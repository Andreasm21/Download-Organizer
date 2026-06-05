==========================================================
  Download Organizer - Windows Edition
==========================================================

Auto-sorts your Downloads folder into category subfolders the moment
files land. Lives in the SYSTEM TRAY (bottom-right, near the clock) and
has a dashboard you open in your browser.

----------------------------------------------------------
WHAT'S IN THIS FOLDER
----------------------------------------------------------
  organizer_win.py          the app (Windows tray UI)
  organizer.py              the shared sorting engine
  dashboard.html            the dashboard web page
  config.json               which file types go where (edit to taste)
  appicon.ico               app icon
  requirements-windows.txt  Python packages it needs
  build_windows.bat         -> builds a single Download Organizer.exe
  run_windows.bat           -> runs it straight from source (no build)
  install_startup_windows.bat -> start automatically at login

----------------------------------------------------------
FIRST: install Python (one time)
----------------------------------------------------------
1. Get Python 3.10+ from  https://www.python.org/downloads/
2. IMPORTANT: on the first install screen, tick
   "Add Python to PATH", then click Install.

----------------------------------------------------------
OPTION A - Build a real .exe  (recommended, gives you one file to keep)
----------------------------------------------------------
1. Double-click  build_windows.bat
2. Wait for "DONE". Your app is:   dist\Download Organizer.exe
3. Copy that single .exe anywhere and double-click to run.
   It appears in the system tray (no window pops up - that's normal).

----------------------------------------------------------
OPTION B - Just run it (no build)
----------------------------------------------------------
1. Double-click  run_windows.bat
   It installs the packages and launches straight away.

----------------------------------------------------------
USING IT
----------------------------------------------------------
- Look in the SYSTEM TRAY (bottom-right). Click the arrow (^) if hidden.
- RIGHT-CLICK the icon for the menu:
    Open Dashboard   - see what was sorted, with quick-open buttons
    Organize Now     - sort everything sitting in Downloads right now
    Pause / Resume   - stop or start auto-watching
    Open Downloads   - open your Downloads folder
    Edit Config      - change the category rules
    Quit
- LEFT-CLICK (or double-click) the icon = open the dashboard.
- When a new download is sorted you'll get a toast notification.

----------------------------------------------------------
START AT LOGIN (optional)
----------------------------------------------------------
After building (Option A), double-click  install_startup_windows.bat
To undo: press Win+R, type  shell:startup  and delete the shortcut.

----------------------------------------------------------
WHERE IT KEEPS ITS DATA
----------------------------------------------------------
Your editable config + history + logs live in:
  %LOCALAPPDATA%\Download Organizer\
(The config.json there is the one "Edit Config" opens.)

----------------------------------------------------------
NOTES
----------------------------------------------------------
- This is the same engine as the Mac version, so both machines sort
  files the same way.
- Windows SmartScreen may warn the first time you run an unsigned .exe:
  click "More info" -> "Run anyway".
==========================================================
