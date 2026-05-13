@echo off
echo.
echo [Playwright Setup] Installing Chromium browser binary...
echo This is required for Spotify artist and channel scraping.
echo.

REM Check if venv exists and use it, otherwise use system python
if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe -m playwright install chromium
) else (
    python -m playwright install chromium
)

echo.
echo ==========================================
echo Playwright browser installed successfully!
echo ==========================================
pause
