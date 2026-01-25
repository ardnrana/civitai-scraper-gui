# Civitai Scraper - Web Interface Guide

## Quick Start

### Launch the Web Interface

**Option 1: Double-click the batch file**
```
launch_web.bat
```

**Option 2: Command line**
```bash
python civitai_scraper.py --web --port 5000
```

Then open your browser to: **http://localhost:5000**

---

## Features Overview

### 1. Gallery View (`/`)
Browse all your downloaded images with advanced viewing options.

**Features:**
- **Grid View** - Thumbnail grid with adjustable sizes (Small/Medium/Large/X-Large)
- **List View** - Detailed list with metadata and file information
- **Filters:**
  - NSFW level filtering
  - Images per page (25/50/100)
  - Sort options
- **Image Details Modal** - Click any image to see:
  - Full metadata
  - Generation parameters (prompt, model, sampler, steps, CFG)
  - Tags
  - Resolution and file info

**Keyboard Shortcuts:**
- `←` Previous page
- `→` Next page
- `G` Grid view
- `L` List view

---

### 2. Control Panel (`/control`)
Start and manage downloads directly from the web interface - **no command line needed!**

#### Basic Settings
- **Number of Images**: How many to download (leave empty for endless mode)
- **Workers**: Concurrent downloads (1-20, default: 5)
- **Sort By**: Most Reactions, Most Comments, Newest
- **Time Period**: AllTime, Year, Month, Week, Day

#### Filters
- **NSFW Filter**: None (PG), Soft (PG-13), Mature (R), X (Adult), or All Levels
- **Minimum Resolution**: Filter by minimum pixels on longer side (e.g., 2048)
- **Username Filter**: Download only from specific user
- **Model ID Filter**: Download only from specific AI model

#### File Types
Select specific file types to download:
- JPG, PNG, WebP, GIF (images)
- MP4, WebM (videos)
- Leave all unchecked to download all types

#### Advanced Options
- **Organize by NSFW**: Auto-organize into SFW/Mature/Adult folders
- **NSFW Only**: Download only X and XXX rated content
- **Skip Metadata**: Don't save JSON metadata files
- **Request Delay**: Delay between API requests (default: 0.5s)
- **Max Retries**: Retry attempts for failed downloads (default: 3)
- **API Key**: Optional Civitai API key for unlimited rate limits

#### Quick Presets
One-click configurations for common scenarios:
- **Popular Images**: Most reactions from this month
- **Latest Images**: Newest from today
- **SFW Only**: Safe for work content
- **High Resolution**: 2048px+ images
- **Videos Only**: MP4 and WebM files

#### Save/Load Settings
- Save your current configuration to browser storage
- Load previously saved settings instantly

#### Real-time Status
Watch your download progress live:
- Progress bar with percentage
- Downloaded/Skipped/Failed counts
- Current status message
- Stop download button (graceful shutdown)

---

### 3. Statistics Dashboard (`/statistics`)
View comprehensive download statistics and analytics.

**Displays:**
- **Summary Cards:**
  - Total downloads count
  - Total size (GB/MB/KB)
  - Average resolution
  - Number of file types
- **Top 20 Tags**: Most used tags with counts
- **Top 20 Models**: Most used AI models with counts
- **Activity Chart**: Downloads per day (last 30 days) with interactive Chart.js graph

---

## API Endpoints

The web interface provides a REST API for programmatic access:

### Gallery Endpoints
- `GET /api/images` - List images with pagination and filters
  - Query params: `page`, `per_page`, `nsfw_level`
- `GET /api/image/<image_id>` - Get detailed image information
- `GET /api/thumbnail/<image_id>` - Get image thumbnail (300x300 JPEG)

### Download Control Endpoints
- `POST /api/download/start` - Start download with parameters (JSON body)
- `POST /api/download/stop` - Stop current download
- `GET /api/download/status` - Get current download status

