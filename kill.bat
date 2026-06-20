@echo off
title 💀 CS2CaseBot - Kill Switch 💀
color 0C
setlocal enabledelayedexpansion

:: ============================================
:: CS2CASEBOOT - EPIC KILL SWITCH
:: Theme: Blood Red / Chaos / Termination
:: ============================================

:: Clear screen and show banner
cls

:: ============================================
:: ASCII ART - SKULL & CROSSBONES
:: ============================================
echo.
echo      ██╗  ██╗██╗██╗     ██╗     ███████╗██╗    ██╗██╗████████╗ ██████╗██╗  ██╗
echo      ██║ ██╔╝██║██║     ██║     ██╔════╝██║    ██║██║╚══██╔══╝██╔════╝██║  ██║
echo      █████╔╝ ██║██║     ██║     ███████╗██║ █╗ ██║██║   ██║   ██║     ███████║
echo      ██╔═██╗ ██║██║     ██║     ╚════██║██║███╗██║██║   ██║   ██║     ██╔══██║
echo      ██║  ██╗██║███████╗███████╗███████║╚███╔███╔╝██║   ██║   ╚██████╗██║  ██║
echo      ╚═╝  ╚═╝╚═╝╚══════╝╚══════╝╚══════╝ ╚══╝╚══╝ ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝
echo.
echo    ╔═══════════════════════════════════════════════════════════════════╗
echo    ║           💀  TERMINATION SEQUENCE INITIATED  💀                 ║
echo    ║              ☠️  CS2CaseBot - Kill Switch  ☠️                    ║
echo    ╚═══════════════════════════════════════════════════════════════════╝
echo.

:: ============================================
:: COLOR THEME - BLOOD RED / CHAOS
:: ============================================
set "RED=[91m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "BLUE=[94m"
set "PURPLE=[95m"
set "CYAN=[96m"
set "WHITE=[97m"
set "DARKRED=[31m"
set "RESET=[0m"

:: ============================================
:: WARNING - SKULL AND DANGER
:: ============================================
echo   [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%]
echo   [%RED%☠%RESET%]                                                 [%RED%☠%RESET%]
echo   [%RED%☠%RESET%]    %RED%WARNING: This will terminate ALL services!%RESET%    [%RED%☠%RESET%]
echo   [%RED%☠%RESET%]    %YELLOW%Make sure you want to do this!%RESET%             [%RED%☠%RESET%]
echo   [%RED%☠%RESET%]                                                 [%RED%☠%RESET%]
echo   [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%] [%RED%☠%RESET%]
echo.

:: ============================================
:: CONFIRMATION - NEEDS DOUBLE CONFIRMATION
:: ============================================
choice /C YN /M "  ☠️  Are you sure you want to terminate all services? (Y/N)"
if errorlevel 2 (
    echo.
    echo   [%GREEN%✅%RESET%] Termination cancelled. All services continue running.
    echo.
    pause
    exit /b 0
)

echo.
echo   [%RED%☠%RESET%] SECOND CONFIRMATION REQUIRED!
choice /C YN /M "  💀  Type Y to confirm termination, N to abort: "
if errorlevel 2 (
    echo.
    echo   [%GREEN%✅%RESET%] Termination aborted. Services continue running.
    echo.
    pause
    exit /b 0
)

:: ============================================
:: KILL ALL SERVICES WITH DRAMATIC EFFECT
:: ============================================
echo.
echo   ════════════════════════════════════════════════════════════════
echo   [%RED%▶%RESET%] TERMINATION SEQUENCE STARTED...
echo   ════════════════════════════════════════════════════════════════
echo.

:: Kill Discord Bot
echo   [%RED%☠%RESET%] [1/5] Terminating Discord Bot...
taskkill /F /IM py.exe /FI "WINDOWTITLE eq CS2CaseBot Bot" > nul 2>&1
if errorlevel 1 (
    echo   [%YELLOW%⚠%RESET%] Bot not running or already terminated
) else (
    echo   [%RED%☠%RESET%] Bot terminated successfully
)
timeout /t 1 /nobreak > nul

:: Kill Web Server
echo   [%RED%☠%RESET%] [2/5] Terminating Web Server...
taskkill /F /IM py.exe /FI "WINDOWTITLE eq CS2CaseBot Web" > nul 2>&1
if errorlevel 1 (
    echo   [%YELLOW%⚠%RESET%] Web server not running or already terminated
) else (
    echo   [%RED%☠%RESET%] Web server terminated successfully
)
timeout /t 1 /nobreak > nul

:: Kill Cloudflare Tunnel
echo   [%RED%☠%RESET%] [3/5] Terminating Cloudflare Tunnel...
taskkill /F /IM cloudflared.exe > nul 2>&1
if errorlevel 1 (
    echo   [%YELLOW%⚠%RESET%] Cloudflare tunnel not running or already terminated
) else (
    echo   [%RED%☠%RESET%] Cloudflare tunnel terminated successfully
)
timeout /t 1 /nobreak > nul

:: Kill any remaining Python processes
echo   [%RED%☠%RESET%] [4/5] Cleaning up remaining Python processes...
taskkill /F /IM py.exe > nul 2>&1
echo   [%RED%☠%RESET%] All Python processes terminated
timeout /t 1 /nobreak > nul

:: Kill any remaining cloudflared processes
echo   [%RED%☠%RESET%] [5/5] Cleaning up remaining Cloudflare processes...
taskkill /F /IM cloudflared.exe > nul 2>&1
echo   [%RED%☠%RESET%] All Cloudflare processes terminated
timeout /t 1 /nobreak > nul

:: ============================================
:: CHECK IF ANYTHING SURVIVED
:: ============================================
echo.
echo   [%CYAN%▶%RESET%] Checking for survivors...

:: Check if any Python processes are still running
tasklist /FI "IMAGENAME eq py.exe" 2>NUL | find /I /N "py.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo   [%YELLOW%⚠%RESET%] WARNING: Some Python processes survived!
    echo   [%RED%☠%RESET%] Force killing survivors...
    taskkill /F /IM py.exe > nul 2>&1
) else (
    echo   [%GREEN%✅%RESET%] All Python processes terminated
)

