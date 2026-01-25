# Troubleshooting Guide - Civitai Scraper

## Common Issues and Solutions

### 1. Web Interface - Signal Handler Error

**Error Message:**
```
ValueError: signal only works in main thread of the main interpreter
```

**Solution:**
This has been fixed! The scraper now has an `enable_signal_handler` parameter that's automatically set to `False` when running in a background thread (web interface).

**What was changed:**
- Added `enable_signal_handler=False` parameter to CivitaiScraper when creating instances in background threads
- Signal handler is now wrapped in try/except to gracefully handle threading scenarios

---

### 2. Web Interface Won't Start

**Symptoms:**
- Can't access http://localhost:5000
- Port already in use error

**Solutions:**

1. **Check if port is in use:**
   ```bash
   netstat -ano | findstr :5000
   ```

2. **Use different port:**
   ```bash
   python civitai_scraper.py --web --port 8080
   ```

3. **Kill existing process:**
   - Find PID from netstat command
   - `taskkill /PID <pid> /F`

---

### 3. Downloads Not Starting from Web UI

**Symptoms:**
- Click "Start Download" but nothing happens
- Status stays "Ready to start"

**Solutions:**

1. **Check browser console (F12):**
   - Look for JavaScript errors
   - Check Network tab for failed API calls

2. **Check command line output:**
   - Look for Python errors in the terminal
   - Check for API connection issues

3. **Verify parameters:**
   - Make sure Number of Images is set
   - Check that API key is valid (if provided)
   - Verify internet connection

4. **Check database:**
   - Ensure `downloads/download_history.db` is accessible
   - Not locked by another process

---

### 4. Thumbnails Not Loading

**Symptoms:**
- Gallery shows broken image icons
- Thumbnails fail to generate

**Solutions:**

1. **Install Pillow:**
   ```bash
   pip install pillow
   ```

2. **Check image files exist:**
   - Verify files are in downloads directory
   - Check file permissions

3. **Check file paths:**
   - If using organized mode, check SFW/Mature/Adult folders
   - Verify database has correct folder_path entries

---

### 5. Real-time Status Not Updating

**Symptoms:**
- Progress bar stuck at 0%
- Download counts not incrementing

**Solutions:**

1. **Hard refresh browser:**
   - Press Ctrl+F5 to clear cache
   - Check browser console for errors

2. **Check scraper instance:**
   - Verify download actually started (check command line)
   - Look for errors in Python output

3. **API endpoint check:**
   ```bash
   # While download running, test in browser:
   http://localhost:5000/api/download/status
   ```

---

### 6. ModuleNotFoundError: No module named 'flask'

**Error:**
```
ModuleNotFoundError: No module named 'flask'
```

**Solution:**
```bash
pip install -r requirements.txt
```

Or install individually:
```bash
pip install flask pillow
```

---

### 7. Database Locked Error

**Error:**
```
sqlite3.OperationalError: database is locked
```

**Solutions:**

1. **Close other instances:**
   - Make sure no other civitai_scraper processes are running
   - Check Task Manager for python.exe processes

2. **Close database connections:**
   - Stop the web interface
   - Restart it fresh

3. **Last resort - delete lock:**
   ```bash
   # Only if no processes are using it!
   del downloads\download_history.db-journal
   ```

---

### 8. Downloads Complete But Not in Gallery

**Symptoms:**
- Downloads successful from CLI
- Web gallery shows empty or old images

**Solutions:**

1. **Refresh gallery page:**
   - Press F5 or click browser refresh
   - Clear browser cache (Ctrl+Shift+Delete)

2. **Check database:**
   - Verify downloads table has entries
   - Run: `sqlite3 downloads/download_history.db "SELECT COUNT(*) FROM downloads;"`

3. **Restart web interface:**
   - Stop the web server (Ctrl+C)
   - Restart: `python civitai_scraper.py --web`

---

### 9. Memory Issues / High RAM Usage

**Symptoms:**
- Python process using lots of RAM
- System slowing down

**Solutions:**

1. **Reduce workers:**
   - Set workers to 3-5 instead of 10-20
   - Fewer concurrent downloads = less memory

2. **Disable progress bars:**
   - Already done automatically in web mode

3. **Close browser when not needed:**
   - Thumbnails in gallery use RAM
   - Close tab when not actively browsing

4. **Restart web interface periodically:**
   - Stop and restart every few hundred downloads

---

### 10. API Rate Limiting

**Symptoms:**
- "Too Many Requests" errors
- Downloads slowing down or failing

**Solutions:**

1. **Increase delay:**
   - Set delay to 1.0 or higher in Control Panel
   - Default is 0.5 seconds

2. **Get API key:**
   - Sign up at civitai.com
   - Get your API key from account settings
   - Enter in Control Panel API Key field
   - Unlimited rate limits!

3. **Reduce workers temporarily:**
   - Lower concurrent downloads
   - Less strain on API

---

### 11. Network/Connection Errors

**Error:**
```
ConnectionError: Max retries exceeded
requests.exceptions.RequestException
```

**Solutions:**

1. **Check internet connection:**
   - Verify you can access civitai.com in browser
   - Test: `ping civitai.com`

2. **Use VPN if blocked:**
   - Some ISPs/countries may block civitai.com
   - Try using a VPN

3. **Increase retry count:**
   - Set Max Retries to 5 or higher in Control Panel

4. **Check firewall:**
   - Allow Python through Windows Firewall
   - Check antivirus isn't blocking requests

---

### 12. Statistics Dashboard Not Loading

**Symptoms:**
- Statistics page blank or stuck loading
- Charts not appearing

**Solutions:**

1. **Check Chart.js CDN:**
   - Requires internet connection for CDN
   - Check browser console for 404 errors

2. **Verify database has data:**
   - Need downloads in database for stats
   - Run a few downloads first

3. **Clear browser cache:**
   - Ctrl+Shift+Delete
   - Clear cached images and files

---

## Performance Optimization Tips

### For Faster Downloads:
- Increase workers to 10-20 (if you have good internet)
- Get Civitai API key for no rate limits
- Reduce delay to 0.1-0.3 seconds (with API key)
- Use SSD for downloads folder

### For Lower Resource Usage:
- Reduce workers to 3-5
- Increase delay to 1.0+ seconds
- Close web interface when not needed
- Disable metadata saving if not needed

### For Better Organization:
- Enable "Organize by NSFW"
- Use specific filters (resolution, file types)
- Save your settings for quick access

---

## Getting Help

1. **Check this guide first**
2. **Look at browser console (F12) for errors**
3. **Check command line output for Python errors**
4. **Try restarting the web interface**
5. **Verify all dependencies installed:** `pip install -r requirements.txt`

---

## Debug Mode

To get more detailed error information:

1. **Enable debug logging:**
   ```bash
   python civitai_scraper.py --web --log-level DEBUG
   ```

2. **Check log file:**
   ```bash
   python civitai_scraper.py --web --log-file scraper.log
   ```

3. **Browser DevTools:**
   - Press F12
   - Go to Console tab
   - Look for red error messages
   - Check Network tab for failed requests

---

## Still Having Issues?

If none of these solutions work:

1. Restart your computer (seriously, this fixes weird issues)
2. Reinstall dependencies: `pip uninstall -y flask pillow && pip install flask pillow`
3. Try a fresh download to a new folder
4. Check if antivirus is interfering
5. Make sure you're using Python 3.8 or higher

---

**Last Updated:** After fixing signal handler threading issue
**Version:** 2.0 (with web interface)
