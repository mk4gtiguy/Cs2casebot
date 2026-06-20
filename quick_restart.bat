@echo off
title ⚡ Quick Restart
color 0A

:: Check for virtual environment
if exist ".\venv\Scripts\python.exe" (
    set "PYTHON=.\venv\Scripts\python.exe"
) else (
    set "PYTHON=py"
)

echo ════════════════════════════════════════════════════════════════
echo  ⚡ CS2CaseBot - Quick Restart
echo ════════════════════════════════════════════════════════════════
echo.

echo [1/3] Stopping services...
taskkill /F /IM py.exe > nul 2>&1
taskkill /F /IM cloudflared.exe > nul 2>&1
timeout /t 2 /nobreak > nul
echo ✅ Stopped

echo [2/3] Starting services...
start "CS2CaseBot Bot" /MIN %PYTHON% main.py
timeout /t 2 /nobreak > nul
start "CS2CaseBot Web" /MIN %PYTHON% web_server.py
timeout /t 2 /nobreak > nul
start "Cloudflare Tunnel" /MIN cloudflared tunnel run cs2casebot
echo ✅ Started

echo [3/3] Verifying...
tasklist /FI "IMAGENAME eq py.exe" 2>NUL | find /I /N "py.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo ✅ All services running!
) else (
    echo ⚠️ Warning: No Python processes found
)

echo.
echo ════════════════════════════════════════════════════════════════
echo  ✅ All services restarted!
echo ════════════════════════════════════════════════════════════════
echo.
pause