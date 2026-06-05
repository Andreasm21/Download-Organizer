"""py2app build script for Download Organizer.

Build a self-contained, distributable macOS .app (bundles Python + all deps):

    ./.venv/bin/python setup.py py2app

Output: dist/Download Organizer.app  (no external venv/workspace needed)
"""
from setuptools import setup

APP = ["organizer.py"]
DATA_FILES = ["dashboard.html", "config.json"]
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "appicon.icns",
    "plist": {
        "CFBundleName": "Download Organizer",
        "CFBundleDisplayName": "Download Organizer",
        "CFBundleIdentifier": "ai.openclaw.download-organizer",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,  # menu-bar accessory: no Dock icon by default
        "LSMinimumSystemVersion": "11.0",
        "NSHumanReadableCopyright": "Download Organizer",
    },
    "packages": ["rumps", "objc", "AppKit", "WebKit", "Foundation",
                 "Quartz", "watchdog"],
    "includes": ["queue", "http.server", "urllib.request"],
}

setup(
    app=APP,
    name="Download Organizer",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
