@echo off
setlocal
cd /d "%~dp0"
echo === Synty Project Installation ===
echo The PowerShell execution-policy override is limited to this process.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0SyntyDownloader\install_synty_sync.ps1" %*
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" (echo [ERROR] Installer exited with code %RESULT%.) else (echo Installation complete. Run launch_localdex.cmd next.)
pause
exit /b %RESULT%
