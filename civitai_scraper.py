#!/usr/bin/env python3
"""
Civitai Image Scraper
Downloads images from civitai.com with support for filters and sorting
"""

import requests
import os
import json
import time
import argparse
import signal
import sys
import msvcrt
import logging
import sqlite3
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from urllib.parse import urljoin
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from dataclasses import dataclass


@dataclass
class DownloadStatistics:
    """Track download statistics"""
    start_time: float
    total_downloaded: int = 0
    total_bytes: int = 0

    def add_download(self, file_size: int):
        """Record a successful download"""
        self.total_downloaded += 1
        self.total_bytes += file_size

    def get_speed(self) -> float:
        """Get average speed in bytes/sec"""
        elapsed = time.time() - self.start_time
        return self.total_bytes / elapsed if elapsed > 0 else 0

    def format_speed(self) -> str:
        """Format speed as human readable"""
        speed = self.get_speed()
        if speed < 1024:
            return f"{speed:.1f} B/s"
        elif speed < 1024 * 1024:
            return f"{speed / 1024:.1f} KB/s"
        else:
            return f"{speed / (1024 * 1024):.2f} MB/s"

    def format_size(self) -> str:
        """Format total size"""
        if self.total_bytes < 1024 * 1024:
            return f"{self.total_bytes / 1024:.1f} KB"
        elif self.total_bytes < 1024 * 1024 * 1024:
            return f"{self.total_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{self.total_bytes / (1024 * 1024 * 1024):.2f} GB"

    def calculate_eta(self, remaining: int) -> str:
        """Calculate ETA for remaining downloads"""
        if remaining <= 0 or self.total_downloaded == 0:
            return "N/A"

        avg_file_size = self.total_bytes / self.total_downloaded
        remaining_bytes = remaining * avg_file_size
        speed = self.get_speed()

        if speed == 0:
            return "calculating..."

        eta_seconds = int(remaining_bytes / speed)

        if eta_seconds < 60:
            return f"{eta_seconds}s"
        elif eta_seconds < 3600:
            return f"{eta_seconds // 60}m {eta_seconds % 60}s"
        else:
            return f"{eta_seconds // 3600}h {(eta_seconds % 3600) // 60}m"


