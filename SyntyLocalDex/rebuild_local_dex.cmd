@echo off
setlocal
cd /d "%~dp0"
rem Discovers SyntyLibrary next to this Dex folder, regardless of drive.
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
echo [Local Dex] Refreshing catalog from ..\SyntyLibrary...
"%PYTHON%" %PYARGS% "%~dp0build_local_dex.py" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo [ERROR] Indexing failed with code %RESULT%.
pause
exit /b %RESULT%
