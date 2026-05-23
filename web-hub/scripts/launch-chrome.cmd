@echo off
:: Launch Chrome with remote debugging port for CDP Proxy
:: Usage: double-click this file or run from terminal

echo Closing Chrome...
taskkill /F /IM chrome.exe >nul 2>&1
timeout /t 4 /nobreak >nul

echo Starting Chrome with debug port 9222...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\Google\Chrome\User Data"

echo Chrome launched. Run check-deps.mjs to verify.
