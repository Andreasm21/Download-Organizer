# 📥 Download Organizer

Auto-sorts your **Downloads** folder into tidy category subfolders the moment
files land. Runs quietly in the background (macOS **menu bar** / Windows
**system tray**) with a modern dashboard, desktop notifications, and one-click
controls.

The same sorting engine powers both platforms, so your Mac and PC organize
files identically.

---

## ✨ Features

- **Instant sorting** — watches Downloads and moves each new file into the right
  subfolder (Media, Documents, Software, Archives, 3D-Models, Fonts, Dev, …).
- **Modern dashboard** — see what went where, with quick-open / reveal buttons.
  Opens in a native window (macOS) or your browser (Windows).
- **Notifications** — a banner pops up each time a file is sorted.
- **Restart Service** — reloads your rules and restarts the watcher (dashboard
  button + menu item).
- **Safe by default** — `_Sensitive`, `NFT`, and already-sorted folders are
  never touched.
- **Configurable** — all rules live in `config.json` (edit via the menu).

---

## 🍎 macOS

**Run from source**

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install rumps pyobjc watchdog
./.venv/bin/python organizer.py
```

**Build a standalone `.app`** (bundles Python + deps):

```bash
./.venv/bin/python -m pip install py2app
./.venv/bin/python setup.py py2app
# -> dist/Download Organizer.app
```

It runs in the **menu bar** (top-right). First launch of a downloaded build:
right-click the app → **Open** → **Open** (Gatekeeper).

---

## 🪟 Windows

Install **Python 3.10+** from [python.org](https://www.python.org/downloads/)
and tick *“Add Python to PATH”*.

**Build a single `.exe`:** double-click `build_windows.bat`
→ produces `dist\Download Organizer.exe`.

**Or just run it:** double-click `run_windows.bat`.

**Start at login (optional):** `install_startup_windows.bat`.

It runs in the **system tray** (bottom-right). Right-click for the menu,
left-click opens the dashboard. SmartScreen may warn on first run →
**More info** → **Run anyway**. Full details in
[`WINDOWS-README.txt`](WINDOWS-README.txt).

---

## ⚙️ Configuration

`config.json` maps file extensions to category folders and lists folders to
never touch. Edit it directly or via **Edit Config** in the menu, then hit
**Restart Service** to apply.

Writable data (your edited config, history, logs) lives in a per-user dir for
packaged builds:

- macOS: `~/Library/Application Support/Download Organizer/`
- Windows: `%LOCALAPPDATA%\Download Organizer\`

---

## 🧩 Project layout

| File | Purpose |
|------|---------|
| `organizer.py` | Shared engine + macOS menu-bar app |
| `organizer_win.py` | Windows system-tray app |
| `dashboard.html` | The dashboard UI (served on `127.0.0.1`) |
| `config.json` | Category rules |
| `setup.py` | py2app build (macOS) |
| `build_windows.bat` | PyInstaller build (Windows) |
| `make_icon.py` | Icon generator |
