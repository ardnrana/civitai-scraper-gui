@echo off
REM Civitai Scraper Web Interface Launcher
REM This batch file launches the web interface on http://localhost:5000

echo.
echo ========================================
echo  Civitai Scraper Web Interface
echo ========================================
echo.
echo Starting web server...
echo.
echo The web interface will be available at:
echo   http://localhost:5000
echo.
echo Press Ctrl+C to stop the server
echo.
echo ========================================
echo.

python civitai_scraper.py --web --port 5000

pause
