# Settings Configuration Guide

## Overview

The Civitai Scraper now supports flexible path configuration, allowing you to:
- Store downloaded media files on any drive (e.g., external drive, different partition)
- Keep app data (database, logs, config) in the application directory
- Configure all settings through a web UI

## File Structure

```
C:\Users\PC\civitai_scraper\          # Application directory
├── config.json                        # Settings configuration
├── download_history.db                # Database (708 MB)
├── civitai_scraper.py                 # Main scraper
├── web_interface.py                   # Web UI
├── settings_manager.py                # Settings manager
└── templates/
    └── settings.html                  # Settings page

D:\civitai-scraper\downloads\          # Media files location
├── SFW\                               # SFW images
├── Mature\                            # Mature images
└── Adult\                             # Adult images
```

## Settings File (config.json)

Located at: `C:\Users\PC\civitai_scraper\config.json`

```json
{
  "download_path": "D:\\civitai-scraper\\downloads",
  "app_data_path": "C:\\Users\\PC\\civitai_scraper",
  "workers": 5,
  "api_key": "",
  "organize_by_nsfw": true,
  "log_level": "INFO",
  "enable_retry": true,
  "max_retries": 3
}
```

### Settings Explained

| Setting | Description | Default |
|---------|-------------|---------|
| `download_path` | Where downloaded images/videos are saved | `downloads` |
| `app_data_path` | Where database and logs are stored (DO NOT CHANGE) | Script directory |
| `workers` | Number of parallel downloads (1-20) | 5 |
| `api_key` | Civitai API key for NSFW access | Empty |
| `organize_by_nsfw` | Create SFW/Mature/Adult folders | true |
| `log_level` | Logging verbosity (DEBUG/INFO/WARNING/ERROR) | INFO |
| `enable_retry` | Retry failed downloads | true |
| `max_retries` | Max retry attempts | 3 |

## Web UI Settings Page

Access the settings page at: **http://localhost:5000/settings**

### Features:
- ✅ Change download location to any drive
- ✅ View current database location
- ✅ Configure concurrent workers
- ✅ Add Civitai API key
- ✅ Toggle NSFW organization
- ✅ Validate paths before saving
- ✅ Reset to defaults

### Path Configuration:

**Download Location** - Can be changed to any drive:
- ✅ D:\civitai-scraper\downloads (current)
- ✅ E:\Media\Civitai
- ✅ C:\Downloads\Civitai
- ✅ Any accessible path with write permissions

**App Data Location** - Cannot be changed:
- ❌ Fixed at C:\Users\PC\civitai_scraper
- Prevents database corruption
- Ensures config file consistency

## Changing Download Location

### Method 1: Web UI (Recommended)

1. Navigate to http://localhost:5000/settings
2. Change "Download Location" field
3. Click "Validate Paths" to verify
4. Click "Save Settings"
5. Restart the web server

### Method 2: Manual Edit

1. Stop the web server
2. Edit `C:\Users\PC\civitai_scraper\config.json`
3. Change `download_path` to your desired location
4. Save the file
5. Start the web server

Example:
```json
{
  "download_path": "E:\\MyDrive\\Civitai_Downloads",
  ...
}
```

## Database Location

**IMPORTANT**: The database always stays in the app directory!

- **Location**: `C:\Users\PC\civitai_scraper\download_history.db`
- **Size**: ~708 MB (for 39,538 images)
- **Purpose**: Stores metadata, tags, generation params, favorites
- **DO NOT MOVE**: Moving the database manually will break the app

## API Key Configuration

To download NSFW content and increase rate limits:

1. Get your API key from https://civitai.com/user/account
2. Go to http://localhost:5000/settings
3. Paste key in "Civitai API Key" field
4. Save settings
5. Restart server

OR edit config.json:
```json
{
  "api_key": "your_api_key_here",
  ...
}
```

## Troubleshooting

### Images not showing in gallery

1. Check download path in settings page
2. Verify files exist in the download location
3. Restart web server
4. Check browser console for errors

### Database errors

1. Ensure `download_history.db` is in `C:\Users\PC\civitai_scraper\`
2. Check file permissions
3. Don't manually edit the database

### Path validation fails

1. Ensure directory exists or can be created
2. Check write permissions
3. Verify no special characters in path
4. Use absolute paths (not relative)

## Best Practices

1. **Backup your database regularly**
   - Copy `download_history.db` to a safe location
   - It contains all your metadata and favorites

2. **Use a fast drive for database**
   - SSD recommended for C:\Users\PC\civitai_scraper\
   - Improves search and filter performance

3. **Use a large drive for downloads**
   - External HDD/SSD works great
   - D: drive, E: drive, network drive all supported

4. **Monitor disk space**
   - 39,538 images can be 50-200 GB
   - Database grows ~18 MB per 1000 images

5. **Don't edit config.json while server is running**
   - Stop server first
   - Edit config
   - Restart server

## Migration Guide

### Moving downloads to new drive

1. Stop web server
2. Copy all files from old location to new location
3. Update `download_path` in settings
4. Validate paths
5. Restart server

### Moving entire app to new computer

1. Copy entire `C:\Users\PC\civitai_scraper\` folder
2. Update `download_path` to point to media files
3. Update `app_data_path` to new app location
4. Run from new location

## Support

For issues:
1. Check this guide
2. Validate paths in settings
3. Check console logs
4. Verify file permissions
