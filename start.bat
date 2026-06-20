@echo off
title ⚡ CS2CaseBot - Production V1 ⚡
color 0A
setlocal enabledelayedexpansion

:: ============================================
:: CS2CASEBOOT - EPIC LAUNCHER
:: Theme: Casino Gold / Cyberpunk
:: ============================================

:: Clear screen and show banner
cls

:: ============================================
:: ASCII ART BANNER
:: ============================================
echo.
echo   ██████╗ ███████╗██████╗  ██████╗ █████╗ ███████╗███████╗██████╗  ██████╗ ████████╗
echo  ██╔════╝ ██╔════╝██╔══██╗██╔════╝██╔══██╗██╔════╝██╔════╝██╔══██╗██╔═══██╗╚══██╔══╝
echo  ██║      ███████╗██████╔╝██║     ███████║███████╗█████╗  ██████╔╝██║   ██║   ██║   
echo  ██║      ╚════██║██╔══██╗██║     ██╔══██║╚════██║██╔══╝  ██╔══██╗██║   ██║   ██║   
echo  ╚██████╗ ███████║██████╔╝╚██████╗██║  ██║███████║███████╗██║  ██║╚██████╔╝   ██║   
echo   ╚═════╝ ╚══════╝╚═════╝  ╚═════╝╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═╝ ╚═════╝    ╚═╝   
echo.
echo   ╔═══════════════════════════════════════════════════════════════════╗
echo   ║          🎰  CS2CaseBot - Premium Case Opening Bot  🎰           ║
echo   ║                    💎 Production V1.0 💎                         ║
echo   ╚═══════════════════════════════════════════════════════════════════╝
echo.

:: ============================================
:: COLOR THEME
:: ============================================
set "GOLD=[92m"
set "RED=[91m"
set "GREEN=[92m"
set "BLUE=[94m"
set "PURPLE=[95m"
set "CYAN=[96m"
set "WHITE=[97m"
set "YELLOW=[93m"
set "RESET=[0m"

:: ============================================
:: CHECK VIRTUAL ENVIRONMENT
:: ============================================
echo   [%CYAN%▶%RESET%] Checking virtual environment...

if exist ".\venv\Scripts\python.exe" (
    echo   [%GREEN%✓%RESET%] Virtual environment found
    set "PYTHON=.\venv\Scripts\python.exe"
    set "ACTIVATE=.\venv\Scripts\activate"
) else (
    echo   [%YELLOW%⚠%RESET%] Virtual environment not found, using system Python
    set "PYTHON=py"
    set "ACTIVATE="
)

:: ============================================
:: CHECK ENVIRONMENT
:: ============================================
echo   [%GREEN%✓%RESET%] Checking environment...

:: Check .env file
if not exist .env (
    echo   [%RED%✗%RESET%] ERROR: .env file not found!
    echo   [%YELLOW%!%RESET%] Please rename .env.txt to .env
    echo.
    pause
    exit /b 1
)
echo   [%GREEN%✓%RESET%] .env file found

:: Check Python
echo   [%GREEN%✓%RESET%] Checking Python...
%PYTHON% --version > nul 2>&1
if errorlevel 1 (
    echo   [%RED%✗%RESET%] Python not found! Please install Python 3.8+
    pause
    exit /b 1
)

:: ============================================
:: CHECK PACKAGES WITH COOL PROGRESS
:: ============================================
echo.
echo   [%CYAN%▶%RESET%] Checking Python packages...

set /a total=5
set /a current=0

:: Check discord.py
%PYTHON% -c "import discord" > nul 2>&1
if errorlevel 1 (
    echo   [%RED%✗%RESET%] discord.py not installed!
    echo   [%YELLOW%!%RESET%] Run: %PYTHON% -m pip install -r requirements.txt
    pause
    exit /b 1
)
set /a current+=1
echo   [%GREEN%✓%RESET%] discord.py %current%/%total%

:: Check asyncpg
%PYTHON% -c "import asyncpg" > nul 2>&1
if errorlevel 1 (
    echo   [%RED%✗%RESET%] asyncpg not installed!
    echo   [%YELLOW%!%RESET%] Run: %PYTHON% -m pip install -r requirements.txt
    pause
    exit /b 1
)
set /a current+=1
echo   [%GREEN%✓%RESET%] asyncpg %current%/%total%