class CivitaiScraper:
    def __init__(self, output_dir: str = "downloads", workers: int = 5, allowed_types: Optional[List[str]] = None,
                 log_level: str = "INFO", log_file: Optional[str] = None, use_database: bool = True,
                 enable_retry: bool = True, max_retries: int = 3, dry_run: bool = False,
                 api_key: Optional[str] = None, organize_by_nsfw: bool = True, enable_signal_handler: bool = True,
                 db_path: Optional[str] = None):
        """
        Initialize the Civitai scraper

        Args:
            output_dir: Directory to save downloaded images
            workers: Number of concurrent download threads
            allowed_types: List of allowed file types (e.g., ['jpg', 'png']). None = allow all
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
            log_file: Optional log file path
            use_database: Use SQLite database instead of text log
            enable_retry: Enable retry logic for failed downloads
            max_retries: Maximum retry attempts per download
            dry_run: Preview mode without downloading files
            api_key: Civitai API key for authenticated requests
            organize_by_nsfw: Organize files into SFW/Mature/Adult folders
            enable_signal_handler: Enable signal handler for Ctrl+C (disable for threading)
            db_path: Optional custom database path (defaults to output_dir/download_history.db)
        """
        # Initialize logging first
        self._setup_logging(log_level, log_file)

        self.base_url = "https://civitai.com/api/v1/images"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create metadata subfolder
        self.metadata_dir = self.output_dir / "metadata"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

        # Create videos subfolder
        self.videos_dir = self.output_dir / "videos"
        self.videos_dir.mkdir(parents=True, exist_ok=True)

        # Download log file
        self.log_file = self.output_dir / "download_log.txt"

        # Store settings BEFORE database initialization
        self.workers = workers
        self.allowed_types = allowed_types  # List of allowed file extensions (e.g., ['jpg', 'png'])
        self.enable_retry = enable_retry
        self.max_retries = max_retries
        self.dry_run = dry_run
        self.api_key = api_key
        self.organize_by_nsfw = organize_by_nsfw
        self.custom_db_path = Path(db_path) if db_path else None

        # Initialize database or text log
        self.use_database = use_database
        if use_database:
            self._init_database()
            self._migrate_text_log_to_db()
        else:
            self.downloaded_ids = self._load_download_log()

        # Create organized directory structure if needed
        if organize_by_nsfw:
            self._create_organized_directories()

        # Setup session with API key if provided
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if self.api_key:
            self.session.headers.update({
                'Authorization': f'Bearer {self.api_key}'
            })
            self.logger.info("Using authenticated API (API key provided)")

        self.stats_lock = Lock()
        self.downloaded_count = 0
        self.skipped_count = 0
        self.failed_count = 0
        self.filtered_type_count = 0  # Counter for files filtered by type
        self.running = True
        self.paused = False

        # Initialize download statistics
        self.stats = DownloadStatistics(start_time=time.time())

        # Setup signal handler for graceful shutdown (only in main thread)
        if enable_signal_handler:
            try:
                signal.signal(signal.SIGINT, self._signal_handler)
            except ValueError:
                # Signal can only be set in main thread, ignore in worker threads
                pass

    def _signal_handler(self, signum, frame):
        """Handle Ctrl+C gracefully"""
        print("\n\nReceived interrupt signal. Finishing current downloads...")
        self.running = False

    def _setup_logging(self, log_level: str = "INFO", log_file: Optional[str] = None):
        """Setup logging configuration with console and optional file handler"""
        self.logger = logging.getLogger('CivitaiScraper')
        self.logger.setLevel(getattr(logging, log_level.upper()))

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_format)
        self.logger.addHandler(console_handler)

        # Optional file handler
        if log_file:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            file_format = logging.Formatter(
                '%(asctime)s [%(levelname)s] %(threadName)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_format)
            self.logger.addHandler(file_handler)

    def _init_database(self):
        """Initialize SQLite database"""
        # Use custom path if provided, otherwise use output_dir
        if self.custom_db_path:
            self.db_path = self.custom_db_path
        else:
            self.db_path = self.output_dir / "download_history.db"

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.db_conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.db_lock = Lock()

        cursor = self.db_conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
                image_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_extension TEXT,
                file_size INTEGER,
                width INTEGER,
                height INTEGER,
                nsfw_level INTEGER,
                download_timestamp TEXT NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS metadata (
                image_id TEXT PRIMARY KEY,
                json_data TEXT NOT NULL,
                FOREIGN KEY (image_id) REFERENCES downloads(image_id)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_status ON downloads(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON downloads(download_timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_nsfw_level ON downloads(nsfw_level)')

        # Enhanced metadata tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS generation_params (
                image_id TEXT PRIMARY KEY,
                prompt TEXT,
                negative_prompt TEXT,
                model_name TEXT,
                model_hash TEXT,
                sampler_name TEXT,
                steps INTEGER,
                cfg_scale REAL,
                seed INTEGER,
                clip_skip INTEGER,
                raw_params TEXT,
                FOREIGN KEY (image_id) REFERENCES downloads(image_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_name TEXT UNIQUE NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS image_tags (
                image_id TEXT,
                tag_id INTEGER,
                PRIMARY KEY (image_id, tag_id),
                FOREIGN KEY (image_id) REFERENCES downloads(image_id),
                FOREIGN KEY (tag_id) REFERENCES tags(tag_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS favorites (
                image_id TEXT PRIMARY KEY,
                favorited_at TEXT NOT NULL,
                FOREIGN KEY (image_id) REFERENCES downloads(image_id)
            )
        ''')

        # Indexes for enhanced search
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_prompt ON generation_params(prompt)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_model_name ON generation_params(model_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sampler ON generation_params(sampler_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_name ON tags(tag_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_favorited_at ON favorites(favorited_at)')

        # Additional missing indexes for performance (Phase 1.3 optimization)
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_extension ON downloads(file_extension)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_folder_path ON downloads(folder_path)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_id ON image_tags(tag_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_status_reactions ON downloads(status, reaction_total)')

        # Add folder_path column if it doesn't exist (for organization feature)
        try:
            cursor.execute('ALTER TABLE downloads ADD COLUMN folder_path TEXT')
        except sqlite3.OperationalError:
            # Column already exists
            pass

        # Add tags_fetched column for tracking tag fetch status
        try:
            cursor.execute('ALTER TABLE downloads ADD COLUMN tags_fetched BOOLEAN DEFAULT 0')
        except sqlite3.OperationalError:
            # Column already exists
            pass

        # Add reaction_total column for sorting by popularity
        try:
            cursor.execute('ALTER TABLE downloads ADD COLUMN reaction_total INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            # Column already exists
            pass

        # Backfill reaction totals from metadata
        cursor.execute('''
            SELECT d.image_id, m.json_data
            FROM downloads d
            LEFT JOIN metadata m ON d.image_id = m.image_id
            WHERE (d.reaction_total IS NULL OR d.reaction_total = 0) AND m.json_data IS NOT NULL
        ''')

        rows_to_update = cursor.fetchall()
        if rows_to_update:
            self.logger.info(f"Backfilling reaction totals for {len(rows_to_update)} images...")
            for row in rows_to_update:
                image_id, json_data = row
                if json_data:
                    try:
                        metadata = json.loads(json_data)
                        stats = metadata.get('stats', {})
                        total = (
                            stats.get('likeCount', 0) +
                            stats.get('heartCount', 0) +
                            stats.get('commentCount', 0)
                        )
                        cursor.execute(
                            'UPDATE downloads SET reaction_total = ? WHERE image_id = ?',
                            (total, image_id)
                        )
                    except (json.JSONDecodeError, KeyError, TypeError) as e:
                        self.logger.debug(f"Failed to parse reaction total for {image_id}: {e}")
                    except Exception as e:
                        self.logger.error(f"Unexpected error updating reaction total: {e}")

        # Create index for reaction sorting performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_reaction_total ON downloads(reaction_total)')

        self.db_conn.commit()
        self.logger.info(f"Database initialized at {self.db_path}")

    def _migrate_text_log_to_db(self):
        """Migrate existing download_log.txt to database"""
        if not self.log_file.exists():
            return

        self.logger.info("Migrating download_log.txt to database...")

        with open(self.log_file, 'r', encoding='utf-8') as f:
            image_ids = [line.strip() for line in f if line.strip()]

        cursor = self.db_conn.cursor()
        for image_id in image_ids:
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO downloads
                    (image_id, url, filename, download_timestamp, status)
                    VALUES (?, ?, ?, ?, ?)
                ''', (image_id, '', f'civitai_{image_id}',
                      datetime.now().isoformat(), 'migrated'))
            except sqlite3.Error as e:
                self.logger.debug(f"Migration insert failed for {image_id}: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error during migration: {e}")

        self.db_conn.commit()

        # Backup old log
        backup_path = self.log_file.with_suffix('.txt.bak')
        self.log_file.rename(backup_path)
        self.logger.info(f"Migrated {len(image_ids)} entries. Backup: {backup_path}")

    def _parse_int(self, value) -> Optional[int]:
        """Safely parse integer from various formats"""
        try:
            return int(value) if value is not None else None
        except (ValueError, TypeError):
            return None

    def _parse_float(self, value) -> Optional[float]:
        """Safely parse float from various formats"""
        try:
            return float(value) if value is not None else None
        except (ValueError, TypeError):
            return None

    def _extract_generation_params(self, meta: Dict) -> Dict:
        """Extract generation parameters from meta field"""
        # Extract model name - handle multiple metadata formats
        model_name = meta.get('model', '')

        if not model_name:
            # Try baseModel for newer Flux images
            model_name = meta.get('baseModel', '')
            # If baseModel exists, try to get specific checkpoint from civitaiResources
            if model_name and 'civitaiResources' in meta:
                resources = meta.get('civitaiResources', [])
                for resource in resources:
                    if resource.get('type') == 'checkpoint':
                        # Store as "baseModel (version_id)"
                        version_id = resource.get('modelVersionId', '')
                        if version_id:
                            model_name = f"{model_name} (v{version_id})"
                        break

        if not model_name:
            # Try to extract from keys ending with "Version" (e.g., "ponyDiffusionV6XL_v6StartWithThisOne Version")
            # This format is used by some image generation tools like ComfyUI
            for key in meta.keys():
                if key.endswith(' Version') or key.endswith('Version'):
                    # Extract model name from the key (remove ' Version' suffix)
                    model_name = key.replace(' Version', '').strip()
                    break

        return {
            'prompt': meta.get('prompt', ''),
            'negative_prompt': meta.get('negativePrompt', ''),
            'model_name': model_name,
            'model_hash': meta.get('Model hash', ''),
            'sampler_name': meta.get('sampler', meta.get('Sampler', '')),
            'steps': self._parse_int(meta.get('steps', meta.get('Steps'))),
            'cfg_scale': self._parse_float(meta.get('cfgScale', meta.get('CFG scale'))),
            'seed': self._parse_int(meta.get('seed', meta.get('Seed'))),
            'clip_skip': self._parse_int(meta.get('Clip skip')),
            'raw_params': json.dumps(meta)
        }

    def _store_generation_params(self, image_id: str, meta: Dict):
        """Store generation parameters in database"""
        if not meta:
            return

        params = self._extract_generation_params(meta)

        with self.db_lock:
            cursor = self.db_conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO generation_params
                (image_id, prompt, negative_prompt, model_name, model_hash,
                 sampler_name, steps, cfg_scale, seed, clip_skip, raw_params)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (image_id, params['prompt'], params['negative_prompt'],
                  params['model_name'], params['model_hash'], params['sampler_name'],
                  params['steps'], params['cfg_scale'], params['seed'],
                  params['clip_skip'], params['raw_params']))
            self.db_conn.commit()

    def _store_tags(self, image_id: str, tags: List[str]):
        """Store tags in database with many-to-many relationship"""
        if not tags:
            return

        with self.db_lock:
            cursor = self.db_conn.cursor()

            for tag in tags:
                # Insert tag if doesn't exist
                cursor.execute('INSERT OR IGNORE INTO tags (tag_name) VALUES (?)', (tag,))

                # Get tag_id
                cursor.execute('SELECT tag_id FROM tags WHERE tag_name = ?', (tag,))
                tag_id = cursor.fetchone()[0]

                # Link image to tag
                cursor.execute('''
                    INSERT OR IGNORE INTO image_tags (image_id, tag_id)
                    VALUES (?, ?)
                ''', (image_id, tag_id))

            self.db_conn.commit()

    def _convert_nsfw_to_level(self, nsfw_value) -> int:
        """Convert NSFW string label or level to integer level

        API returns either:
        - nsfwLevel: integer (0-6) or string number
        - nsfw: string label ('None', 'Soft', 'Mature', 'X', 'XXX', etc.)

        Mapping:
        - None/Soft: 0-1 (SFW)
        - Mature/Mature+: 2-4 (Mature)
        - X/XXX: 5-6 (Adult)
        """
        if nsfw_value is None:
            return 0

        # Try to convert to int first (if it's already a number)
        try:
            return int(nsfw_value)
        except (ValueError, TypeError):
            pass

        # Map string labels to levels
        nsfw_str = str(nsfw_value).upper()
        nsfw_mapping = {
            'NONE': 0,
            'SOFT': 1,
            'MATURE': 2,
            'MATURE+': 4,
            'X': 5,
            'XXX': 6
        }

        level = nsfw_mapping.get(nsfw_str, 0)
        if nsfw_str not in nsfw_mapping:
            self.logger.warning(f"Unknown NSFW value: {repr(nsfw_value)}, defaulting to level 0")

        return level

    def _get_nsfw_folder(self, nsfw_level: int) -> str:
        """Determine folder name based on NSFW level

        Returns:
            - "SFW" for Safe content (levels 0-1: None, Soft)
            - "NSFW" for adult content (levels 2-6: Mature, Mature+, X, XXX)
        """
        level = self._convert_nsfw_to_level(nsfw_level)

        if level <= 1:
            return "SFW"
        else:
            return "NSFW"

    def _create_organized_directories(self):
        """Create organized directory structure with SFW/NSFW folders"""
        for nsfw_category in ["SFW", "NSFW"]:
            # Main image folder
            category_dir = self.output_dir / nsfw_category
            category_dir.mkdir(parents=True, exist_ok=True)

            # Metadata subfolder
            meta_dir = category_dir / "metadata"
            meta_dir.mkdir(parents=True, exist_ok=True)

            # Video subfolder
            video_dir = self.videos_dir / nsfw_category
            video_dir.mkdir(parents=True, exist_ok=True)

    def _is_downloaded_db(self, image_id: str) -> bool:
        """Check if downloaded via database"""
        with self.db_lock:
            cursor = self.db_conn.cursor()
            cursor.execute('SELECT 1 FROM downloads WHERE image_id = ? AND status IN (?, ?)',
                          (str(image_id), 'success', 'migrated'))
            return cursor.fetchone() is not None

    def _log_download_db(self, image_id: str, url: str, filename: str,
                         file_size: int, metadata: Optional[Dict] = None,
                         status: str = 'success', error: Optional[str] = None,
                         folder_path: Optional[str] = None):
        """Log download to database"""
        with self.db_lock:
            cursor = self.db_conn.cursor()

            # Convert width/height to integers, handling string values from API
            width = None
            height = None
            nsfw_level = None
            if metadata:
                try:
                    width = int(metadata.get('width')) if metadata.get('width') else None
                except (ValueError, TypeError):
                    self.logger.warning(f"Invalid width value from API: {repr(metadata.get('width'))}")
                    width = None
                try:
                    height = int(metadata.get('height')) if metadata.get('height') else None
                except (ValueError, TypeError):
                    self.logger.warning(f"Invalid height value from API: {repr(metadata.get('height'))}")
                    height = None

                # Convert NSFW level - try nsfwLevel first, fall back to nsfw string
                nsfw_raw = metadata.get('nsfwLevel') or metadata.get('nsfw')
                if nsfw_raw is not None:
                    nsfw_level = self._convert_nsfw_to_level(nsfw_raw)

            # Extract reaction total if available
            reaction_total = 0
            if metadata:
                stats = metadata.get('stats', {})
                if stats:
                    reaction_total = (
                        stats.get('likeCount', 0) +
                        stats.get('heartCount', 0) +
                        stats.get('commentCount', 0)
                    )

            file_ext = Path(filename).suffix.lstrip('.')

            cursor.execute('''
                INSERT OR REPLACE INTO downloads
                (image_id, url, filename, file_extension, file_size, width, height,
                 nsfw_level, download_timestamp, status, error_message, folder_path, reaction_total)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (str(image_id), url, filename, file_ext, file_size, width, height,
                  nsfw_level, datetime.now().isoformat(), status, error, folder_path, reaction_total))

            if metadata and status == 'success':
                cursor.execute('''
                    INSERT OR REPLACE INTO metadata (image_id, json_data)
                    VALUES (?, ?)
                ''', (str(image_id), json.dumps(metadata)))

            self.db_conn.commit()

        # Store enhanced metadata if available
        if metadata and status == 'success':
            # Store generation parameters
            meta = metadata.get('meta', {})
            if meta:
                self.logger.debug(f"Storing generation params for {image_id}: {list(meta.keys())}")
                self._store_generation_params(str(image_id), meta)
            else:
                self.logger.warning(f"No 'meta' field in metadata for image {image_id}. Available keys: {list(metadata.keys())}")

            # Store tags
            tags = metadata.get('tags', [])
            if tags:
                self.logger.debug(f"Storing {len(tags)} tags for {image_id}")
                self._store_tags(str(image_id), tags)
            else:
                self.logger.debug(f"No tags in metadata for {image_id}")

    def get_download_stats(self) -> Dict:
        """Get comprehensive statistics from database"""
        with self.db_lock:
            cursor = self.db_conn.cursor()

            stats = {}
            cursor.execute('SELECT status, COUNT(*) FROM downloads GROUP BY status')
            stats['by_status'] = dict(cursor.fetchall())

            cursor.execute('SELECT SUM(file_size) FROM downloads WHERE status = "success"')
            stats['total_bytes'] = cursor.fetchone()[0] or 0

            cursor.execute('''
                SELECT AVG(width), AVG(height)
                FROM downloads WHERE status = "success" AND width IS NOT NULL
            ''')
            stats['avg_resolution'] = cursor.fetchone()

            cursor.execute('''
                SELECT file_extension, COUNT(*)
                FROM downloads WHERE status = "success" GROUP BY file_extension
            ''')
            stats['by_type'] = dict(cursor.fetchall())

            return stats

    def search_by_tags(self, include_tags: List[str] = None,
                       exclude_tags: List[str] = None,
                       match_all: bool = False) -> List[Dict]:
        """Search images by tags with include/exclude logic"""
        with self.db_lock:
            cursor = self.db_conn.cursor()

            # Build base query with exclusions in SQL (fix N+1 query issue)
            params = []

            if match_all and include_tags:
                # Find images that have ALL specified tags
                placeholders = ','.join('?' * len(include_tags))
                query = f'''
                    SELECT d.*, COUNT(DISTINCT it.tag_id) as match_count
                    FROM downloads d
                    JOIN image_tags it ON d.image_id = it.image_id
                    JOIN tags t ON it.tag_id = t.tag_id
                    WHERE t.tag_name IN ({placeholders})
                '''
                params.extend(include_tags)

                # Add exclusion filter in SQL
                if exclude_tags:
                    exclude_placeholders = ','.join('?' * len(exclude_tags))
                    query += f'''
                        AND d.image_id NOT IN (
                            SELECT it2.image_id FROM image_tags it2
                            JOIN tags t2 ON it2.tag_id = t2.tag_id
                            WHERE t2.tag_name IN ({exclude_placeholders})
                        )
                    '''
                    params.extend(exclude_tags)

                query += '''
                    GROUP BY d.image_id
                    HAVING match_count = ?
                '''
                params.append(len(include_tags))
                cursor.execute(query, params)

            elif include_tags:
                # Find images that have ANY specified tag
                placeholders = ','.join('?' * len(include_tags))
                query = f'''
                    SELECT DISTINCT d.*
                    FROM downloads d
                    JOIN image_tags it ON d.image_id = it.image_id
                    JOIN tags t ON it.tag_id = t.tag_id
                    WHERE t.tag_name IN ({placeholders})
                '''
                params.extend(include_tags)

                # Add exclusion filter in SQL
                if exclude_tags:
                    exclude_placeholders = ','.join('?' * len(exclude_tags))
                    query += f'''
                        AND d.image_id NOT IN (
                            SELECT it2.image_id FROM image_tags it2
                            JOIN tags t2 ON it2.tag_id = t2.tag_id
                            WHERE t2.tag_name IN ({exclude_placeholders})
                        )
                    '''
                    params.extend(exclude_tags)

                cursor.execute(query, params)
            else:
                # No include tags - just fetch all
                query = 'SELECT * FROM downloads WHERE status = "success"'

                # Add exclusion filter in SQL
                if exclude_tags:
                    exclude_placeholders = ','.join('?' * len(exclude_tags))
                    query += f'''
                        AND image_id NOT IN (
                            SELECT it.image_id FROM image_tags it
                            JOIN tags t ON it.tag_id = t.tag_id
                            WHERE t.tag_name IN ({exclude_placeholders})
                        )
                    '''
                    params.extend(exclude_tags)

                cursor.execute(query, params)

            results = cursor.fetchall()
            return results

    def search_by_model(self, model_name: str = None,
                        sampler_name: str = None) -> List[Dict]:
        """Search images by AI model or sampler"""
        with self.db_lock:
            cursor = self.db_conn.cursor()

            conditions = []
            params = []

            if model_name:
                conditions.append('gp.model_name LIKE ?')
                params.append(f'%{model_name}%')

            if sampler_name:
                conditions.append('gp.sampler_name LIKE ?')
                params.append(f'%{sampler_name}%')

            where_clause = ' AND '.join(conditions) if conditions else '1=1'

            query = f'''
                SELECT d.*, gp.*
                FROM downloads d
                JOIN generation_params gp ON d.image_id = gp.image_id
                WHERE {where_clause}
            '''

            cursor.execute(query, params)
            return cursor.fetchall()

    def search_by_prompt(self, prompt_text: str) -> List[Dict]:
        """Full-text search in prompts"""
        with self.db_lock:
            cursor = self.db_conn.cursor()

            query = '''
                SELECT d.*, gp.prompt, gp.negative_prompt
                FROM downloads d
                JOIN generation_params gp ON d.image_id = gp.image_id
                WHERE gp.prompt LIKE ? OR gp.negative_prompt LIKE ?
            '''

            search_term = f'%{prompt_text}%'
            cursor.execute(query, (search_term, search_term))
            return cursor.fetchall()

    def filter_by_aspect_ratio(self, aspect_ratio: str, limit: int = 10000) -> List[Dict]:
        """Filter by aspect ratio (portrait, landscape, square, or specific ratio like 16:9)

        Phase 5: Added LIMIT parameter to prevent loading entire table into memory
        """
        with self.db_lock:
            cursor = self.db_conn.cursor()

            if aspect_ratio == "portrait":
                query = f'SELECT * FROM downloads WHERE height > width LIMIT {limit}'
            elif aspect_ratio == "landscape":
                query = f'SELECT * FROM downloads WHERE width > height LIMIT {limit}'
            elif aspect_ratio == "square":
                query = f'SELECT * FROM downloads WHERE abs(width - height) < 50 LIMIT {limit}'
            else:
                # Specific ratio like "16:9"
                parts = aspect_ratio.split(':')
                if len(parts) == 2:
                    try:
                        w_ratio, h_ratio = float(parts[0]), float(parts[1])
                        query = f'''
                            SELECT * FROM downloads
                            WHERE abs((width * 1.0 / height) - ?) < 0.1
                            LIMIT {limit}
                        '''
                        cursor.execute(query, (w_ratio / h_ratio,))
                        return cursor.fetchall()
                    except ValueError:
                        return []
                return []

            cursor.execute(query)
            return cursor.fetchall()

    def filter_by_date_range(self, start_date: str = None,
                             end_date: str = None) -> List[Dict]:
        """Filter downloads by date range (YYYY-MM-DD format)"""
        with self.db_lock:
            cursor = self.db_conn.cursor()

            conditions = []
            params = []

            if start_date:
                conditions.append('download_timestamp >= ?')
                params.append(start_date)

            if end_date:
                conditions.append('download_timestamp <= ?')
                params.append(end_date)

            where_clause = ' AND '.join(conditions) if conditions else '1=1'

            query = f'SELECT * FROM downloads WHERE {where_clause}'
            cursor.execute(query, params)
            return cursor.fetchall()

    def get_all_tags(self, min_count: int = 1) -> List[Tuple[str, int]]:
        """Get all tags with usage counts"""
        with self.db_lock:
            cursor = self.db_conn.cursor()

            query = '''
                SELECT t.tag_name, COUNT(it.image_id) as count
                FROM tags t
                LEFT JOIN image_tags it ON t.tag_id = it.tag_id
                GROUP BY t.tag_id, t.tag_name
                HAVING count >= ?
                ORDER BY count DESC
            '''

            cursor.execute(query, (min_count,))
            return cursor.fetchall()

    def get_all_models(self) -> List[Tuple[str, int]]:
        """Get all models with usage counts"""
        with self.db_lock:
            cursor = self.db_conn.cursor()

            query = '''
                SELECT model_name, COUNT(*) as count
                FROM generation_params
                WHERE model_name IS NOT NULL AND model_name != ''
                GROUP BY model_name
                ORDER BY count DESC
            '''

            cursor.execute(query)
            return cursor.fetchall()

    def _load_download_log(self) -> set:
        """
        Load previously downloaded image IDs from log file

        Returns:
            Set of image IDs that have been downloaded before
        """
        downloaded_ids = set()
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            downloaded_ids.add(line)
            except Exception as e:
                self.logger.warning(f"Could not load download log: {e}")
        return downloaded_ids

    def _log_download(self, image_id: str):
        """
        Log a downloaded image ID to the log file

        Args:
            image_id: Image ID to log
        """
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f"{image_id}\n")
            self.downloaded_ids.add(str(image_id))
        except Exception as e:
            self.logger.warning(f"Could not write to download log: {e}")

    def check_pause(self):
        """Check for 'p' keypress to toggle pause"""
        if msvcrt.kbhit():
            key = msvcrt.getch()
            if key.lower() == b'p':
                self.paused = not self.paused
                if self.paused:
                    print("\n\n=== PAUSED === Press 'p' to resume...")
                else:
                    print("\n=== RESUMED ===")
        
        while self.paused and self.running:
            time.sleep(0.1)
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key.lower() == b'p':
                    self.paused = False
                    print("\n=== RESUMED ===")

    def build_query_params(self,
                          limit: int = 100,
                          sort: str = "Most Reactions",
                          period: str = "AllTime",
                          nsfw: Optional[str] = None,
                          username: Optional[str] = None,
                          modelId: Optional[int] = None,
                          postId: Optional[int] = None,
                          cursor: Optional[str] = None) -> Dict:
        """
        Build query parameters for API request

        Args:
            limit: Number of images per page (max 200)
            sort: Sorting option (Most Reactions, Most Comments, Newest)
            period: Time period (AllTime, Year, Month, Week, Day)
            nsfw: NSFW filter (None, Soft, Mature, X)
            username: Filter by username
            modelId: Filter by model ID
            postId: Filter by post ID
            cursor: Pagination cursor

        Returns:
            Dictionary of query parameters
        """
        params = {
            "limit": min(limit, 200),  # API max is 200
            "sort": sort,
            "period": period
        }

        if nsfw:
            params["nsfw"] = nsfw
        if username:
            params["username"] = username
        if modelId:
            params["modelId"] = modelId
        if postId:
            params["postId"] = postId
        if cursor:
            params["cursor"] = cursor

        return params

    def fetch_images(self, params: Dict) -> Optional[Dict]:
        """
        Fetch images from Civitai API

        Args:
            params: Query parameters

        Returns:
            JSON response or None if failed
        """
        try:
            response = self.session.get(self.base_url, params=params, timeout=30)

            # Check rate limit headers if available
            if 'X-RateLimit-Remaining' in response.headers:
                remaining = response.headers['X-RateLimit-Remaining']
                if int(remaining) < 10:
                    self.logger.warning(f"API rate limit low: {remaining} requests remaining")

            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching images: {e}")
            return None

    def _fetch_image_tags(self, image_id: str) -> List[Dict]:
        """Fetch tags using Civitai tRPC API (gallery-dl pattern)"""
        import time

        url = "https://civitai.com/api/trpc/tag.getVotableTags"

        # Build tRPC request
        input_data = {"json": {"id": int(image_id), "type": "image"}}
        params = {"input": json.dumps(input_data)}

        # tRPC headers
        headers = {
            "content-type": "application/json",
            "x-client-version": "5.0.954",
            "x-client-date": str(int(time.time() * 1000)),
            "x-client": "web",
            "x-fingerprint": "undefined"
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self.session.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            # tRPC format: {"result": {"data": {"json": [...]}}}
            tags = data.get("result", {}).get("data", {}).get("json", [])
            return tags

        except requests.RequestException as e:
            self.logger.debug(f"Tag fetch failed for {image_id}: {e}")
            return []

    def update_tags_for_image(self, image_id: str) -> bool:
        """Fetch and store tags for one image"""
        try:
            tag_data = self._fetch_image_tags(image_id)

            if tag_data:
                tag_names = [tag.get('name') for tag in tag_data if tag.get('name')]

                if tag_names:
                    self._store_tags(image_id, tag_names)

            # Mark as fetched (even if empty)
            with self.db_lock:
                cursor = self.db_conn.cursor()
                cursor.execute(
                    'UPDATE downloads SET tags_fetched = 1 WHERE image_id = ?',
                    (str(image_id),)
                )
                self.db_conn.commit()

            return True

        except Exception as e:
            self.logger.error(f"Tag update error for {image_id}: {e}")
            return False

    def batch_fetch_missing_tags(self, max_images: int = 100, delay: float = 1.0) -> Dict:
        """Fetch tags for images without them

        Returns:
            {processed, success, failed, total_tags}
        """
        # Find images without tags
        with self.db_lock:
            cursor = self.db_conn.cursor()
            cursor.execute('''
                SELECT image_id FROM downloads
                WHERE (tags_fetched IS NULL OR tags_fetched = 0)
                AND status = 'success'
                LIMIT ?
            ''', (max_images,))
            image_ids = [row[0] for row in cursor.fetchall()]

        if not image_ids:
            self.logger.info("No images need tag fetching")
            return {'processed': 0, 'success': 0, 'failed': 0, 'total_tags': 0}

        self.logger.info(f"Fetching tags for {len(image_ids)} images...")

        stats = {'processed': 0, 'success': 0, 'failed': 0}

        for i, image_id in enumerate(image_ids, 1):
            if not self.running:
                self.logger.info("Tag fetching interrupted")
                break

            success = self.update_tags_for_image(image_id)
            stats['processed'] += 1

            if success:
                stats['success'] += 1
            else:
                stats['failed'] += 1

            # Progress logging
            if i % 10 == 0:
                self.logger.info(f"Tag progress: {i}/{len(image_ids)}")

            # Rate limiting
            if i < len(image_ids):
                time.sleep(delay)

        # Count total tags
        with self.db_lock:
            cursor = self.db_conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM tags')
            stats['total_tags'] = cursor.fetchone()[0]

        self.logger.info(f"Tag fetching complete: {stats}")
        return stats

    def batch_fetch_missing_metadata(self, max_images: int = 100, delay: float = 1.0) -> Dict:
        """Fetch metadata from Civitai API for images missing generation params

        This is useful for images downloaded with Model ID filter where the API
        doesn't return the 'meta' field.

        Returns:
            {processed, success, failed, not_found, already_null, total_with_metadata}
        """
        # Find images without generation params but CHECK if meta is already null
        with self.db_lock:
            cursor = self.db_conn.cursor()
            cursor.execute('''
                SELECT d.image_id, m.json_data FROM downloads d
                LEFT JOIN generation_params gp ON d.image_id = gp.image_id
                LEFT JOIN metadata m ON d.image_id = m.image_id
                WHERE d.status = 'success'
                AND gp.image_id IS NULL
                LIMIT ?
            ''', (max_images,))
            results = cursor.fetchall()

        # Filter out images that already have meta: null
        image_ids = []
        already_null_count = 0

        for image_id, json_data in results:
            if json_data:
                try:
                    metadata = json.loads(json_data)
                    if metadata.get('meta') is None:
                        # Already checked and has no metadata
                        already_null_count += 1
                        continue
                except json.JSONDecodeError as e:
                    self.logger.debug(f"Invalid JSON for {image_id}: {e}")
            image_ids.append(image_id)

        if not image_ids:
            msg = "No images need metadata fetching"
            if already_null_count > 0:
                msg += f" ({already_null_count} images confirmed to have no metadata)"
            self.logger.info(msg)
            return {
                'processed': 0,
                'success': 0,
                'failed': 0,
                'not_found': 0,
                'already_null': already_null_count,
                'total_with_metadata': 0
            }

        self.logger.info(f"Fetching metadata for {len(image_ids)} images from Civitai API...")
        if already_null_count > 0:
            self.logger.info(f"Skipped {already_null_count} images already confirmed to have no metadata")

        stats = {'processed': 0, 'success': 0, 'failed': 0, 'not_found': 0, 'already_null': already_null_count}

        for i, image_id in enumerate(image_ids, 1):
            if not self.running:
                self.logger.info("Metadata fetching interrupted")
                break

            try:
                # Fetch from Civitai API
                url = f"https://civitai.com/api/v1/images/{image_id}"
                response = self.session.get(url, timeout=10)
                response.raise_for_status()

                data = response.json()
                meta = data.get('meta', {})

                if meta:
                    # Store generation parameters
                    self._store_generation_params(str(image_id), meta)
                    stats['success'] += 1
                    self.logger.debug(f"Fetched metadata for image {image_id}")
                else:
                    self.logger.debug(f"No meta field for image {image_id}")
                    stats['failed'] += 1

            except requests.HTTPError as e:
                # 404 means image was deleted or is private - this is expected
                if e.response.status_code == 404:
                    self.logger.debug(f"Image {image_id} not found (404 - deleted or private)")
                    stats['not_found'] += 1
                else:
                    self.logger.warning(f"HTTP error for image {image_id}: {e.response.status_code}")
                    stats['failed'] += 1
            except Exception as e:
                self.logger.warning(f"Failed to fetch metadata for {image_id}: {e}")
                stats['failed'] += 1

            stats['processed'] += 1

            # Progress logging
            if i % 10 == 0:
                self.logger.info(f"Metadata progress: {i}/{len(image_ids)}")

            # Rate limiting
            if i < len(image_ids):
                time.sleep(delay)

        # Count total images with metadata
        with self.db_lock:
            cursor = self.db_conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM generation_params')
            stats['total_with_metadata'] = cursor.fetchone()[0]

        msg_parts = [
            f"Success={stats['success']}",
            f"Not Found (404)={stats['not_found']}",
            f"Failed={stats['failed']}"
        ]
        if stats['already_null'] > 0:
            msg_parts.append(f"Skipped (no metadata)={stats['already_null']}")

        self.logger.info(f"Metadata fetching complete: {', '.join(msg_parts)}")
        return stats

    def _detect_image_format(self, data: bytes) -> tuple[str, bool]:
        """
        Detect image/video format from file signature (magic bytes)

        Args:
            data: First few bytes of the file

        Returns:
            Tuple of (file extension, is_video)
        """
        # Video formats
        if data[4:12] == b'ftypmp42' or data[4:12] == b'ftypisom':
            return '.mp4', True
        elif data[:4] == b'\x1a\x45\xdf\xa3':
            return '.webm', True
        elif data[:3] == b'FLV':
            return '.flv', True

        # Image formats
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return '.png', False
        elif data.startswith(b'\xff\xd8\xff'):
            return '.jpg', False
        elif data.startswith(b'RIFF') and b'WEBP' in data[:12]:
            return '.webp', False
        elif data.startswith(b'GIF87a') or data.startswith(b'GIF89a'):
            return '.gif', False
        else:
            return '.jpg', False  # Default fallback

    def download_image(self, url: str, filename: str, metadata: Dict = None, image_id: str = None) -> Tuple[bool, str]:
        """
        Download a single image

        Args:
            url: Image URL
            filename: Output filename
            metadata: Image metadata to save alongside
            image_id: Image ID for logging

        Returns:
            Tuple of (success: bool, status: str)
        """
        # Check if already downloaded (from database or log)
        if image_id:
            if self.use_database:
                if self._is_downloaded_db(image_id):
                    with self.stats_lock:
                        self.skipped_count += 1
                    return True, "skipped (in database)"
            else:
                if str(image_id) in self.downloaded_ids:
                    with self.stats_lock:
                        self.skipped_count += 1
                    return True, "skipped (in log)"

        # DRY RUN MODE
        if self.dry_run:
            self.logger.info(f"[DRY RUN] Would download: {url} -> {filename}")

            if metadata:
                width = metadata.get('width', '?')
                height = metadata.get('height', '?')
                nsfw = metadata.get('nsfwLevel', '?')
                self.logger.info(f"  Size: {width}x{height}, NSFW: {nsfw}")

            with self.stats_lock:
                self.downloaded_count += 1

            return True, "simulated"

        # We'll determine the actual extension after downloading
        temp_filepath = self.output_dir / f"temp_{filename}"

        try:
            # Reuse main session for better performance (connection pooling)
            response = self.session.get(url, timeout=30, stream=True)
            response.raise_for_status()

            # Download to temporary file and detect format
            first_chunk = None
            with open(temp_filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if first_chunk is None:
                        first_chunk = chunk
                    f.write(chunk)

            # Detect actual format from file content
            if first_chunk:
                actual_extension, is_video = self._detect_image_format(first_chunk)

                # Check if this file type is allowed
                if self.allowed_types is not None:
                    # Remove the leading dot from extension for comparison
                    ext_without_dot = actual_extension.lstrip('.')
                    if ext_without_dot not in self.allowed_types:
                        os.remove(temp_filepath)
                        with self.stats_lock:
                            self.filtered_type_count += 1
                        return True, f"skipped (type: {ext_without_dot})"

                # Update filename with correct extension
                base_name = os.path.splitext(filename)[0]
                correct_filename = f"{base_name}{actual_extension}"

                # Determine output directory based on organization mode
                folder_path = None
                if self.organize_by_nsfw:
                    # Phase 2.1: Changed debug messages from info to debug level
                    self.logger.debug(f"[NSFW] Image ID: {image_id}")
                    self.logger.debug(f"[NSFW] Metadata present: {metadata is not None}")
                    if metadata:
                        self.logger.debug(f"[NSFW] Metadata keys: {list(metadata.keys())}")
                        self.logger.debug(f"[NSFW] nsfwLevel value: {metadata.get('nsfwLevel')!r}")
                        self.logger.debug(f"[NSFW] nsfw value: {metadata.get('nsfw')!r}")

                    # Get NSFW level from metadata (try nsfwLevel first, fall back to nsfw string)
                    nsfw_raw = metadata.get('nsfwLevel') or metadata.get('nsfw') if metadata else None
                    self.logger.debug(f"[NSFW] Raw value selected: {nsfw_raw!r} (type: {type(nsfw_raw).__name__})")

                    nsfw_folder = self._get_nsfw_folder(nsfw_raw)
                    self.logger.debug(f"[NSFW] Folder determined: {nsfw_folder}")

                    if is_video:
                        filepath = self.videos_dir / nsfw_folder / correct_filename
                        # Ensure video category folder exists
                        (self.videos_dir / nsfw_folder).mkdir(parents=True, exist_ok=True)
                    else:
                        filepath = self.output_dir / nsfw_folder / correct_filename

                    self.logger.debug(f"[NSFW] Final filepath: {filepath}")

                    # Store metadata in category-specific subfolder
                    meta_dir = self.output_dir / nsfw_folder / "metadata"
                    meta_dir.mkdir(parents=True, exist_ok=True)
                    meta_path = meta_dir / f"{base_name}.json"

                    # Store relative folder path for database
                    folder_path = str(filepath.parent.relative_to(self.output_dir))
                else:
                    # Original logic (unchanged)
                    if is_video:
                        filepath = self.videos_dir / correct_filename
                    else:
                        filepath = self.output_dir / correct_filename
                    meta_path = self.metadata_dir / f"{base_name}.json"

                # Skip if already exists with correct name
                if filepath.exists():
                    os.remove(temp_filepath)
                    # Still log it if not already in log/database
                    if image_id:
                        if self.use_database:
                            if not self._is_downloaded_db(image_id):
                                file_size = filepath.stat().st_size
                                self._log_download_db(image_id, url, str(filepath), file_size, metadata, folder_path=folder_path)
                        else:
                            if str(image_id) not in self.downloaded_ids:
                                self._log_download(image_id)
                    with self.stats_lock:
                        self.skipped_count += 1
                    return True, "skipped (exists)"

                # Rename temp file to correct name
                os.rename(temp_filepath, filepath)

                # Save metadata if provided
                if metadata:
                    with open(meta_path, 'w', encoding='utf-8') as f:
                        json.dump(metadata, f, indent=2, ensure_ascii=False)

                # Get file size for stats
                file_size = filepath.stat().st_size

                # Log the download (database or text log)
                if image_id:
                    if self.use_database:
                        self._log_download_db(image_id, url, str(filepath), file_size, metadata, folder_path=folder_path)
                    else:
                        self._log_download(image_id)

                with self.stats_lock:
                    self.downloaded_count += 1
                    self.stats.add_download(file_size)

                return True, "downloaded"
            else:
                os.remove(temp_filepath)
                with self.stats_lock:
                    self.failed_count += 1
                return False, "error: empty file"

        except Exception as e:
            # Clean up temp file if it exists
            if temp_filepath.exists():
                try:
                    os.remove(temp_filepath)
                except OSError as e:
                    self.logger.debug(f"Failed to remove temp file: {e}")

            with self.stats_lock:
                self.failed_count += 1
            return False, f"error: {e}"

    def _download_with_retry(self, url: str, filename: str, metadata: Dict = None,
                            image_id: str = None, max_retries: int = 3,
                            backoff_factor: float = 2.0) -> Tuple[bool, str]:
        """Download with retry logic and exponential backoff"""
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                success, status = self.download_image(url, filename, metadata, image_id)

                if success or status.startswith("skipped"):
                    return success, status

                last_error = status

                if attempt < max_retries:
                    wait_time = backoff_factor ** (attempt - 1)
                    self.logger.warning(
                        f"Download failed (attempt {attempt}/{max_retries}): {filename}. "
                        f"Retrying in {wait_time:.1f}s... Error: {status}"
                    )
                    time.sleep(wait_time)

            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    wait_time = backoff_factor ** (attempt - 1)
                    self.logger.warning(
                        f"Exception (attempt {attempt}/{max_retries}): {filename}. "
                        f"Retrying in {wait_time:.1f}s..."
                    )
                    time.sleep(wait_time)

        self.logger.error(
            f"Failed after {max_retries} attempts: {filename}. Last error: {last_error}"
        )
        return False, f"failed after {max_retries} retries: {last_error}"

    def _download_batch(self, items: List[Dict], save_metadata: bool, progress_bar=None) -> int:
        """
        Download a batch of images concurrently

        Args:
            items: List of image items from API
            save_metadata: Whether to save metadata
            progress_bar: Optional tqdm progress bar

        Returns:
            Number of successfully downloaded images
        """
        download_tasks = []

        for item in items:
            image_id = item.get('id')
            image_url = item.get('url')

            if not image_url:
                continue

            # Generate base filename (extension will be detected from actual content)
            filename = f"civitai_{image_id}.tmp"

            # Prepare metadata
            metadata = None
            if save_metadata:
                metadata = {
                    'id': image_id,
                    'url': image_url,
                    'width': item.get('width'),
                    'height': item.get('height'),
                    'hash': item.get('hash'),
                    'nsfw': item.get('nsfw'),
                    'nsfwLevel': item.get('nsfwLevel'),
                    'createdAt': item.get('createdAt'),
                    'postId': item.get('postId'),
                    'username': item.get('username'),
                    'stats': item.get('stats'),
                    'meta': item.get('meta'),
                    'tags': item.get('tags', [])
                }

            download_tasks.append((image_url, filename, metadata, image_id))

        # Download concurrently
        successful = 0
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            # Use retry logic if enabled
            if self.enable_retry:
                futures = {
                    executor.submit(self._download_with_retry, url, fname, meta, img_id, self.max_retries): fname
                    for url, fname, meta, img_id in download_tasks
                }
            else:
                futures = {
                    executor.submit(self.download_image, url, fname, meta, img_id): fname
                    for url, fname, meta, img_id in download_tasks
                }

            for future in as_completed(futures):
                self.check_pause()
                if not self.running:
                    break

                filename = futures[future]
                try:
                    success, status = future.result()

                    # Update progress bar if provided
                    if progress_bar:
                        progress_bar.update(1)
                        progress_bar.set_postfix({
                            'DL': self.downloaded_count,
                            'Skip': self.skipped_count,
                            'Fail': self.failed_count,
                            'Speed': self.stats.format_speed()
                        })
                    else:
                        # Keep existing print statements for non-progress mode
                        if success:
                            if status == "downloaded":
                                self.logger.info(f"✓ Downloaded: {filename}")
                                successful += 1
                            elif status.startswith("skipped"):
                                self.logger.info(f"○ Skipped: {filename}")
                        else:
                            self.logger.error(f"✗ Failed: {filename} - {status}")

                except Exception as e:
                    self.logger.error(f"✗ Exception downloading {filename}: {e}")
                    with self.stats_lock:
                        self.failed_count += 1

        return successful

    def scrape(self,
              max_images: Optional[int] = 100,
              sort: str = "Most Reactions",
              period: str = "AllTime",
              nsfw: Optional[str] = None,
              username: Optional[str] = None,
              modelId: Optional[int] = None,
              save_metadata: bool = True,
              delay: float = 0.5,
              endless: bool = False,
              nsfw_only: bool = False,
              min_resolution: Optional[int] = None,
              min_reactions: Optional[int] = None,
              show_progress: bool = True):
        """
        Scrape images from Civitai

        Args:
            max_images: Maximum number of images to download (None for endless)
            sort: Sorting option
            period: Time period filter
            nsfw: NSFW filter
            username: Filter by username
            modelId: Filter by model ID
            save_metadata: Save image metadata as JSON
            delay: Delay between API requests (seconds)
            endless: Download until no more images or interrupted
            nsfw_only: Only download Mature and X rated content
            min_resolution: Minimum resolution on the longer side (width or height)
            min_reactions: Minimum total positive reactions (likes + hearts + laughs + cries)
            show_progress: Show tqdm progress bars
        """
        cursor = None
        page = 1

        mode_str = "ENDLESS MODE" if endless else f"{max_images} images"

        # Dry run banner
        if self.dry_run:
            print("\n" + "=" * 60)
            print("DRY RUN MODE - No files will be downloaded")
            print("=" * 60 + "\n")

        print("=" * 60)
        print(f"Civitai Image Scraper - {mode_str}")
        print("=" * 60)
        print(f"Sort: {sort}")
        print(f"Period: {period}")
        print(f"NSFW: {nsfw or 'All'}")
        if nsfw_only:
            print(f"NSFW-only: Yes (X/XXX only)")
        if min_resolution:
            print(f"Min Resolution: {min_resolution}px (longer side)")
        if self.allowed_types:
            print(f"Allowed file types: {', '.join(self.allowed_types)}")
        print(f"Workers: {self.workers}")
        print(f"Output: {self.output_dir}")
        if endless:
            print("\nPress Ctrl+C to stop downloading")
        print("\nPress 'p' to pause/resume")
        print("=" * 60)
        print()

        # Setup progress bar if enabled
        progress_bar = None
        if show_progress:
            try:
                from tqdm import tqdm
                if not endless and max_images:
                    progress_bar = tqdm(
                        total=max_images,
                        desc="Downloading",
                        unit='img',
                        ncols=100,
                        bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'
                    )
                else:
                    progress_bar = tqdm(
                        desc="Downloading (endless)",
                        unit='img',
                        ncols=100
                    )
            except ImportError:
                self.logger.warning("tqdm not installed. Progress bars disabled. Install with: pip install tqdm")
                progress_bar = None

        try:
            while self.running:
                self.check_pause()
                # Check if we've reached the limit (if not endless)
                if not endless and max_images and self.downloaded_count >= max_images:
                    break

                # Calculate how many to fetch this page
                if endless:
                    limit = 200  # Max per request
                else:
                    remaining = max_images - self.downloaded_count
                    limit = min(remaining, 200)

                params = self.build_query_params(
                    limit=limit,
                    sort=sort,
                    period=period,
                    nsfw=nsfw,
                    username=username,
                    modelId=modelId,
                    cursor=cursor
                )

                if not progress_bar:
                    self.logger.info(f"[Page {page}] Fetching metadata from API...")
                data = self.fetch_images(params)

                if not data or 'items' not in data:
                    self.logger.info("No more images found or error occurred")
                    break

                items = data['items']
                if not items:
                    self.logger.info("No images in response")
                    break

                # Filter for NSFW-only if requested
                if nsfw_only:
                    original_count = len(items)
                    # Filter for X and XXX content (nsfwLevel: 5=X, 6=XXX or nsfw: 'X', 'XXX')
                    items = [item for item in items
                            if item.get('nsfwLevel') in [5, 6] or
                            item.get('nsfw') in ['X', 'XXX']]
                    filtered_count = original_count - len(items)
                    if filtered_count > 0:
                        self.logger.info(f"[Page {page}] Filtered out {filtered_count} non-adult images")

                # Filter by minimum resolution if specified
                if min_resolution:
                    original_count = len(items)
                    filtered_items = []
                    for item in items:
                        # Convert to int in case API returns strings
                        try:
                            width = int(item.get('width', 0)) if item.get('width') else 0
                            height = int(item.get('height', 0)) if item.get('height') else 0
                            longer_side = max(width, height)
                            if longer_side >= min_resolution:
                                filtered_items.append(item)
                        except (ValueError, TypeError) as e:
                            self.logger.error(f"Resolution filtering error for image {item.get('id')}: width={repr(item.get('width'))}, height={repr(item.get('height'))}, min_resolution={repr(min_resolution)}, error={e}")
                            # Skip this image if resolution data is invalid
                            continue
                    items = filtered_items
                    filtered_count = original_count - len(items)
                    if filtered_count > 0:
                        self.logger.info(f"[Page {page}] Filtered out {filtered_count} images below {min_resolution}px")

                # Filter by minimum reactions if specified
                if min_reactions:
                    original_count = len(items)
                    filtered_items = []

                    for item in items:
                        stats = item.get('stats', {})
                        if stats:
                            total_reactions = (
                                stats.get('likeCount', 0) +
                                stats.get('heartCount', 0) +
                                stats.get('laughCount', 0) +
                                stats.get('cryCount', 0)
                            )
                            if total_reactions >= min_reactions:
                                filtered_items.append(item)

                    items = filtered_items
                    filtered_count = original_count - len(items)

                    if filtered_count > 0:
                        self.logger.info(
                            f"[Page {page}] Filtered out {filtered_count} images below {min_reactions} reactions"
                        )

                if not items:
                    self.logger.info(f"[Page {page}] No images left after filtering")
                    page += 1
                    continue

                if not progress_bar:
                    self.logger.info(f"[Page {page}] Found {len(items)} images, starting downloads...")

                # Download this batch concurrently
                batch_downloaded = self._download_batch(items, save_metadata, progress_bar)

                # Print stats (only if no progress bar)
                if not progress_bar:
                    print(f"\n[Page {page}] Batch complete:")
                    print(f"  Downloaded: {self.downloaded_count}")
                    print(f"  Skipped: {self.skipped_count}")
                    if self.filtered_type_count > 0:
                        print(f"  Filtered (file type): {self.filtered_type_count}")
                    print(f"  Failed: {self.failed_count}")
                    print(f"  Total processed: {self.downloaded_count + self.skipped_count + self.failed_count + self.filtered_type_count}")

                # Get next page cursor
                metadata_obj = data.get('metadata', {})
                cursor = metadata_obj.get('nextCursor')

                if not cursor:
                    if not progress_bar:
                        print("\nNo more pages available")
                    break

                page += 1

                # Only delay between API requests (not downloads)
                if self.running:
                    time.sleep(delay)

        except KeyboardInterrupt:
            print("\n\nDownload interrupted by user")
        finally:
            # Close progress bar
            if progress_bar:
                progress_bar.close()

            # Dry run completion banner
            if self.dry_run:
                print("\n" + "=" * 60)
                print("DRY RUN COMPLETE - No files were downloaded")
                print("=" * 60)

            # Calculate elapsed time
            elapsed_time = time.time() - self.stats.start_time

            print("\n" + "=" * 60)
            print("FINAL STATISTICS")
            print("=" * 60)
            print(f"Successfully downloaded: {self.downloaded_count:,}")
            print(f"Skipped (already exist): {self.skipped_count:,}")
            if self.filtered_type_count > 0:
                print(f"Filtered by file type:   {self.filtered_type_count:,}")
            print(f"Failed:                  {self.failed_count:,}")
            print(f"Total images processed:  {self.downloaded_count + self.skipped_count + self.failed_count + self.filtered_type_count:,}")
            print(f"\nTotal download size:     {self.stats.format_size()}")
            print(f"Average speed:           {self.stats.format_speed()}")

            # Format elapsed time
            if elapsed_time < 60:
                elapsed_str = f"{int(elapsed_time)}s"
            elif elapsed_time < 3600:
                minutes = int(elapsed_time // 60)
                seconds = int(elapsed_time % 60)
                elapsed_str = f"{minutes}m {seconds}s"
            else:
                hours = int(elapsed_time // 3600)
                minutes = int((elapsed_time % 3600) // 60)
                elapsed_str = f"{hours}h {minutes}m"

            print(f"Total elapsed time:      {elapsed_str}")
            print(f"\nOutput directory:        {self.output_dir.absolute()}")

            # Database stats if enabled
            if self.use_database:
                try:
                    db_stats = self.get_download_stats()
                    print(f"\nDatabase statistics:")
                    print(f"  Total in database:     {sum(db_stats.get('by_status', {}).values()):,}")
                    if db_stats.get('by_type'):
                        types_str = ', '.join(f"{k}: {v}" for k, v in list(db_stats['by_type'].items())[:5])
                        print(f"  By file type:          {types_str}")
                except Exception as e:
                    self.logger.debug(f"Could not fetch database stats: {e}")
            print("=" * 60)


def generate_config_template(output_path: str = "civitai_config.yaml"):
    """Generate template configuration file"""
    try:
        import yaml
    except ImportError:
        print("Error: pyyaml not installed. Install with: pip install pyyaml")
        return

    template = {
        'output': {'directory': 'downloads', 'save_metadata': True},
        'download': {'workers': 5, 'delay': 0.5, 'allowed_file_types': None},
        'filters': {
            'sort': 'Most Reactions', 'period': 'AllTime',
            'nsfw': None, 'nsfw_only': False,
            'min_resolution': None, 'username': None, 'model_id': None
        },
        'logging': {'level': 'INFO', 'file': None},
        'api': {'key': None, 'base_url': 'https://civitai.com/api/v1/images'},
        'retry': {'enabled': True, 'max_retries': 3}
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(template, f, default_flow_style=False, sort_keys=False)
    print(f"Configuration template created at {output_path}")


def search_command(args):
    """Execute search from command line"""
    scraper = CivitaiScraper(output_dir=args.output, use_database=True)

    results = []

    # List tags or models
    if args.list_tags:
        tags = scraper.get_all_tags(min_count=args.min_count or 1)
        print(f"\nFound {len(tags)} tags:")
        for tag, count in tags[:100]:  # Limit to top 100
            print(f"  {tag}: {count} images")
        return
    elif args.list_models:
        models = scraper.get_all_models()
        print(f"\nFound {len(models)} models:")
        for model, count in models[:50]:  # Limit to top 50
            print(f"  {model}: {count} images")
        return

    # Perform searches
    if args.tags or args.exclude_tags:
        results = scraper.search_by_tags(
            include_tags=args.tags,
            exclude_tags=args.exclude_tags,
            match_all=args.match_all_tags
        )
    elif args.model:
        results = scraper.search_by_model(model_name=args.model)
    elif args.sampler:
        results = scraper.search_by_model(sampler_name=args.sampler)
    elif args.prompt:
        results = scraper.search_by_prompt(args.prompt)
    elif args.aspect_ratio:
        results = scraper.filter_by_aspect_ratio(args.aspect_ratio)
    elif args.date_from or args.date_to:
        results = scraper.filter_by_date_range(args.date_from, args.date_to)
    else:
        print("No search criteria specified. Use --help for search options.")
        print("\nAvailable search options:")
        print("  --search-tags TAG [TAG...]     Search by tags")
        print("  --exclude-tags TAG [TAG...]    Exclude tags")
        print("  --search-model MODEL           Search by model name")
        print("  --search-prompt TEXT           Search in prompts")
        print("  --aspect-ratio RATIO           Filter by aspect ratio")
        print("  --list-tags                    List all tags")
        print("  --list-models                  List all models")
        return

    # Display results
    print(f"\nFound {len(results)} images matching criteria:")
    limit = args.result_limit
    for row in results[:limit]:
        # row[0] = image_id, row[2] = filename, row[5] = width, row[6] = height
        print(f"  {row[2]} - {row[5]}x{row[6]}")

    if len(results) > limit:
        print(f"\n... and {len(results) - limit} more results (use --result-limit to show more)")


def main():
    parser = argparse.ArgumentParser(
        description='Download images from Civitai with filters and sorting (with concurrent downloads)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download 50 most recent images with 10 concurrent workers
  python civitai_scraper.py -n 50 --sort Newest --workers 10

  # Download top images from this month
  python civitai_scraper.py -n 100 --period Month

  # Endless mode - download everything until interrupted
  python civitai_scraper.py --endless --sort Newest

  # Download SFW images only in endless mode
  python civitai_scraper.py --endless --nsfw None --workers 20

  # Download only X/XXX adult images
  python civitai_scraper.py --endless --nsfw-only --workers 20

  # Download only high-resolution images (min 2048px on longer side)
  python civitai_scraper.py --endless --min-resolution 2048 --workers 20

  # Download images from specific user
  python civitai_scraper.py -n 50 --username someuser

  # Download images from specific model with high concurrency
  python civitai_scraper.py --endless --model-id 12345 --workers 15

  # Download only JPG and PNG files (no videos or WebP)
  python civitai_scraper.py -n 100 --file-types jpg png

  # Download only videos (MP4, WebM)
  python civitai_scraper.py --endless --file-types mp4 webm --workers 20

Sort options: "Most Reactions", "Most Comments", "Newest"
Period options: "AllTime", "Year", "Month", "Week", "Day"
NSFW API filter: "None" (PG), "Soft" (PG-13), "Mature" (R), "X" (adult)
NSFW-only mode: Client-side filter for X and XXX rated content
File types: jpg, png, webp, gif, mp4, webm, flv (omit to allow all)
Controls: Press 'p' to pause/resume downloads
        """
    )

    # Config file
    parser.add_argument('--config', type=str,
                       help='Path to configuration file (YAML)')
    parser.add_argument('--generate-config', action='store_true',
                       help='Generate template config file and exit')

    # Search mode
    parser.add_argument('--search', action='store_true',
                       help='Search mode - search downloaded images instead of downloading')
    parser.add_argument('--search-tags', nargs='+', dest='tags', help='Include these tags in search')
    parser.add_argument('--exclude-tags', nargs='+', help='Exclude these tags from search')
    parser.add_argument('--match-all-tags', action='store_true',
                       help='Match all tags (AND logic instead of OR)')
    parser.add_argument('--search-model', dest='model', help='Search by model name')
    parser.add_argument('--search-sampler', dest='sampler', help='Search by sampler name')
    parser.add_argument('--search-prompt', dest='prompt', help='Search in prompts')
    parser.add_argument('--aspect-ratio', help='Filter by aspect ratio (portrait/landscape/square/16:9)')
    parser.add_argument('--date-from', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--date-to', help='End date (YYYY-MM-DD)')
    parser.add_argument('--list-tags', action='store_true', help='List all tags with counts')
    parser.add_argument('--list-models', action='store_true', help='List all models with counts')
    parser.add_argument('--min-tag-count', dest='min_count', type=int, help='Minimum tag count for --list-tags')
    parser.add_argument('--result-limit', type=int, default=50, help='Limit search results (default: 50)')

    # Logging
    parser.add_argument('--log-level', type=str, default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Logging level (default: INFO)')
    parser.add_argument('--log-file', type=str,
                       help='Save detailed logs to file')

    # Download options
    parser.add_argument('-n', '--num-images', type=int, default=None,
                       help='Number of images to download (omit for endless mode)')
    parser.add_argument('-o', '--output', type=str, default='downloads',
                       help='Output directory (default: downloads)')
    parser.add_argument('--sort', type=str, default='Most Reactions',
                       choices=['Most Reactions', 'Most Comments', 'Newest'],
                       help='Sort order (default: Most Reactions)')
    parser.add_argument('--period', type=str, default='AllTime',
                       choices=['AllTime', 'Year', 'Month', 'Week', 'Day'],
                       help='Time period (default: AllTime)')
    parser.add_argument('--nsfw', type=str, choices=['None', 'Soft', 'Mature', 'X'],
                       help='NSFW filter level sent to API (None=PG, Soft=PG-13, Mature=R, X=adult - default: all levels)')
    parser.add_argument('--nsfw-only', action='store_true',
                       help='Download only X and XXX rated adult content (filters out PG, PG-13, R)')
    parser.add_argument('--min-resolution', type=int,
                       help='Minimum resolution on the longer side (e.g., 2048 for images >= 2048px)')
    parser.add_argument('--username', type=str,
                       help='Filter by username')
    parser.add_argument('--model-id', type=int,
                       help='Filter by model ID')
    parser.add_argument('--no-metadata', action='store_true',
                       help='Do not save metadata JSON files')
    parser.add_argument('--delay', type=float, default=0.5,
                       help='Delay between API requests in seconds (default: 0.5)')
    parser.add_argument('--workers', type=int, default=5,
                       help='Number of concurrent download threads (default: 5)')
    parser.add_argument('--endless', action='store_true',
                       help='Download all available images until interrupted (ignores -n)')
    parser.add_argument('--file-types', nargs='+',
                       choices=['jpg', 'png', 'webp', 'gif', 'mp4', 'webm', 'flv'],
                       help='Only download specific file types (e.g., --file-types jpg png)')
    parser.add_argument('--organize-by-nsfw', action='store_true',
                       help='Organize files into SFW/Mature/Adult folders based on NSFW level')

    # Advanced features
    parser.add_argument('--no-database', action='store_true',
                       help='Use text log instead of database (legacy mode)')
    parser.add_argument('--no-progress', action='store_true',
                       help='Disable progress bars')
    parser.add_argument('--max-retries', type=int, default=3,
                       help='Maximum retry attempts (default: 3)')
    parser.add_argument('--no-retry', action='store_true',
                       help='Disable retry logic')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview without downloading')
    parser.add_argument('--api-key', type=str,
                       help='Civitai API key for higher rate limits')

    # Web interface
    parser.add_argument('--web', action='store_true',
                       help='Launch web interface for browsing and searching')
    parser.add_argument('--port', type=int, default=5000,
                       help='Web interface port (default: 5000)')

    args = parser.parse_args()

    # Handle --generate-config
    if args.generate_config:
        generate_config_template()
        return

    # Handle search mode
    if args.search:
        search_command(args)
        return

    # Handle web interface mode
    if args.web:
        from web_interface import run_web_interface
        # Don't pass output_dir - let web interface use settings
        run_web_interface(output_dir=None, port=args.port)
        return

    # Load config file if specified
    config = {}
    if args.config:
        try:
            import yaml
            with open(args.config, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            print(f"Loaded configuration from {args.config}")
        except Exception as e:
            print(f"Warning: Could not load config file: {e}")

    # Get API key (priority: CLI > env var > config)
    api_key = args.api_key or os.environ.get('CIVITAI_API_KEY') or config.get('api', {}).get('key')

    # Determine mode
    if args.endless:
        endless_mode = True
        max_images = None
    else:
        endless_mode = False
        max_images = args.num_images if args.num_images else 100

    scraper = CivitaiScraper(
        output_dir=args.output,
        workers=args.workers,
        allowed_types=args.file_types,
        log_level=args.log_level,
        log_file=args.log_file,
        use_database=not args.no_database,
        enable_retry=not args.no_retry,
        max_retries=args.max_retries,
        dry_run=args.dry_run,
        api_key=api_key,
        organize_by_nsfw=args.organize_by_nsfw
    )

    scraper.scrape(
        max_images=max_images,
        sort=args.sort,
        period=args.period,
        nsfw=args.nsfw,
        username=args.username,
        modelId=args.model_id,
        save_metadata=not args.no_metadata,
        delay=args.delay,
        endless=endless_mode,
        nsfw_only=args.nsfw_only,
        min_resolution=args.min_resolution,
        show_progress=not args.no_progress
    )


if __name__ == '__main__':
    main()
