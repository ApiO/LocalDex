@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0SyntyDownloader\.venv\Scripts\python.exe"
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
echo [ERROR] Python 3.10+ was not found. Run install.cmd first.
pause
exit /b 1
:RUN
echo [Local Dex] Opening the local catalog...
echo Press Ctrl+C to stop the local web server.
"%PYTHON%" %PYARGS% "%~dp0SyntyLocalDex\local_dex_server.py" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo [ERROR] Local Dex exited with code %RESULT%.
pause
exit /b %RESULT%