### Statistics Endpoints
- `GET /api/statistics` - Get comprehensive statistics
- `GET /api/tags` - Get all tags (for autocomplete)
- `GET /api/models` - Get all models (for autocomplete)

---

## Usage Examples

### Example 1: Download Popular SFW Images
1. Open Control Panel
2. Click "SFW Only" preset
3. Set Workers to 10 for faster downloads
4. Enable "Organize by NSFW"
5. Click "Start Download"
6. Watch real-time progress!

### Example 2: Download High-Res Art
1. Open Control Panel
2. Click "High Resolution" preset
3. Set NSFW filter to "None" or "Soft"
4. Check only JPG and PNG file types
5. Set minimum resolution to 3072
6. Click "Start Download"

### Example 3: Download from Specific User
1. Open Control Panel
2. Enter username in "Username Filter"
3. Set Sort to "Newest"
4. Set Period to "Month"
5. Click "Start Download"

### Example 4: Batch Video Download
1. Open Control Panel
2. Click "Videos Only" preset
3. Set Workers to 15 (videos are larger)
4. Leave NSFW filter as "All Levels"
5. Click "Start Download"

---

## Tips & Best Practices

### Performance
- **More Workers = Faster**: Use 10-20 workers for maximum speed
- **Less Delay = Faster**: Reduce request delay (but respect API limits)
- **API Key**: Get unlimited rate limits with Civitai API key

### Organization
- **Enable NSFW Organization**: Automatically sorts into SFW/Mature/Adult folders
- **Use Filters**: Save bandwidth by filtering before downloading
- **Minimum Resolution**: Avoid low-quality images

### Storage
- **Check Total Size**: Monitor statistics dashboard for storage usage
- **File Types**: Download only needed formats to save space
- **Metadata**: Disable metadata saving if not needed

### Workflow
1. **Search in Gallery**: Browse existing downloads first
2. **Check Statistics**: See what you already have
3. **Configure Download**: Use Control Panel with precise filters
4. **Monitor Progress**: Watch real-time status
5. **Review in Gallery**: Check newly downloaded images

---

## Troubleshooting

### Web Interface Won't Start
- Check if port 5000 is available
- Try different port: `python civitai_scraper.py --web --port 8080`
- Check Python and Flask are installed: `pip install -r requirements.txt`

### Images Not Loading in Gallery
- Verify database exists: `downloads/download_history.db`
- Check files are in downloads directory
- Refresh the page (Ctrl+F5)

### Download Not Starting
- Check internet connection
- Verify API parameters are valid
- Look at browser console (F12) for errors
- Check command line output for error messages

### Thumbnails Not Generating
- Ensure Pillow is installed: `pip install pillow`
- Verify image files are not corrupted
- Check file permissions

---

## Advanced Features

### Database Access
All downloads are tracked in SQLite database with:
- Full metadata
- Generation parameters
- Tags (many-to-many relationships)
- File organization paths

### Search Integration
Use the command line search while web interface runs:
```bash
python civitai_scraper.py --search --search-tags anime fantasy
python civitai_scraper.py --search --list-tags
```

### Custom Port
```bash
python civitai_scraper.py --web --port 8080
```

### Network Access
The web interface binds to `0.0.0.0`, so you can access it from other devices on your network:
```
http://YOUR_COMPUTER_IP:5000
```

---

## Keyboard Shortcuts Summary

**Gallery View:**
- `←` Previous page
- `→` Next page
- `G` Switch to grid view
- `L` Switch to list view

---

## Browser Compatibility

Tested and working on:
- Chrome/Edge (Recommended)
- Firefox
- Safari
- Opera

Requires JavaScript enabled.

---

## Security Notes

- Web interface is for **local use only** by default
- No authentication required (local network)
- Don't expose to public internet without adding authentication
- API key is stored in browser localStorage (client-side only)

---

## Need Help?

1. Check console output for errors
2. Open browser DevTools (F12) and check Console tab
3. Review this guide for configuration tips
4. Check `download_history.db` is accessible

---

**Enjoy your fully-featured web interface! 🎉**