:: Check fastapi
%PYTHON% -c "import fastapi" > nul 2>&1
if errorlevel 1 (
    echo   [%RED%✗%RESET%] fastapi not installed!
    echo   [%YELLOW%!%RESET%] Run: %PYTHON% -m pip install -r requirements.txt
    pause
    exit /b 1
)
set /a current+=1
echo   [%GREEN%✓%RESET%] fastapi %current%/%total%

:: Check stripe
%PYTHON% -c "import stripe" > nul 2>&1
if errorlevel 1 (
    echo   [%RED%✗%RESET%] stripe not installed!
    echo   [%YELLOW%!%RESET%] Run: %PYTHON% -m pip install -r requirements.txt
    pause
    exit /b 1
)
set /a current+=1
echo   [%GREEN%✓%RESET%] stripe %current%/%total%

:: Check uvicorn
%PYTHON% -c "import uvicorn" > nul 2>&1
if errorlevel 1 (
    echo   [%RED%✗%RESET%] uvicorn not installed!
    echo   [%YELLOW%!%RESET%] Run: %PYTHON% -m pip install -r requirements.txt
    pause
    exit /b 1
)
set /a current+=1
echo   [%GREEN%✓%RESET%] uvicorn %current%/%total%

echo   [%GREEN%✓%RESET%] All packages installed!

:: ============================================
:: CHECK POSTGRESQL
:: ============================================
echo.
echo   [%CYAN%▶%RESET%] Checking PostgreSQL...
pg_isready -h 127.0.0.1 -p 5432 > nul 2>&1
if errorlevel 1 (
    echo   [%YELLOW%⚠%RESET%] WARNING: PostgreSQL may not be running
    echo   [%YELLOW%!%RESET%] Make sure PostgreSQL is started before running
) else (
    echo   [%GREEN%✓%RESET%] PostgreSQL is running
)

:: ============================================
:: CHECK DATABASE CONNECTION
:: ============================================
echo.
echo   [%CYAN%▶%RESET%] Testing database connection...
%PYTHON% -c "import asyncpg, os; from dotenv import load_dotenv; load_dotenv(); import asyncio; asyncio.run(asyncpg.connect(os.getenv('DATABASE_URL')))" > nul 2>&1
if errorlevel 1 (
    echo   [%YELLOW%⚠%RESET%] WARNING: Cannot connect to database
    echo   [%YELLOW%!%RESET%] Check DATABASE_URL in .env
) else (
    echo   [%GREEN%✓%RESET%] Database connection successful
)

:: ============================================
:: CHECK CLOUDFLARE TUNNEL
:: ============================================
echo.
echo   [%CYAN%▶%RESET%] Checking Cloudflare Tunnel...
cloudflared tunnel list | findstr "cs2casebot" > nul 2>&1
if errorlevel 1 (
    echo   [%YELLOW%⚠%RESET%] WARNING: Cloudflare tunnel 'cs2casebot' not found
    echo   [%YELLOW%!%RESET%] Create it with: cloudflared tunnel create cs2casebot
) else (
    echo   [%GREEN%✓%RESET%] Cloudflare tunnel found
)

:: ============================================
:: CHECK STATIC FILES
:: ============================================
echo.
echo   [%CYAN%▶%RESET%] Checking static files...
if not exist "static\index.html" (
    echo   [%YELLOW%⚠%RESET%] WARNING: static/index.html not found!
    echo   [%YELLOW%!%RESET%] The dashboard may not display correctly
) else (
    echo   [%GREEN%✓%RESET%] Dashboard file found
)

:: ============================================
:: START SERVICES WITH FANCY OUTPUT
:: ============================================
echo.
echo   ════════════════════════════════════════════════════════════════
echo   [%GREEN%▶%RESET%] Starting Services...
echo   ════════════════════════════════════════════════════════════════
echo.

