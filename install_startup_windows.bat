@echo off
REM ============================================================
REM  Make Download Organizer start automatically at login.
REM  Run this AFTER build_windows.bat (it points at dist\Download Organizer.exe).
REM  To undo: open  shell:startup  and delete the shortcut.
REM ============================================================
setlocal
cd /d "%~dp0"

set "TARGET=%~dp0dist\Download Organizer.exe"
if not exist "%TARGET%" (
    echo Could not find "%TARGET%".
    echo Run build_windows.bat first.
    pause
    exit /b 1
)

powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([System.IO.Path]::Combine($env:APPDATA,'Microsoft\Windows\Start Menu\Programs\Startup\Download Organizer.lnk'));" ^
  "$s.TargetPath='%TARGET%';" ^
  "$s.WorkingDirectory=[System.IO.Path]::GetDirectoryName('%TARGET%');" ^
  "$s.IconLocation='%TARGET%';" ^
  "$s.Save()"

echo Done. Download Organizer will start at login.
echo (To remove: press Win+R, type  shell:startup  and delete the shortcut.)
pause
endlocal
