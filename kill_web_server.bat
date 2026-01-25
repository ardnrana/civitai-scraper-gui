@echo off
REM Force kill the Civitai Scraper web server

echo.
echo ========================================
echo  Force Killing Web Server
echo ========================================
echo.

echo Searching for Python web server processes...
echo.

REM Find and kill Python processes running civitai_scraper.py
for /f "tokens=2" %%i in ('tasklist /fi "imagename eq python.exe" /fo list ^| findstr /i "PID"') do (
    echo Checking PID %%i...
    wmic process where "ProcessId=%%i" get CommandLine | findstr /i "civitai_scraper.py --web" >nul
    if not errorlevel 1 (
        echo Found web server process: PID %%i
        echo Killing process...
        taskkill /PID %%i /F
        echo Process killed successfully!
        echo.
    )
)

echo.
echo ========================================
echo  Done! You can now restart the server.
echo ========================================
echo.
echo To restart: python civitai_scraper.py --web
echo Or run: launch_web.bat
echo.

pause
