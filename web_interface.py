"""
Civitai Scraper Web Interface
Flask-based web UI for browsing, searching, and managing downloads
"""

from flask import Flask, render_template, request, jsonify, send_file
from pathlib import Path
import json
from civitai_scraper import CivitaiScraper
from settings_manager import SettingsManager
from PIL import Image
import io
import threading
import time

app = Flask(__name__)
scraper = None
settings_manager = None
download_thread = None
download_status = {
    'running': False,
    'progress': 0,
    'total': 0,
    'downloaded': 0,
    'skipped': 0,
    'failed': 0,
    'current_file': '',
    'message': 'Ready to start'
}

def init_scraper(output_dir: str = None):
    """Initialize scraper instance using settings"""
    global scraper, settings_manager

    # Initialize settings manager if not already done
    if settings_manager is None:
        settings_manager = SettingsManager()

    # Use settings for output_dir if not specified
    if output_dir is None:
        output_dir = settings_manager.get_download_path()

    # Get database path from settings (always in app data directory)
    db_path = settings_manager.get_database_path()

    print(f"[INIT] Initializing scraper with:")
    print(f"[INIT]   output_dir: {output_dir}")
    print(f"[INIT]   db_path: {db_path}")

    scraper = CivitaiScraper(
        output_dir=str(output_dir),
        use_database=True,
        workers=settings_manager.get('workers', 5),
        api_key=settings_manager.get('api_key') or None,
        organize_by_nsfw=settings_manager.get('organize_by_nsfw', True),
        enable_retry=settings_manager.get('enable_retry', True),
        max_retries=settings_manager.get('max_retries', 3),
        log_level=settings_manager.get('log_level', 'INFO'),
        db_path=str(db_path)
    )

    print(f"[INIT] Scraper initialized:")
    print(f"[INIT]   scraper.output_dir: {scraper.output_dir}")
    print(f"[INIT]   scraper.db_path: {scraper.db_path}")

@app.route('/')
def index():
    """Main gallery page"""
    return render_template('gallery.html')

