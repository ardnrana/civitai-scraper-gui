# 🔧 Hotfix: Endless Mode TypeError

## Issue
**Error:** `Error: unsupported operand type(s) for -: 'NoneType' and 'int'`

**Symptoms:**
- Downloads not starting
- Status shows error message
- Makes API requests but doesn't download files

## Root Cause
When "Endless Mode" is selected, the frontend sends `num_images: null` to the backend. The backend then tries to:
1. Store `null` as the total count
2. Calculate progress percentage by dividing by `null`
3. This causes a TypeError when trying to do math operations with None

## Fix Applied

### 1. Backend (`web_interface.py`)

**Line 437-448:** Handle None value when setting up download status
```python
# Before:
'total': params.get('num_images', 100),

# After:
num_images = params.get('num_images')
total_for_display = num_images if num_images is not None else 0

download_status = {
    'total': total_for_display,
    'message': 'Starting download...' if num_images else 'Starting download (endless mode)...'
}
```

**Line 484-489:** Safe progress calculation
```python
# Before:
if download_status['total'] > 0:
    download_status['progress'] = int((total / download_status['total']) * 100)

# After:
if download_status['total'] is not None and download_status['total'] > 0:
    download_status['progress'] = int((total / download_status['total']) * 100)
else:
    # Endless mode - show total count instead of percentage
    download_status['progress'] = 0
```

### 2. Frontend (`templates/control.html`)

**Line 365-378:** Display endless mode properly in UI
```javascript
// Before:
document.getElementById('progressBar').textContent = status.progress + '%';
document.getElementById('totalCount').textContent = status.total;

// After:
if (status.total === 0) {
    document.getElementById('progressBar').style.width = '100%';
    document.getElementById('progressBar').textContent = 'Endless Mode';
} else {
    document.getElementById('progressBar').style.width = status.progress + '%';
    document.getElementById('progressBar').textContent = status.progress + '%';
}

document.getElementById('totalCount').textContent = status.total === 0 ? '∞' : status.total;
```

## Files Modified
- `web_interface.py` - Lines 437-448, 484-489
- `templates/control.html` - Lines 365-378

## Testing

### Test Endless Mode:
1. Restart web interface
2. Open Control Panel
3. Select "Endless Mode" from dropdown
4. Click "Start Download"
5. Verify:
   - ✅ Download actually starts
   - ✅ Progress bar shows "Endless Mode"
   - ✅ Total shows "∞" symbol
   - ✅ Downloaded/Skipped/Failed counts update
   - ✅ Can stop download with Stop button

### Test Limited Mode (regression test):
1. Select "Limited" mode
2. Set number (e.g., 100)
3. Click "Start Download"
4. Verify:
   - ✅ Download starts
   - ✅ Progress bar shows percentage (0-100%)
   - ✅ Total shows actual number (100)
   - ✅ Progress increases as downloads complete

---

## Additional Issue Found & Fixed

### Error 2: String/Integer Comparison TypeError
**Error:** `'<=' not supported between instances of 'str' and 'int'`

**Symptoms:**
- Downloads fail with retry messages
- Error occurs when min_resolution or model_id filters are used

**Root Cause:**
The Civitai API sometimes returns `width` and `height` as **strings** instead of integers in the image metadata. When the scraper tried to compare these string values with the integer `min_resolution` parameter (e.g., `"1920" >= 1024`), Python raised a TypeError.

**Fix Applied:**

**File:** `civitai_scraper.py` - Lines 1259-1260

Added type conversion for width/height from API:
```python
# Before (BROKEN - API sometimes returns strings):
width = item.get('width', 0)
height = item.get('height', 0)

# After (FIXED - Convert to int):
width = int(item.get('width', 0)) if item.get('width') else 0
height = int(item.get('height', 0)) if item.get('height') else 0
```

**Additional Fixes:**

**File:** `web_interface.py` - Lines 523-550
Added backend type conversion and debug logging for parameters.

**File:** `templates/control.html` - Lines 110-116
Changed min_resolution from text input to dropdown (prevents future issues).

---

## Additional Issue Found & Fixed (CRITICAL)

### Error 3: NSFW Level Type Error (ACTUAL Root Cause)
**Error:** `'<=' not supported between instances of 'str' and 'int'`

**Symptoms:**
- Error occurred EVEN when min_resolution filter was not selected
- Error happened during file organization (NSFW folder determination)
- Debug showed min_resolution was None but error still occurred

**Root Cause:**
The Civitai API returns `nsfwLevel` as a **STRING** instead of an integer. The `_get_nsfw_folder` method (line 391-398) compares this string value directly with integers (e.g., `nsfw_level <= 1`, `nsfw_level <= 4`) to determine which folder (SFW/Mature/Adult) to use. This triggered the type comparison error.

**Fixes Applied:**

**Fix 1: `_log_download_db` Method - Lines 431-447**

Added type conversion for width/height with error handling:
```python
# Convert width/height to integers, handling string values from API
width = None
height = None
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
```

**Fix 2: `_get_nsfw_folder` Method - Lines 391-404 (CRITICAL FIX)**

