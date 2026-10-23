@echo off
setlocal
cd /d "%~dp0"
echo === Synty Sync ===
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_synty_sync.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
    echo Synchronisation echouee. Code: %EXIT_CODE%
) else (
    echo Synchronisation terminee.
)
pause
exit /b %EXIT_CODE%