@app.route('/api/images')
def api_images():
    """API endpoint for image list with pagination and filtering"""
    global scraper
    if scraper is None:
        init_scraper()

    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))

    # Filters
    nsfw_level = request.args.get('nsfw_level')
    file_types = request.args.getlist('file_types')  # Changed to getlist for multiple file types
    models = request.args.getlist('models')  # Changed to getlist for multiple models
    tags = request.args.getlist('tags')
    favorites_only = request.args.get('favorites_only') == 'true'
    aspect_ratio = request.args.get('aspect_ratio')
    sort = request.args.get('sort', 'newest')

    offset = (page - 1) * per_page

    # Build query
    with scraper.db_lock:
        cursor = scraper.db_conn.cursor()

        # Base query - use DISTINCT if filtering by tags (AND logic)
        if tags:
            query = 'SELECT DISTINCT d.* FROM downloads d'
            # Add model join if needed
            if models:
                query += ' LEFT JOIN generation_params gp ON d.image_id = gp.image_id'
            # Add favorites join if needed
            if favorites_only:
                query += ' INNER JOIN favorites f ON d.image_id = f.image_id'
            # INNER JOIN for each tag to ensure ALL tags exist (AND logic)
            for i, tag in enumerate(tags):
                query += f'''
                    INNER JOIN image_tags it{i} ON d.image_id = it{i}.image_id
                    INNER JOIN tags t{i} ON it{i}.tag_id = t{i}.tag_id'''
            query += ' WHERE d.status = "success"'
        elif models or favorites_only:
            query = 'SELECT d.* FROM downloads d'
            if models:
                query += ' LEFT JOIN generation_params gp ON d.image_id = gp.image_id'
            if favorites_only:
                query += ' INNER JOIN favorites f ON d.image_id = f.image_id'
            query += ' WHERE d.status = "success"'
        else:
            query = 'SELECT * FROM downloads WHERE status = "success"'
        params = []

        # Apply filters
        if nsfw_level:
            query += ' AND nsfw_level = ?' if 'd.' not in query else ' AND d.nsfw_level = ?'
            params.append(int(nsfw_level))

        if file_types:
            # Build OR conditions for multiple file types
            type_conditions = []
            type_params = []

            for file_type in file_types:
                if file_type == 'jpg':
                    # Handle both jpg and jpeg
                    type_conditions.append('(file_extension = ? OR file_extension = ?)' if 'd.' not in query else '(d.file_extension = ? OR d.file_extension = ?)')
                    type_params.extend(['jpg', 'jpeg'])
                else:
                    type_conditions.append('file_extension = ?' if 'd.' not in query else 'd.file_extension = ?')
                    type_params.append(file_type)

            if type_conditions:
                query += ' AND (' + ' OR '.join(type_conditions) + ')'
                params.extend(type_params)

        if models:
            # Filter by multiple models
            placeholders = ','.join(['?' for _ in models])
            query += f' AND gp.model_name IN ({placeholders})'
            params.extend(models)

        if tags:
            # Add tag name conditions (AND logic)
            for i, tag in enumerate(tags):
                query += f' AND t{i}.tag_name = ?'
                params.append(tag)

        # Order by sort option (use d. prefix when using tags/models/favorites)
        table_prefix = 'd.' if (tags or models or favorites_only) else ''
        if sort == 'oldest':
            order_by = f'ORDER BY {table_prefix}download_timestamp ASC'
        elif sort == 'largest':
            order_by = f'ORDER BY {table_prefix}file_size DESC'
        elif sort == 'resolution':
            order_by = f'ORDER BY ({table_prefix}width * {table_prefix}height) DESC'
        elif sort == 'reactions':
            order_by = f'ORDER BY {table_prefix}reaction_total DESC'
        else:  # newest (default)
            order_by = f'ORDER BY {table_prefix}download_timestamp DESC'

        # Order and paginate
        query += f' {order_by} LIMIT ? OFFSET ?'
        params.extend([per_page, offset])

        cursor.execute(query, params)
        results = cursor.fetchall()

        # Get total count
        cursor.execute('SELECT COUNT(*) FROM downloads WHERE status = "success"')
        total = cursor.fetchone()[0]

    # Format results
    images = []

    # Get all favorited image IDs in a single query (fix N+1 query issue)
    favorited_ids = set()
    if results:
        image_ids = [row[0] for row in results]
        placeholders = ','.join('?' * len(image_ids))
        cursor.execute(f'SELECT image_id FROM favorites WHERE image_id IN ({placeholders})', image_ids)
        favorited_ids = {row[0] for row in cursor.fetchall()}

    for row in results:
        images.append({
            'id': row[0],
            'filename': row[2],
            'width': row[5],
            'height': row[6],
            'nsfw_level': row[7],
            'timestamp': row[8],
            'folder_path': row[11] if len(row) > 11 else None,
            'reaction_total': row[13] if len(row) > 13 else 0,
            'favorited': row[0] in favorited_ids  # O(1) lookup instead of query
        })

    return jsonify({
        'images': images,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page
    })

@app.route('/api/metadata/<image_id>')
def api_image_metadata(image_id):
    """Get detailed image metadata for fullscreen view"""
    global scraper
    if scraper is None:
        init_scraper()

    with scraper.db_lock:
        cursor = scraper.db_conn.cursor()

        # Get image info
        cursor.execute('SELECT * FROM downloads WHERE image_id = ?', (image_id,))
        image = cursor.fetchone()

        if not image:
            return jsonify({'error': 'Image not found'}), 404

        # Get metadata JSON
        cursor.execute('SELECT json_data FROM metadata WHERE image_id = ?', (image_id,))
        metadata_row = cursor.fetchone()
        metadata_json = json.loads(metadata_row[0]) if metadata_row else {}

        # Get generation params
        cursor.execute('SELECT * FROM generation_params WHERE image_id = ?', (image_id,))
        params = cursor.fetchone()

        # Get tags
        cursor.execute('''
            SELECT t.tag_name FROM tags t
            JOIN image_tags it ON t.tag_id = it.tag_id
            WHERE it.image_id = ?
        ''', (image_id,))
        tags = [row[0] for row in cursor.fetchall()]

    return jsonify({
        'id': image[0],
        'url': image[1],
        'filename': image[2],
        'file_size': image[4],
        'width': image[5],
        'height': image[6],
        'nsfw_level': image[7],
        'timestamp': image[8],
        'stats': metadata_json.get('stats'),
        'generation_params': {
            'prompt': params[1] if params else None,
            'negative_prompt': params[2] if params else None,
            'model_name': params[3] if params else None,
            'sampler_name': params[6] if params else None,
            'steps': params[7] if params else None,
            'cfg_scale': params[8] if params else None,
            'seed': params[9] if params else None
        } if params else None,
        'tags': tags
    })

