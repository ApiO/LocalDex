@echo off
setlocal
cd /d "%~dp0"
rem Dex-owned integration launcher. The downloader files are NOT modified.
for %%I in ("%~dp0..\SyntyLibrary") do set "LIBRARY=%%~fI"
for %%I in ("%~dp0..\SyntyDownloader\run_synty_sync.ps1") do set "SYNC_SCRIPT=%%~fI"
if not exist "%SYNC_SCRIPT%" (
    echo [ERROR] Downloader not found: %SYNC_SCRIPT%
    pause
    exit /b 1
)
if not exist "%LIBRARY%\" mkdir "%LIBRARY%"
echo [1/2] Running downloader into "%LIBRARY%"...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SYNC_SCRIPT%" -OutputDir "%LIBRARY%"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo [ERROR] Downloader failed with code %RESULT%. Dex index not rebuilt.
    pause
    exit /b %RESULT%
)
echo [2/2] Rebuilding the Dex catalog...
call "%~dp0rebuild_local_dex.cmd"
exit /b %ERRORLEVEL%
