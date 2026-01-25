@echo off
REM Civitai Scraper - Clean Restart Script
REM Kills running server, clears cache, restarts fresh

echo.
echo ========================================
echo  Civitai Scraper - Clean Restart
echo ========================================
echo.

echo [1/4] Stopping server...
tasklist /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *civitai_scraper*" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    for /f "tokens=2" %%i in ('tasklist /fi "imagename eq python.exe" /fo list ^| findstr /i "PID"') do (
        wmic process where "ProcessId=%%i" get CommandLine 2^>nul | findstr /i "web_interface\|civitai_scraper.py --web" >nul 2>&1
        if not errorlevel 1 (
            taskkill /PID %%i /F >nul 2>&1
            echo   - Stopped server (PID %%i)
        )
    )
) else (
    echo   - No server running
)
echo.

echo [2/4] Clearing cache...
if exist __pycache__ (
    rd /S /Q __pycache__ >nul 2>&1
    echo   - Removed __pycache__
)
del /S *.pyc >nul 2>&1
echo   - Cleaned up .pyc files
echo.

echo [3/4] Waiting for cleanup...
timeout /t 2 /nobreak >nul
echo   - Ready!
echo.

echo [4/4] Starting server...
echo.
echo ========================================
echo  Server: http://localhost:5000
echo  Press Ctrl+C to stop
echo ========================================
echo.

python web_interface.py

pause
