@echo off
title 🔄 CS2CaseBot - Restart Sequence 🔄
color 0E
setlocal enabledelayedexpansion

:: ============================================
:: CS2CASEBOOT - EPIC RESTART SEQUENCE
:: Theme: Gold / Phoenix Rising / Rebirth
:: ============================================

:: Clear screen and show banner
cls

:: ============================================
:: ASCII ART - PHOENIX / REBIRTH
:: ============================================
echo.
echo    ██████╗ ███████╗███████╗████████╗ █████╗ ██████╗ ████████╗
echo    ██╔══██╗██╔════╝██╔════╝╚══██╔══╝██╔══██╗██╔══██╗╚══██╔══╝
echo    ██████╔╝█████╗  ███████╗   ██║   ███████║██████╔╝   ██║   
echo    ██╔══██╗██╔══╝  ╚════██║   ██║   ██╔══██║██╔══██╗   ██║   
echo    ██║  ██║███████╗███████║   ██║   ██║  ██║██║  ██║   ██║   
echo    ╚═╝  ╚═╝╚══════╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   
echo.
echo    ╔═══════════════════════════════════════════════════════════════════╗
echo    ║        🔄  CS2CaseBot - RESTART SEQUENCE  🔄                      ║
echo    ║              🌟  Rebirth of the Bot  🌟                          ║
echo    ╚═══════════════════════════════════════════════════════════════════╝
echo.

:: ============================================
:: COLOR THEME - GOLD / PHOENIX
:: ============================================
set "GOLD=[93m"
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
if exist ".\venv\Scripts\python.exe" (
    set "PYTHON=.\venv\Scripts\python.exe"
) else (
    set "PYTHON=py"
)

:: ============================================
:: STEP 1: KILL EVERYTHING
:: ============================================
echo   [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%]
echo   [%GOLD%🔥%RESET%]                                                 [%GOLD%🔥%RESET%]
echo   [%GOLD%🔥%RESET%]    %YELLOW%Phase 1: Terminating Services%RESET%                  [%GOLD%🔥%RESET%]
echo   [%GOLD%🔥%RESET%]                                                 [%GOLD%🔥%RESET%]
echo   [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%] [%GOLD%🔥%RESET%]
echo.

:: Kill Discord Bot
echo   [%RED%☠%RESET%] Terminating Discord Bot...
taskkill /F /IM py.exe /FI "WINDOWTITLE eq CS2CaseBot Bot" > nul 2>&1
timeout /t 1 /nobreak > nul

:: Kill Web Server
echo   [%RED%☠%RESET%] Terminating Web Server...
taskkill /F /IM py.exe /FI "WINDOWTITLE eq CS2CaseBot Web" > nul 2>&1
timeout /t 1 /nobreak > nul

:: Kill Cloudflare Tunnel
echo   [%RED%☠%RESET%] Terminating Cloudflare Tunnel...
taskkill /F /IM cloudflared.exe > nul 2>&1
timeout /t 1 /nobreak > nul

:: Kill all remaining Python processes
echo   [%RED%☠%RESET%] Cleaning up remaining processes...
taskkill /F /IM py.exe > nul 2>&1
timeout /t 1 /nobreak > nul

echo.
echo   [%GREEN%✅%RESET%] All services terminated!
echo.

:: ============================================
:: STEP 2: WAIT FOR CLEANUP
:: ============================================
echo   [%CYAN%⏳%RESET%] Waiting for cleanup...
echo   [%CYAN%  ├─%RESET%] Releasing ports...
timeout /t 2 /nobreak > nul
echo   [%CYAN%  ├─%RESET%] Clearing memory...
timeout /t 1 /nobreak > nul
echo   [%CYAN%  └─%RESET%] Ready for restart...
timeout /t 1 /nobreak > nul

:: ============================================
:: STEP 3: RESTART EVERYTHING
:: ============================================
echo.
echo   ════════════════════════════════════════════════════════════════
echo   [%GOLD%🔥%RESET%] Phase 2: Phoenix Rising - Restarting Services...
echo   ════════════════════════════════════════════════════════════════
echo.

:: Start Discord Bot
echo   [%GREEN%▶%RESET%] [1/3] Starting Discord Bot...
start "CS2CaseBot Bot" /MIN %PYTHON% main.py
timeout /t 2 /nobreak > nul
echo   [%GREEN%✓%RESET%] Bot started

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
:: VERIFY SERVICES ARE RUNNING
:: ============================================
echo.
echo   [%CYAN%▶%RESET%] Verifying services...

:: Check if processes are running
tasklist /FI "IMAGENAME eq py.exe" 2>NUL | find /I /N "py.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo   [%GREEN%✅%RESET%] Python processes running
) else (
    echo   [%YELLOW%⚠%RESET%] WARNING: No Python processes found!
)

:: ============================================
:: FINAL STATUS - PHOENIX RISING
:: ============================================
echo.
echo   ════════════════════════════════════════════════════════════════
echo   [%GOLD%🔥%RESET%] PHOENIX RISING - RESTART COMPLETE! [%GOLD%🔥%RESET%]
echo   ════════════════════════════════════════════════════════════════
echo.
echo   [%GOLD%🌟%RESET%] SERVICES RESTARTED:
echo   [%CYAN%  ├─%RESET%] Discord Bot     [%GREEN%✅ ONLINE%RESET%]
echo   [%CYAN%  ├─%RESET%] Web Server      [%GREEN%✅ ONLINE%RESET%]
echo   [%CYAN%  └─%RESET%] Cloudflare      [%GREEN%✅ ONLINE%RESET%]
echo.
echo   [%GOLD%🎰%RESET%] DASHBOARD:  [%CYAN%https://cs2casebot.xyz%RESET%]
echo   [%GOLD%🤖%RESET%] BOT:        [%GREEN%Online in Discord%RESET%]
echo   [%GOLD%💻%RESET%] WEB SERVER: [%GREEN%Running on port 8000%RESET%]
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
echo   [%GOLD%🔥%RESET%] THE BOT HAS RISEN FROM THE ASHES! [%GOLD%🔥%RESET%]
echo.

:: ============================================
:: OPTIONAL: OPEN DASHBOARD
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