:: Check if any cloudflared processes are still running
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>NUL | find /I /N "cloudflared.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo   [%YELLOW%⚠%RESET%] WARNING: Some Cloudflare processes survived!
    echo   [%RED%☠%RESET%] Force killing survivors...
    taskkill /F /IM cloudflared.exe > nul 2>&1
) else (
    echo   [%GREEN%✅%RESET%] All Cloudflare processes terminated
)

:: ============================================
:: FINAL STATUS WITH DRAMATIC SKULL
:: ============================================
echo.
echo   ════════════════════════════════════════════════════════════════
echo   [%RED%☠%RESET%] TERMINATION COMPLETE! [%RED%☠%RESET%]
echo   ════════════════════════════════════════════════════════════════
echo.
echo   [%RED%💀%RESET%] SERVICES TERMINATED:
echo   [%CYAN%  ├─%RESET%] Discord Bot     [%RED%☠ KILLED%RESET%]
echo   [%CYAN%  ├─%RESET%] Web Server      [%RED%☠ KILLED%RESET%]
echo   [%CYAN%  └─%RESET%] Cloudflare      [%RED%☠ KILLED%RESET%]
echo.
echo   [%YELLOW%📊%RESET%] SYSTEM STATUS:
echo   [%CYAN%  ├─%RESET%] All processes   [%RED%☠ TERMINATED%RESET%]
echo   [%CYAN%  └─%RESET%] Ports cleared   [%GREEN%✅ READY%RESET%]
echo.
echo   ════════════════════════════════════════════════════════════════
echo.
echo   [%YELLOW%💡%RESET%] NEXT STEPS:
echo   [%CYAN%  ├─%RESET%] To restart: Run [%GREEN%full_restart.bat%RESET%]
echo   [%CYAN%  ├─%RESET%] To start: Run [%GREEN%start.bat%RESET%]
echo   [%CYAN%  └─%RESET%] To quick restart: Run [%GREEN%quick_restart.bat%RESET%]
echo.
echo   [%GREEN%✅%RESET%] All services have been terminated successfully!
echo   [%RED%☠%RESET%] System is ready for a fresh start [%RED%☠%RESET%]
echo.
echo   ════════════════════════════════════════════════════════════════
echo.

:: ============================================
:: OPTIONAL: LAUNCH START.BAT
:: ============================================
choice /C YN /M "  🔄 Restart services now? (Y/N)"
if errorlevel 2 (
    echo.
    echo   [%CYAN%!%RESET%] You can start manually with start.bat
) else (
    echo.
    echo   [%GREEN%▶%RESET%] Starting services...
    call start.bat
)

echo.
pause
exit /b 0