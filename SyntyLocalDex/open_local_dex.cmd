@echo off
setlocal
cd /d "%~dp0"
rem All locations are relative to this Dex folder; no drive letter is hard-coded.
set "PYTHON=%~dp0..\SyntyDownloader\.venv\Scripts\python.exe"
set "PYARGS="
if exist "%PYTHON%" goto RUN
where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=py"
    set "PYARGS=-3"
    goto RUN
)
where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python"
    goto RUN
)
echo [ERROR] Python 3.10+ not found. Install Python or run the SyntyDownloader installer.
pause
exit /b 1
:RUN
echo [Local Dex] Launching browser (library: ..\SyntyLibrary).
echo Press Ctrl+C to stop the local web server.
"%PYTHON%" %PYARGS% "%~dp0local_dex_server.py" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo [ERROR] Local Dex exited with code %RESULT%.
pause
exit /b %RESULT%
