@echo off
REM ============================================================
REM  Download Organizer - run from source (no .exe build needed)
REM  Needs Python 3.10+ installed (https://www.python.org, "Add to PATH").
REM ============================================================
setlocal
cd /d "%~dp0"

python -m pip install -r requirements-windows.txt
if errorlevel 1 (
    echo ERROR: pip install failed. Is Python on your PATH?  python --version
    pause
    exit /b 1
)

REM pythonw = no console window; the app lives in the system tray.
start "" pythonw organizer_win.py
endlocal