@app.route('/api/thumbnail/<image_id>')
def api_thumbnail(image_id):
    """Generate and serve thumbnail"""
    global scraper
    if scraper is None:
        init_scraper()

    with scraper.db_lock:
        cursor = scraper.db_conn.cursor()
        cursor.execute('SELECT filename, folder_path, file_extension FROM downloads WHERE image_id = ?', (image_id,))
        result = cursor.fetchone()

    if not result:
        return "Not found", 404

    filename, folder_path, file_ext = result

    # Strip "downloads\" prefix if present (legacy database format)
    if filename.startswith("downloads\\") or filename.startswith("downloads/"):
        clean_filename = filename.replace("downloads\\", "").replace("downloads/", "")
    else:
        clean_filename = filename

    # Construct file path - check both organized and non-organized locations
    possible_paths = []

    if folder_path:
        possible_paths.append(scraper.output_dir / folder_path / clean_filename)

    # Also check in main downloads folder
    possible_paths.append(scraper.output_dir / clean_filename)

    # Check in videos folder
    possible_paths.append(scraper.videos_dir / clean_filename)

    # Check organized video folders
    for nsfw_cat in ["SFW", "Mature", "Adult"]:
        possible_paths.append(scraper.videos_dir / nsfw_cat / clean_filename)
        possible_paths.append(scraper.output_dir / nsfw_cat / clean_filename)

    filepath = None
    # Security: Validate paths to prevent directory traversal (Phase 1.4 fix)
    allowed_bases = [
        scraper.output_dir.resolve(),
        scraper.videos_dir.resolve()
    ]

    for path in possible_paths:
        try:
            resolved_path = path.resolve()
            # Check if path is within allowed directories
            is_safe = any(str(resolved_path).startswith(str(base)) for base in allowed_bases)

            if not is_safe:
                logger.warning(f"Path traversal attempt blocked: {path}")
                continue

            if resolved_path.exists():
                filepath = resolved_path
                break
        except (ValueError, OSError) as e:
            logger.warning(f"Path resolution error: {e}")
            continue

    if not filepath:
        # Debug info
        debug_info = f"File not found: {clean_filename}\n"
        debug_info += f"Output dir: {scraper.output_dir}\n"
        debug_info += f"Checked {len(possible_paths)} locations:\n"
        for p in possible_paths[:3]:  # Show first 3 paths
            debug_info += f"  - {p}\n"
        return debug_info, 404

    # Check if it's a video - just return video icon or placeholder
    video_extensions = ['.mp4', '.webm', '.flv', '.avi', '.mov']
    if file_ext and f'.{file_ext}' in video_extensions:
        # For videos, return a placeholder or video thumbnail
        # For now, just indicate it's a video
        return "Video file - preview not available", 200

    # Generate thumbnail for images
    try:
        img = Image.open(filepath)
        img.thumbnail((300, 300))

        img_io = io.BytesIO()
        img.save(img_io, 'JPEG', quality=85)
        img_io.seek(0)

        return send_file(img_io, mimetype='image/jpeg')
    except Exception as e:
        return f"Error generating thumbnail: {str(e)}", 500

@app.route('/api/image/<image_id>')
def api_serve_image(image_id):
    """Serve full image file"""
    global scraper
    if scraper is None:
        init_scraper()

    with scraper.db_lock:
        cursor = scraper.db_conn.cursor()
        cursor.execute('SELECT filename, folder_path, file_extension FROM downloads WHERE image_id = ?', (image_id,))
        result = cursor.fetchone()

    if not result:
        return "Not found", 404

    filename, folder_path, file_ext = result

    # Strip "downloads\" prefix if present (legacy database format)
    if filename.startswith("downloads\\") or filename.startswith("downloads/"):
        clean_filename = filename.replace("downloads\\", "").replace("downloads/", "")
    else:
        clean_filename = filename

    # Construct file path - check multiple locations
    possible_paths = []

    if folder_path:
        possible_paths.append(scraper.output_dir / folder_path / clean_filename)

    possible_paths.append(scraper.output_dir / clean_filename)
    possible_paths.append(scraper.videos_dir / clean_filename)

    for nsfw_cat in ["SFW", "Mature", "Adult"]:
        possible_paths.append(scraper.videos_dir / nsfw_cat / clean_filename)
        possible_paths.append(scraper.output_dir / nsfw_cat / clean_filename)

    filepath = None
    # Security: Validate paths to prevent directory traversal (Phase 1.4 fix)
    allowed_bases = [
        scraper.output_dir.resolve(),
        scraper.videos_dir.resolve()
    ]

    for path in possible_paths:
        try:
            resolved_path = path.resolve()
            # Check if path is within allowed directories
            is_safe = any(str(resolved_path).startswith(str(base)) for base in allowed_bases)

            if not is_safe:
                logger.warning(f"Path traversal attempt blocked: {path}")
                continue

            if resolved_path.exists():
                filepath = resolved_path
                break
        except (ValueError, OSError) as e:
            logger.warning(f"Path resolution error: {e}")
            continue

    if not filepath:
        # Debug info
        debug_info = f"File not found: {clean_filename}\n"
        debug_info += f"Output dir: {scraper.output_dir}\n"
        debug_info += f"Checked {len(possible_paths)} locations:\n"
        for p in possible_paths[:3]:  # Show first 3 paths
            debug_info += f"  - {p}\n"
        return debug_info, 404

    # Serve the file
    try:
        return send_file(filepath)
    except Exception as e:
        return str(e), 500