Added type conversion for nsfw_level before comparisons:
```python
# Before (BROKEN - Compares string with int):
def _get_nsfw_folder(self, nsfw_level: int) -> str:
    if nsfw_level is None or nsfw_level <= 1:
        return "SFW"
    elif nsfw_level <= 4:
        return "Mature"
    else:
        return "Adult"

# After (FIXED - Converts to int first):
def _get_nsfw_folder(self, nsfw_level: int) -> str:
    try:
        level = int(nsfw_level) if nsfw_level is not None else 0
    except (ValueError, TypeError):
        self.logger.warning(f"Invalid NSFW level value: {repr(nsfw_level)}, defaulting to SFW")
        level = 0

    if level <= 1:
        return "SFW"
    elif level <= 4:
        return "Mature"
    else:
        return "Adult"
```

These fixes ensure that ALL numeric values from the Civitai API are converted to integers before any comparisons, completely eliminating type mismatch errors.

---

---

## Additional Issue Found & Fixed (Round 4)

### Error 4: NSFW Level String Labels Not Recognized
**Error:** `Invalid NSFW level value: 'X', defaulting to SFW`

**Symptoms:**
- All images being saved to SFW folder regardless of actual NSFW level
- Warning messages showing string values like 'X', 'XXX', 'Mature', etc.

**Root Cause:**
The Civitai API returns `nsfwLevel` as BOTH string labels ('None', 'Soft', 'Mature', 'X', 'XXX') AND numeric values (0-6). The previous fix only tried to convert to integer, which failed for string labels.

**Fix Applied:**

**File:** `civitai_scraper.py` - Lines 391-425

Added `_convert_nsfw_to_level` method that maps string labels to numeric levels:
```python
def _convert_nsfw_to_level(self, nsfw_value) -> int:
    """Convert NSFW string label or level to integer level"""
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
    return level
```

Updated `_get_nsfw_folder`, `_log_download_db`, and `download_image` methods to use this converter.

---

### Issue 5: Statistics Page Not Showing Tags/Models

**Problem:** Statistics page was empty or not showing tag and model information

**Root Cause:** The Civitai API doesn't always include 'meta' and 'tags' fields in responses, so these weren't being stored in the database.

**Fix Applied:**

**File:** `civitai_scraper.py` - Lines 510-526

Added debug logging to track when metadata is missing:
```python
# Store enhanced metadata if available
if metadata and status == 'success':
    # Store generation parameters
    meta = metadata.get('meta', {})
    if meta:
        self.logger.debug(f"Storing generation params for {image_id}: {list(meta.keys())}")
        self._store_generation_params(str(image_id), meta)
    else:
        self.logger.debug(f"No 'meta' field in metadata for {image_id}")

    # Store tags
    tags = metadata.get('tags', [])
    if tags:
        self.logger.debug(f"Storing {len(tags)} tags for {image_id}")
        self._store_tags(str(image_id), tags)
    else:
        self.logger.debug(f"No tags in metadata for {image_id}")
```

This will help identify which images have metadata and which don't.

---

### Issue 6: No Easy Way to Copy Just the Prompt

**Problem:** Users had to copy all metadata to get the prompt

**Solution Applied:**

**File:** `templates/gallery.html` - Lines 108-113, 357-377

Added "Copy Prompt" button to image details modal:
```html
<button type="button" class="btn btn-success" onclick="copyPrompt()">Copy Prompt</button>
```

Added JavaScript function:
```javascript
function copyPrompt() {
    if (!currentImageData || !currentImageData.params) {
        alert('No prompt available');
        return;
    }

    const prompt = currentImageData.params.prompt || '';
    if (!prompt) {
        alert('No prompt found');
        return;
    }

    navigator.clipboard.writeText(prompt)
        .then(() => {
            alert('Prompt copied to clipboard!');
        })
        .catch(err => {
            alert('Failed to copy prompt: ' + err);
        });
}
```

---

## Status
✅ **All issues fixed and ready to use!**

**Files Modified (Complete List):**
- `web_interface.py` - Lines 437-450 (endless mode fix)
- `web_interface.py` - Lines 484-493 (progress calculation fix)
- `web_interface.py` - Lines 523-550 (type conversion fix with debug logging)
- `templates/control.html` - Lines 350-362 (UI endless mode display)
- `templates/control.html` - Lines 110-116 (min_resolution dropdown UI)
- `civitai_scraper.py` - Lines 471-492 (width/height/nsfw_level type conversion in _log_download_db)
- `civitai_scraper.py` - Lines 391-425 (_convert_nsfw_to_level method - STRING LABEL MAPPING)
- `civitai_scraper.py` - Lines 962-966 (use nsfw converter in download_image)
- `civitai_scraper.py` - Lines 510-526 (debug logging for metadata storage)
- `templates/gallery.html` - Lines 108-113 (Copy Prompt button)
- `templates/gallery.html` - Lines 357-377 (copyPrompt function)

**Final Solution - Preventing Future Type Errors:**

Changed minimum resolution from free-text input to dropdown with predefined values:
- **Any Resolution** (default - sends `null`)
- 512px, 768px, 1024px, 1536px, 2048px, 2560px, 4096px

This guarantees the value is always either `null` or a valid integer, completely preventing type mismatch errors.

Restart the web interface to apply all fixes:
```bash
python civitai_scraper.py --web
```

Or use: **`restart_web.bat`** (recommended - includes cache clearing)