:: Kill any existing processes
echo   [%CYAN%!%RESET%] Cleaning up existing processes...
taskkill /F /IM py.exe /FI "WINDOWTITLE eq CS2CaseBot Bot" > nul 2>&1
taskkill /F /IM py.exe /FI "WINDOWTITLE eq CS2CaseBot Web" > nul 2>&1
timeout /t 1 /nobreak > nul

:: Start Discord Bot
echo   [%GREEN%▶%RESET%] [1/3] Starting Discord Bot...
start "CS2CaseBot Bot" /MIN %PYTHON% main.py
timeout /t 2 /nobreak > nul
echo   [%GREEN%✓%RESET%] Bot started in background

:: Start Web Server
echo   [%GREEN%▶%RESET%] [2/3] Starting Web Server...
start "CS2CaseBot Web" /MIN %PYTHON% web_server.py
timeout /t 2 /nobreak > nul
echo   [%GREEN%✓%RESET%] Web server started on port 8000

:: Start Cloudflare Tunnel
echo   [%GREEN%▶%RESET%] [3/3] Starting Cloudflare Tunnel...
start "Cloudflare Tunnel" /MIN cloudflared tunnel run cs2casebot
timeout /t 2 /nobreak > nul
echo   [%GREEN%✓%RESET%] Cloudflare tunnel started

:: ============================================
:: SHOW STATUS WITH FANCY BOX
:: ============================================
echo.
echo   ════════════════════════════════════════════════════════════════
echo   [%GREEN%✅%RESET%] ALL SERVICES STARTED SUCCESSFULLY!
echo   ════════════════════════════════════════════════════════════════
echo.
echo   [%GOLD%🌟%RESET%] DASHBOARD:  [%CYAN%https://cs2casebot.xyz%RESET%]
echo   [%GOLD%🤖%RESET%] BOT:        [%GREEN%Online in Discord%RESET%]
echo   [%GOLD%💻%RESET%] WEB SERVER: [%GREEN%Running on port 8000%RESET%]
echo   [%GOLD%🚇%RESET%] TUNNEL:     [%GREEN%Cloudflare active%RESET%]
echo.
echo   ════════════════════════════════════════════════════════════════
echo.
echo   [%YELLOW%📋%RESET%] QUICK COMMANDS:
echo   [%CYAN%  ├─%RESET%] /balance     - Check your balance
echo   [%CYAN%  ├─%RESET%] /cases       - View available cases
echo   [%CYAN%  ├─%RESET%] /open [case] - Open a case
echo   [%CYAN%  └─%RESET%] /help_bot    - Full command list
echo.
echo   ════════════════════════════════════════════════════════════════
echo.
echo   [%YELLOW%📊%RESET%] LIVE STATS:
echo   [%CYAN%  ├─%RESET%] Total Cases:  [%GREEN%37%RESET%]
echo   [%CYAN%  ├─%RESET%] Stickers:     [%GREEN%5 Capsules%RESET%]
echo   [%CYAN%  ├─%RESET%] Games:        [%GREEN%4 Games%RESET%]
echo   [%CYAN%  └─%RESET%] Premium:      [%YELLOW%Locked%RESET%] [%PURPLE%Coming Soon!%RESET%]
echo.
echo   ════════════════════════════════════════════════════════════════
echo.
echo   [%YELLOW%💡%RESET%] TIPS:
echo   [%CYAN%  ├─%RESET%] To stop: Close the terminal windows
echo   [%CYAN%  ├─%RESET%] To check logs: Check each terminal window
echo   [%CYAN%  └─%RESET%] Dashboard: Login with Discord or Google
echo.
echo   ════════════════════════════════════════════════════════════════
echo.
echo   [%GOLD%🎰%RESET%] GOOD LUCK AND HAVE FUN! [%GOLD%🎰%RESET%]
echo.

:: ============================================
:: OPTIONAL: OPEN DASHBOARD IN BROWSER
:: ============================================
choice /C YN /M "  Open dashboard in browser now? (Y/N)"
if errorlevel 2 (
    echo.
    echo   [%CYAN%!%RESET%] You can open it later at: https://cs2casebot.xyz
) else (
    echo.
    echo   [%GREEN%▶%RESET%] Opening dashboard...
    start https://cs2casebot.xyz
)

echo.
pause
exit /b 0