@app.route('/api/statistics')
def api_statistics():
    """Get statistics for dashboard"""
    stats = scraper.get_download_stats()

    # Get tag statistics
    tags = scraper.get_all_tags(min_count=5)[:20]  # Top 20 tags

    # Get model statistics
    models = scraper.get_all_models()[:20]  # Top 20 models

    with scraper.db_lock:
        cursor = scraper.db_conn.cursor()

        # Downloads by date
        cursor.execute('''
            SELECT DATE(download_timestamp) as date, COUNT(*) as count
            FROM downloads
            WHERE status = "success"
            GROUP BY date
            ORDER BY date DESC
            LIMIT 30
        ''')
        downloads_by_date = cursor.fetchall()

    return jsonify({
        'total_downloads': stats.get('by_status', {}).get('success', 0),
        'total_size': stats.get('total_bytes', 0),
        'avg_resolution': stats.get('avg_resolution'),
        'by_type': stats.get('by_type', {}),
        'top_tags': [{'name': tag, 'count': count} for tag, count in tags],
        'top_models': [{'name': model, 'count': count} for model, count in models],
        'downloads_by_date': [{'date': date, 'count': count} for date, count in downloads_by_date]
    })

@app.route('/api/image/<image_id>/delete', methods=['DELETE'])
def api_delete_image(image_id):
    """Delete image file, metadata file, and database records"""
    try:
        with scraper.db_lock:
            cursor = scraper.db_conn.cursor()

            # Get file info from database
            cursor.execute('SELECT filename, folder_path FROM downloads WHERE image_id = ?', (image_id,))
            result = cursor.fetchone()

            if not result:
                return jsonify({'success': False, 'error': 'Image not found in database'}), 404

            filename, folder_path = result

            # Strip "downloads\" prefix if present
            if filename.startswith('downloads\\') or filename.startswith('downloads/'):
                clean_filename = filename.replace('downloads\\', '').replace('downloads/', '')
            else:
                clean_filename = filename

            # Find and delete image file
            possible_paths = []
            if folder_path:
                possible_paths.append(scraper.output_dir / folder_path / clean_filename)
            possible_paths.append(scraper.output_dir / clean_filename)
            possible_paths.append(scraper.videos_dir / clean_filename)
            for nsfw_cat in ["SFW", "Mature", "Adult"]:
                possible_paths.append(scraper.videos_dir / nsfw_cat / clean_filename)
                possible_paths.append(scraper.output_dir / nsfw_cat / clean_filename)

            image_deleted = False
            for path in possible_paths:
                if path.exists():
                    path.unlink()
                    image_deleted = True
                    break

            # Delete metadata JSON file
            base_name = clean_filename.rsplit('.', 1)[0]
            metadata_paths = []

            # Check in organized metadata folders
            for nsfw_cat in ["SFW", "Mature", "Adult"]:
                metadata_paths.append(scraper.output_dir / nsfw_cat / "metadata" / f"{base_name}.json")

            # Check in main metadata folder
            metadata_paths.append(scraper.metadata_dir / f"{base_name}.json")

            metadata_deleted = False
            for meta_path in metadata_paths:
                if meta_path.exists():
                    meta_path.unlink()
                    metadata_deleted = True

            # Delete from database (Phase 1.5: Fix orphaned records)
            cursor.execute('DELETE FROM downloads WHERE image_id = ?', (image_id,))
            cursor.execute('DELETE FROM generation_params WHERE image_id = ?', (image_id,))
            cursor.execute('DELETE FROM image_tags WHERE image_id = ?', (image_id,))
            cursor.execute('DELETE FROM metadata WHERE image_id = ?', (image_id,))
            cursor.execute('DELETE FROM favorites WHERE image_id = ?', (image_id,))
            scraper.db_conn.commit()

            return jsonify({
                'success': True,
                'image_deleted': image_deleted,
                'metadata_deleted': metadata_deleted,
                'message': 'Image, metadata, and database records deleted successfully'
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/image/<image_id>/metadata', methods=['PUT'])
def api_update_metadata(image_id):
    """Update metadata for an image"""
    try:
        data = request.get_json()

        with scraper.db_lock:
            cursor = scraper.db_conn.cursor()

            # Check if image exists
            cursor.execute('SELECT 1 FROM downloads WHERE image_id = ?', (image_id,))
            if not cursor.fetchone():
                return jsonify({'success': False, 'error': 'Image not found'}), 404

            # Update generation_params table
            cursor.execute('''
                UPDATE generation_params
                SET prompt = ?, negative_prompt = ?, model_name = ?,
                    sampler_name = ?, steps = ?, cfg_scale = ?, seed = ?
                WHERE image_id = ?
            ''', (
                data.get('prompt'),
                data.get('negative_prompt'),
                data.get('model'),
                data.get('sampler'),
                data.get('steps'),
                data.get('cfg_scale'),
                data.get('seed'),
                image_id
            ))

            scraper.db_conn.commit()

            return jsonify({
                'success': True,
                'message': 'Metadata updated successfully'
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tags')
def api_tags():
    """Get all tags for autocomplete"""
    tags = scraper.get_all_tags()
    return jsonify([tag for tag, count in tags])

@app.route('/api/image/<image_id>/favorite', methods=['POST'])
def api_favorite_image(image_id):
    """Add to favorites"""
    try:
        from datetime import datetime

        with scraper.db_lock:
            cursor = scraper.db_conn.cursor()

            cursor.execute('SELECT 1 FROM downloads WHERE image_id = ?', (image_id,))
            if not cursor.fetchone():
                return jsonify({'success': False, 'error': 'Not found'}), 404

            cursor.execute('''
                INSERT OR IGNORE INTO favorites (image_id, favorited_at)
                VALUES (?, ?)
            ''', (image_id, datetime.now().isoformat()))

            scraper.db_conn.commit()

        return jsonify({'success': True, 'favorited': True})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/image/<image_id>/unfavorite', methods=['POST'])
def api_unfavorite_image(image_id):
    """Remove from favorites"""
    try:
        with scraper.db_lock:
            cursor = scraper.db_conn.cursor()
            cursor.execute('DELETE FROM favorites WHERE image_id = ?', (image_id,))
            scraper.db_conn.commit()

        return jsonify({'success': True, 'favorited': False})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/image/<image_id>/favorite/status')
def api_favorite_status(image_id):
    """Check favorite status"""
    with scraper.db_lock:
        cursor = scraper.db_conn.cursor()
        cursor.execute('SELECT 1 FROM favorites WHERE image_id = ?', (image_id,))
        is_favorited = cursor.fetchone() is not None

    return jsonify({'favorited': is_favorited})

@app.route('/api/favorites/organize', methods=['POST'])
def api_organize_favorites():
    """Organize favorite images into a Favorites directory using symlinks"""
    import os
    import shutil
    from pathlib import Path

    try:
        data = request.get_json() or {}
        use_symlinks = data.get('use_symlinks', True)  # Default to symlinks for performance

        download_path = Path(scraper.settings.get_download_path())
        favorites_dir = download_path / 'Favorites'

        # Create favorites directory structure
        favorites_dir.mkdir(exist_ok=True)
        if scraper.settings.get('organize_by_nsfw', True):
            (favorites_dir / 'SFW').mkdir(exist_ok=True)
            (favorites_dir / 'Mature').mkdir(exist_ok=True)
            (favorites_dir / 'Adult').mkdir(exist_ok=True)

        with scraper.db_lock:
            cursor = scraper.db_conn.cursor()

            # Get all favorited images with their file paths
            cursor.execute('''
                SELECT d.image_id, d.filename, d.folder_path, d.nsfw_level
                FROM downloads d
                INNER JOIN favorites f ON d.image_id = f.image_id
                WHERE d.status = 'success'
            ''')

            favorites = cursor.fetchall()

            organized = 0
            skipped = 0
            errors = []

            for image_id, filename, folder_path, nsfw_level in favorites:
                try:
                    # Determine source file path
                    if folder_path:
                        source = Path(folder_path) / filename
                    else:
                        source = download_path / filename

                    if not source.exists():
                        skipped += 1
                        errors.append(f"File not found: {filename}")
                        continue

                    # Determine destination based on NSFW level
                    if scraper.settings.get('organize_by_nsfw', True):
                        if nsfw_level == 1:
                            dest_dir = favorites_dir / 'SFW'
                        elif nsfw_level in [2, 4]:
                            dest_dir = favorites_dir / 'Mature'
                        else:
                            dest_dir = favorites_dir / 'Adult'
                    else:
                        dest_dir = favorites_dir

                    dest = dest_dir / filename

                    # Skip if already exists
                    if dest.exists():
                        organized += 1
                        continue

                    # Create symlink or copy
                    if use_symlinks:
                        try:
                            # Try creating symlink (requires admin on Windows)
                            os.symlink(source, dest)
                            organized += 1
                        except OSError:
                            # Fallback to hard link, then copy
                            try:
                                os.link(source, dest)
                                organized += 1
                            except OSError:
                                shutil.copy2(source, dest)
                                organized += 1
                    else:
                        # Direct copy
                        shutil.copy2(source, dest)
                        organized += 1

                except Exception as e:
                    errors.append(f"{filename}: {str(e)}")
                    skipped += 1

        return jsonify({
            'success': True,
            'organized': organized,
            'skipped': skipped,
            'total': len(favorites),
            'favorites_dir': str(favorites_dir),
            'errors': errors[:10]  # Return first 10 errors
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/favorites/clean', methods=['POST'])
def api_clean_favorites():
    """Remove unfavorited images from Favorites directory"""
    import os
    from pathlib import Path

    try:
        download_path = Path(scraper.settings.get_download_path())
        favorites_dir = download_path / 'Favorites'

        if not favorites_dir.exists():
            return jsonify({'success': True, 'removed': 0, 'message': 'Favorites directory does not exist'})

        with scraper.db_lock:
            cursor = scraper.db_conn.cursor()

            # Get all favorited filenames
            cursor.execute('''
                SELECT d.filename
                FROM downloads d
                INNER JOIN favorites f ON d.image_id = f.image_id
                WHERE d.status = 'success'
            ''')

            favorited_files = {row[0] for row in cursor.fetchall()}

        removed = 0

        # Walk through favorites directory and remove non-favorited files
        for root, dirs, files in os.walk(favorites_dir):
            for filename in files:
                if filename not in favorited_files:
                    file_path = Path(root) / filename
                    try:
                        file_path.unlink()
                        removed += 1
                    except Exception:
                        pass

        return jsonify({
            'success': True,
            'removed': removed,
            'message': f'Removed {removed} unfavorited images from Favorites directory'
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/models')
def api_models():
    """Get all models for autocomplete"""
    models = scraper.get_all_models()
    return jsonify([model for model, count in models])

@app.route('/api/tags/fetch', methods=['POST'])
def api_fetch_tags():
    """Trigger batch tag fetching"""
    try:
        data = request.get_json() or {}
        max_images = data.get('max_images', 100)
        delay = data.get('delay', 1.0)

        stats = scraper.batch_fetch_missing_tags(max_images=max_images, delay=delay)

        return jsonify({'success': True, 'stats': stats})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/metadata/fetch', methods=['POST'])
def api_fetch_metadata():
    """Trigger batch metadata fetching for images missing generation params"""
    try:
        data = request.get_json() or {}
        max_images = data.get('max_images', 100)
        delay = data.get('delay', 1.0)

        stats = scraper.batch_fetch_missing_metadata(max_images=max_images, delay=delay)

        return jsonify({'success': True, 'stats': stats})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/models/list')
def api_models_list():
    """Get list of all unique model names with counts"""
    with scraper.db_lock:
        cursor = scraper.db_conn.cursor()
        cursor.execute('''
            SELECT gp.model_name, COUNT(*) as count
            FROM generation_params gp
            JOIN downloads d ON gp.image_id = d.image_id
            WHERE d.status = 'success' AND gp.model_name IS NOT NULL AND gp.model_name != ''
            GROUP BY gp.model_name
            ORDER BY count DESC
        ''')
        models = [{'name': row[0], 'count': row[1]} for row in cursor.fetchall()]

    return jsonify({'models': models})

@app.route('/api/tags/status')
def api_tags_status():
    """Get tag fetching status"""
    with scraper.db_lock:
        cursor = scraper.db_conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM downloads WHERE status = "success"')
        total_images = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM downloads WHERE tags_fetched = 1')
        tagged_images = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM tags')
        total_tags = cursor.fetchone()[0]

    pending = total_images - tagged_images
    completion = (tagged_images / total_images * 100) if total_images > 0 else 0

    return jsonify({
        'total_images': total_images,
        'tagged_images': tagged_images,
        'pending_images': pending,
        'total_tags': total_tags,
        'completion_percentage': round(completion, 1)
    })

@app.route('/api/tags/all')
def api_tags_all():
    """Get ALL tags sorted by usage count for statistics page"""
    all_tags = scraper.get_all_tags(min_count=1)

    tags_list = [{'name': tag[0], 'count': tag[1]} for tag in all_tags]

    return jsonify({
        'tags': tags_list,
        'total': len(tags_list)
    })

@app.route('/api/tags/gallery')
def api_tags_gallery():
    """Get popular tags for gallery filtering (top 100)"""
    tags = scraper.get_all_tags(min_count=5)[:100]  # Top 100 with 5+ uses

    tags_list = [{'name': tag[0], 'count': tag[1]} for tag in tags]

    return jsonify({'tags': tags_list})

@app.route('/control')
def control_panel():
    """Download control panel page"""
    return render_template('control.html')

@app.route('/statistics')
def statistics_page():
    """Statistics dashboard page"""
    return render_template('statistics.html')

@app.route('/api/download/start', methods=['POST'])
def api_start_download():
    """Start a download session with specified parameters"""
    global download_thread, download_status

    if download_status['running']:
        return jsonify({'error': 'Download already in progress'}), 400

    # Get parameters from request
    params = request.json

    # Reset status
    num_images = params.get('num_images')
    # Handle None (endless mode) - set to 0 for display purposes
    total_for_display = num_images if num_images is not None else 0

    download_status = {
        'running': True,
        'progress': 0,
        'total': total_for_display,
        'downloaded': 0,
        'skipped': 0,
        'failed': 0,
        'current_file': '',
        'message': 'Starting download...' if num_images else 'Starting download (endless mode)...'
    }

    # Start download in background thread
    download_thread = threading.Thread(
        target=run_download_task,
        args=(params,),
        daemon=True
    )
    download_thread.start()

    return jsonify({'status': 'started', 'message': 'Download started successfully'})

@app.route('/api/download/stop', methods=['POST'])
def api_stop_download():
    """Stop the current download session"""
    global download_status

    if not download_status['running']:
        return jsonify({'error': 'No download in progress'}), 400

    # Signal scraper to stop
    if scraper:
        scraper.running = False

    download_status['running'] = False
    download_status['message'] = 'Stopping download...'

    return jsonify({'status': 'stopping', 'message': 'Download will stop after current file'})

@app.route('/api/download/status')
def api_download_status():
    """Get current download status"""
    # Update progress from scraper if running
    if download_status['running'] and scraper:
        download_status['downloaded'] = scraper.downloaded_count
        download_status['skipped'] = scraper.skipped_count
        download_status['failed'] = scraper.failed_count

        total = download_status['downloaded'] + download_status['skipped']
        if download_status['total'] is not None and download_status['total'] > 0:
            download_status['progress'] = int((total / download_status['total']) * 100)
        else:
            # Endless mode - show total count instead of percentage
            download_status['progress'] = 0  # Can't calculate percentage in endless mode

    return jsonify(download_status)

def run_download_task(params):
    """Run download task in background thread"""
    global download_status, scraper

    old_scraper = scraper  # Save reference before try block

    try:
        # Create new scraper instance for this download
        temp_scraper = CivitaiScraper(
            output_dir=params.get('output_dir', r'D:\civitai-scraper\downloads'),
            workers=params.get('workers', 5),
            allowed_types=params.get('file_types'),
            use_database=True,
            enable_retry=params.get('enable_retry', True),
            max_retries=params.get('max_retries', 3),
            organize_by_nsfw=params.get('organize_by_nsfw', False),
            api_key=params.get('api_key'),
            enable_signal_handler=False  # Disable signal handler in background thread
        )

        # Update global scraper reference for status updates
        scraper = temp_scraper

        download_status['message'] = 'Downloading images...'

        # Parse numeric parameters to ensure they're integers or None
        # Phase 2.1: Replaced print with logger.debug
        min_res = params.get('min_resolution')
        logger.debug(f"min_resolution from params: {repr(min_res)} (type: {type(min_res).__name__})")
        if min_res is not None and min_res != '':
            try:
                min_res = int(min_res)
                logger.debug(f"min_resolution after conversion: {min_res}")
            except (ValueError, TypeError) as e:
                logger.debug(f"min_resolution conversion failed: {e}")
                min_res = None
        else:
            min_res = None

        model_id = params.get('model_id')
        logger.debug(f"model_id from params: {repr(model_id)} (type: {type(model_id).__name__})")
        if model_id is not None and model_id != '':
            try:
                model_id = int(model_id)
                logger.debug(f"model_id after conversion: {model_id}")
            except (ValueError, TypeError) as e:
                logger.debug(f"model_id conversion failed: {e}")
                model_id = None
        else:
            model_id = None

        min_reactions = params.get('min_reactions')
        logger.debug(f"min_reactions from params: {repr(min_reactions)} (type: {type(min_reactions).__name__})")
        if min_reactions is not None and min_reactions != '':
            try:
                min_reactions = int(min_reactions)
                logger.debug(f"min_reactions after conversion: {min_reactions}")
            except (ValueError, TypeError) as e:
                logger.debug(f"min_reactions conversion failed: {e}")
                min_reactions = None
        else:
            min_reactions = None

        logger.debug(f"Final values - min_resolution: {min_res}, model_id: {model_id}, min_reactions: {min_reactions}")

        # Start scraping
        temp_scraper.scrape(
            max_images=params.get('num_images'),
            endless=params.get('endless', False),
            sort=params.get('sort', 'Most Reactions'),
            period=params.get('period', 'AllTime'),
            nsfw=params.get('nsfw'),
            username=params.get('username'),
            modelId=model_id,
            min_resolution=min_res,
            min_reactions=min_reactions,
            save_metadata=not params.get('no_metadata', False),
            delay=params.get('delay', 0.5),
            nsfw_only=params.get('nsfw_only', False),
            show_progress=False  # Disable progress bar in web mode
        )

        download_status['running'] = False
        download_status['message'] = 'Download completed successfully'

        # Restore original scraper
        scraper = old_scraper

    except Exception as e:
        download_status['running'] = False
        download_status['message'] = f'Error: {str(e)}'
        # Restore original scraper
        scraper = old_scraper

# ========== SETTINGS ENDPOINTS ==========

@app.route('/settings')
def settings_page():
    """Settings page"""
    return render_template('settings.html')

@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    """Get current settings"""
    global settings_manager
    if settings_manager is None:
        settings_manager = SettingsManager()

    return jsonify({
        'success': True,
        'settings': settings_manager.get_all(),
        'database_path': str(settings_manager.get_database_path()),
        'download_path_resolved': str(settings_manager.get_download_path())
    })

@app.route('/api/settings', methods=['POST'])
def api_update_settings():
    """Update settings"""
    global settings_manager
    if settings_manager is None:
        settings_manager = SettingsManager()

    try:
        updates = request.get_json()
        settings_manager.update(updates)

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/settings/validate')
def api_validate_settings():
    """Validate current settings paths"""
    global settings_manager
    if settings_manager is None:
        settings_manager = SettingsManager()

    validation = settings_manager.validate_paths()
    return jsonify(validation)

@app.route('/api/settings/reset', methods=['POST'])
def api_reset_settings():
    """Reset settings to defaults"""
    global settings_manager
    if settings_manager is None:
        settings_manager = SettingsManager()

    try:
        settings_manager.reset_to_defaults()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

def run_web_interface(output_dir: str = None, port: int = 5000):
    """Start web interface"""
    global settings_manager

    # Initialize settings manager
    settings_manager = SettingsManager()

    # Use settings if output_dir not specified
    if output_dir is None:
        output_dir = settings_manager.get_download_path()

    init_scraper(output_dir)

    print(f"\n{'='*60}")
    print(f"  Civitai Scraper Web Interface")
    print(f"{'='*60}")
    print(f"  Server running at: http://localhost:{port}")
    print(f"  Download directory: {output_dir}")
    print(f"  Database: {settings_manager.get_database_path()}")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*60}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
