@echo off
title CS2CaseBot Launcher
color 0A

echo ============================================================
echo  🚀 CS2CaseBot - Production V1
echo ============================================================
echo.

:: Check if .env exists
if not exist .env (
    echo ❌ ERROR: .env file not found!
    echo Please rename .env.txt to .env
    pause
    exit /b 1
)
echo ✅ .env file found

:: Check Python packages
echo.
echo Checking Python packages...
py -c "import discord" > nul 2>&1
if errorlevel 1 (
    echo ❌ discord.py not installed!
    echo Run: py -m pip install -r requirements.txt
    pause
    exit /b 1
)

py -c "import asyncpg" > nul 2>&1
if errorlevel 1 (
    echo ❌ asyncpg not installed!
    echo Run: py -m pip install -r requirements.txt
    pause
    exit /b 1
)

py -c "import fastapi" > nul 2>&1
if errorlevel 1 (
    echo ❌ fastapi not installed!
    echo Run: py -m pip install -r requirements.txt
    pause
    exit /b 1
)

py -c "import stripe" > nul 2>&1
if errorlevel 1 (
    echo ❌ stripe not installed!
    echo Run: py -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo ✅ All packages installed

:: Check PostgreSQL
echo.
echo Checking PostgreSQL...
pg_isready -h 127.0.0.1 -p 5432 > nul 2>&1
if errorlevel 1 (
    echo ⚠️  WARNING: PostgreSQL may not be running
    echo Make sure PostgreSQL is started before running the bot
) else (
    echo ✅ PostgreSQL is running
)

:: Check Cloudflare Tunnel (optional)
echo.
echo Checking Cloudflare Tunnel...
cloudflared tunnel list | findstr "cs2casebot" > nul 2>&1
if errorlevel 1 (
    echo ⚠️  WARNING: Cloudflare tunnel 'cs2casebot' not found
    echo Create it with: cloudflared tunnel create cs2casebot
) else (
    echo ✅ Cloudflare tunnel found
)

echo.
echo ============================================================
echo  Starting Services...
echo ============================================================
echo.

:: Start Discord Bot
echo [1/3] Starting Discord Bot...
start "CS2CaseBot Bot" py main.py
timeout /t 3 /nobreak > nul

:: Start Web Server
echo [2/3] Starting Web Server...
start "CS2CaseBot Web" py web_server.py
timeout /t 3 /nobreak > nul

:: Start Cloudflare Tunnel
echo [3/3] Starting Cloudflare Tunnel...
start "Cloudflare Tunnel" cloudflared tunnel run cs2casebot
timeout /t 2 /nobreak > nul

echo.
echo ============================================================
echo  ✅ All services started!
echo  🌐 Dashboard: https://cs2casebot.xyz
echo  🤖 Bot: Online in Discord
echo  💻 Web Server: Running on port 8000
echo  🚇 Tunnel: Cloudflare tunnel active
echo.
echo  🛑 To stop: Close each terminal window
echo  📋 To check logs: Check console windows
echo.
echo  💡 Quick Commands:
echo     - /balance - Check your balance
echo     - /cases - View available cases
echo     - /open [case] - Open a case
echo     - /help_bot - Full command list
echo ============================================================
echo.
pause