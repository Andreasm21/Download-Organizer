@echo off
REM ============================================================
REM  Download Organizer - build a standalone Windows .exe
REM  Run this ON A WINDOWS MACHINE that has Python 3.10+ installed
REM  (get Python from https://www.python.org - tick "Add to PATH").
REM  Result: dist\Download Organizer.exe  (double-clickable, no Python needed)
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo === Installing build dependencies ===
python -m pip install --upgrade pip
python -m pip install -r requirements-windows.txt pyinstaller
if errorlevel 1 (
    echo.
    echo ERROR: pip install failed. Is Python on your PATH? Try: python --version
    pause
    exit /b 1
)

echo.
echo === Building Download Organizer.exe ===
pyinstaller --noconfirm --onefile --windowed ^
    --name "Download Organizer" ^
    --icon appicon.ico ^
    --hidden-import pystray._win32 ^
    --add-data "dashboard.html;." ^
    --add-data "config.json;." ^
    --add-data "appicon.ico;." ^
    organizer_win.py
if errorlevel 1 (
    echo.
    echo ERROR: build failed. See messages above.
    pause
    exit /b 1
)

echo.
echo === DONE ===
echo Your app is here:  dist\Download Organizer.exe
echo You can copy that single file anywhere and double-click it.
echo (It lives in the system tray - bottom-right, near the clock.)
echo.
pause
endlocal
