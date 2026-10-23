@echo off
setlocal
cd /d "%~dp0"
echo === Installation Synty Sync ===
echo Le contournement ExecutionPolicy s'applique seulement a ce processus.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_synty_sync.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
    echo Installation echouee. Code: %EXIT_CODE%
) else (
    echo Installation terminee.
)
pause
exit /b %EXIT_CODE%
