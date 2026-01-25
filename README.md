# Civitai Image Scraper

A high-performance Python script to download images from [Civitai](https://civitai.com/images) with full support for sorting, filtering, and pagination using the official Civitai API.

## Features

- ✅ **Concurrent downloads** - Download multiple images simultaneously with configurable thread pool
- ✅ **Endless mode** - Download all available images until interrupted or completed
- ✅ **Download log** - Tracks all downloads, skips images even if deleted
- ✅ **Organized storage** - Metadata in separate folder, videos in separate folder
- ✅ **Official Civitai API** - Uses v1 API for reliable access
- ✅ **Multiple sort options** - Most Reactions, Most Comments, Newest
- ✅ **Time period filters** - AllTime, Year, Month, Week, Day
- ✅ **NSFW content filtering** - Fine-grained control over content levels
- ✅ **NSFW-only mode** - Download only Mature/X rated content
- ✅ **Resolution filtering** - Download only high-resolution images
- ✅ **Pause/Resume** - Press 'p' to pause downloads anytime
- ✅ **Filter by username or model ID** - Target specific content
- ✅ **File type filtering** - Choose which formats to download (JPG, PNG, MP4, etc.)
- ✅ **Automatic pagination** - Seamlessly fetch multiple pages
- ✅ **Save image metadata** - JSON files with prompts, settings, and tags
- ✅ **Skip already downloaded images** - Resume interrupted downloads
- ✅ **Graceful shutdown** - Ctrl+C handling for safe interruption
- ✅ **Real-time statistics** - Track downloads, skips, and failures
- ✅ **Accurate file formats** - Detects actual image format (PNG/JPG/WebP/GIF)

## Installation

1. Clone or download this repository
2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

Download 100 images with default settings (Most Reactions, All Time, 5 workers):

```bash
python civitai_scraper.py -n 100
```

### Endless Mode (Download Everything)

Download all available images until interrupted or completed:

```bash
python civitai_scraper.py --endless
```

Press `Ctrl+C` to stop gracefully.

### High-Speed Downloads

Download with 20 concurrent workers:

```bash
python civitai_scraper.py -n 500 --workers 20
```

### Download Specific Number of Images

```bash
python civitai_scraper.py -n 50 --workers 10
```

### Sort Options

Download most recent images:

```bash
python civitai_scraper.py -n 50 --sort Newest
```

Available sort options:
- `Most Reactions` (default)
- `Most Comments`
- `Newest`

### Time Period Filters

Download top images from this month:

```bash
python civitai_scraper.py -n 100 --period Month
```

Available period options:
- `AllTime` (default)
- `Year`
- `Month`
- `Week`
- `Day`

### NSFW Filtering

Download only SFW images:

```bash
python civitai_scraper.py -n 100 --nsfw None
```

Available NSFW API filter options:
- Not specified (default, downloads all browsing levels)
- `None` - PG content only
- `Soft` - PG-13 content
- `Mature` - R rated content
- `X` - Adult content (X and XXX)

Note: The API groups X and XXX together. Use `--nsfw-only` for client-side filtering of X/XXX content.

### Filter by User

Download images from a specific user:

```bash
python civitai_scraper.py -n 50 --username someuser
```

### Filter by Model ID

Download images generated with a specific model:

```bash
python civitai_scraper.py -n 100 --model-id 12345
```

### Custom Output Directory

```bash
python civitai_scraper.py -n 50 -o my_images
```

### Advanced Examples

Download 200 newest SFW images from this week with high concurrency:

```bash
python civitai_scraper.py -n 200 --sort Newest --period Week --nsfw None --workers 15
```

Endless mode - download all SFW images with 20 workers:

```bash
python civitai_scraper.py --endless --nsfw None --workers 20
```

Download only X/XXX rated adult content:

```bash
python civitai_scraper.py --endless --nsfw-only --workers 20
```

Download only high-resolution images (minimum 2048px on longer side):

```bash
python civitai_scraper.py --endless --min-resolution 2048 --workers 20
```

Combine filters (4K images, NSFW-only, newest first):

```bash
python civitai_scraper.py --endless --min-resolution 3840 --nsfw-only --sort Newest --workers 20
```

Download only JPG and PNG files (exclude videos and WebP):

```bash
python civitai_scraper.py -n 100 --file-types jpg png --workers 10
```

Download only videos (MP4 and WebM):

```bash
python civitai_scraper.py --endless --file-types mp4 webm --workers 20
```

Download only PNG images in high resolution:

```bash
python civitai_scraper.py --endless --file-types png --min-resolution 2048 --workers 15
```

Download images without saving metadata:

```bash
python civitai_scraper.py -n 100 --no-metadata --workers 10
```

Adjust delay between API requests (default 0.5 seconds):

```bash
python civitai_scraper.py -n 100 --delay 1.0 --workers 5
```

Endless mode for a specific model:

```bash
python civitai_scraper.py --endless --model-id 12345 --workers 15
```

## Command-Line Arguments

```
-n, --num-images      Number of images to download (omit for endless mode)
-o, --output          Output directory (default: downloads)
--sort                Sort order: "Most Reactions", "Most Comments", "Newest"
--period              Time period: "AllTime", "Year", "Month", "Week", "Day"
--nsfw                NSFW API filter: "None", "Soft", "Mature", "X"
                      Maps to: PG, PG-13, R, Adult (X+XXX)
--nsfw-only           Client-side filter for X and XXX rated content only
--min-resolution      Minimum resolution on longer side (e.g., 2048)
--file-types          Only download specific file types (e.g., --file-types jpg png)
                      Available types: jpg, png, webp, gif, mp4, webm, flv
--username            Filter by username
--model-id            Filter by model ID
--no-metadata         Do not save metadata JSON files
--delay               Delay between API requests in seconds (default: 0.5)
--workers             Number of concurrent download threads (default: 5)
--endless             Download all available images until interrupted
```

## Keyboard Controls

- **Press 'p'** - Pause/resume downloads at any time
- **Ctrl+C** - Gracefully stop and exit (finishes current downloads)

## Output

The scraper creates an organized folder structure:

```
downloads/
├── download_log.txt          # Log of all downloaded image IDs
├── civitai_12345.png         # Downloaded images
├── civitai_12346.jpg
├── civitai_12347.webp
├── metadata/                 # Metadata JSON files
│   ├── civitai_12345.json
│   ├── civitai_12346.json
│   └── civitai_12347.json
└── videos/                   # Video files (MP4, WebM, etc.)
    ├── civitai_12348.mp4
    └── civitai_12349.webm
```

### File Organization

1. **Images** - Saved in the root downloads folder with correct extensions
2. **Videos** - Automatically moved to `videos/` subfolder
3. **Metadata** - JSON files stored in `metadata/` subfolder
4. **Download Log** - `download_log.txt` tracks all downloaded IDs

### Metadata Contents

Each JSON file contains:
- Image ID, URL, dimensions
- Hash and NSFW level
- Creation date
- Post ID and username
- Statistics (likes, comments, etc.)
- Generation metadata (prompt, model, settings)
- Tags

## API Information

This scraper uses the official Civitai API v1:
- Endpoint: `https://civitai.com/api/v1/images`
- Maximum 200 images per request
- Supports pagination via cursor

## Performance

### Concurrent Downloads
The scraper uses a thread pool to download multiple images simultaneously. The default is 5 workers, but you can increase this for faster downloads:

- **Conservative (5 workers)**: Safe for most connections
- **Balanced (10 workers)**: Good speed without overwhelming
- **Aggressive (20+ workers)**: Maximum speed (ensure stable connection)

### Endless Mode
When using `--endless` mode:
- Downloads continue until all available images are fetched
- Press `Ctrl+C` to stop gracefully (finishes current downloads)
- Resume capability - already downloaded images are skipped
- Real-time statistics show progress

## Rate Limiting

The scraper includes a configurable delay between API requests (default 0.5 seconds) to be respectful to the Civitai API. The delay only applies to API calls, not individual image downloads.

## Notes

### Download Log Feature
- **Persistent tracking** - `download_log.txt` records every downloaded image ID
- **Skip deleted images** - Even if you delete images, they won't be re-downloaded
- **Resume anytime** - Stop and restart downloads without duplicates
- **Log format** - One image ID per line for easy tracking

### File Format Detection
- **Accurate extensions** - Detects actual file format from content, not URL
- **Supported formats** - PNG, JPEG, WebP, GIF for images; MP4, WebM for videos
- **Automatic organization** - Videos go to separate folder automatically

### General
- Thread-safe downloading with proper locking mechanisms
- Graceful shutdown on Ctrl+C (waits for active downloads to complete)
- Real-time statistics: downloaded, skipped, and failed counts
- The script will stop when it reaches the maximum number of images or runs out of results
- Metadata includes generation parameters, prompts, and model information when available

### NSFW-Only Mode
- Filters for only **X** and **XXX** rated adult content
- Skips PG, PG-13, and R rated content automatically
- Useful for curating adult content collections
- Browsing levels: PG < PG-13 < R < X < XXX

### Resolution Filtering
- **--min-resolution** filters images by their longer side dimension
- Example: `--min-resolution 2048` downloads only images >= 2048px on width or height
- Useful for high-quality collections (1080p, 2K, 4K, etc.)
- Common values: 1920 (1080p), 2048 (2K), 3840 (4K)

### Pause/Resume Feature
- **Press 'p'** during download to pause
- **Press 'p'** again to resume
- Works in endless mode and regular mode
- Current downloads finish before pausing

### File Type Filtering
- **--file-types** allows you to specify which formats to download
- Available formats: jpg, png, webp, gif, mp4, webm, flv
- Can specify multiple types: `--file-types jpg png`
- Files are downloaded first, format is detected from content, then filtered
- Useful for:
  - Only downloading images, no videos: `--file-types jpg png webp gif`
  - Only downloading videos: `--file-types mp4 webm`
  - Excluding specific formats: e.g., only jpg and png, no webp
- If omitted, all file types are downloaded
- Filtered files are counted separately in statistics

## License

This project is for educational purposes. Please respect Civitai's Terms of Service and rate limits when using this scraper.
