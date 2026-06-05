#!/usr/bin/env python3
"""Download Organizer - Windows edition.

Same engine as the macOS app (organizer.py), but the UI is a Windows
system-tray icon instead of a macOS menu-bar item. The dashboard opens in the
default browser (served by the same local HTTP server), and notifications use
native Windows toast balloons via pystray.

Run from source:
    pip install -r requirements-windows.txt
    pythonw organizer_win.py

Build a standalone .exe (run on Windows):
    build_windows.bat            ->  dist\\Download Organizer.exe
"""
import os
import sys
import queue
import threading
import webbrowser

# Reuse the shared engine. organizer.py keeps every macOS-specific call inside
# functions, so importing it on Windows only runs cross-platform setup.
import organizer as core

from PIL import Image
import pystray
from pystray import MenuItem as Item


def _load_icon():
    """Load the tray icon image. Prefer the bundled .ico, fall back to .png,
    then to a plain generated square so the tray always has something."""
    here = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    for name in ("appicon.ico", "appicon_source.png", "appicon.png"):
        p = os.path.join(here, name)
        if os.path.exists(p):
            try:
                return Image.open(p)
            except Exception:
                pass
    return Image.new("RGBA", (64, 64), (124, 92, 255, 255))


class WinApp:
    def __init__(self):
        self.cfg = core.load_config()
        core.load_recent()
        self.watching = True
        self.events = queue.Queue()
        self.watcher = core.Watcher(self.cfg, self.events)

        # Wire engine -> Windows toast notifications.
        core.NOTIFY_HOOK[0] = self._toast

        # Expose engine actions to the dashboard HTTP API.
        core.CTX["cfg"] = self.cfg
        core.CTX["state"] = lambda: core.build_state(self.cfg, self.watching)
        core.CTX["organize"] = self._organize_now
        core.CTX["toggle"] = self._toggle
        core.CTX["restart"] = self._restart
        core.CTX["show"] = self._open_dashboard

        self.icon = pystray.Icon(
            "download_organizer",
            _load_icon(),
            "Download Organizer",
            menu=self._build_menu(),
        )

    # ---- notifications ----
    def _toast(self, title, subtitle, msg):
        body = f"{subtitle}\n{msg}" if subtitle else msg
        try:
            self.icon.notify(body, title)
        except Exception as e:
            core.log(f"toast failed: {e}")

    # ---- menu ----
    def _build_menu(self):
        return pystray.Menu(
            Item("Open Dashboard", self._open_dashboard, default=True),
            Item("Organize Now", self._organize_now_menu),
            Item(
                lambda _i: "Pause Watching" if self.watching else "Resume Watching",
                self._toggle_menu,
            ),
            Item(
                "Ask before sorting",
                self._toggle_mode_menu,
                checked=lambda _i: self.cfg.get("sort_mode", "auto") == "ask",
            ),
            Item("Restart Service", self._restart_menu),
            Item("Open Downloads", self._open_downloads),
            Item("Edit Config", self._edit_config),
            pystray.Menu.SEPARATOR,
            Item("Check for Updates", self._check_updates_menu),
            Item("Quit", self._quit),
        )

    # ---- actions ----
    def _open_dashboard(self, *_):
        url = f"http://127.0.0.1:{core.SERVER_PORT[0]}/"
        webbrowser.open(url)

    def _organize_now(self):
        summary = core.organize_all(self.cfg, fresh_only=False)
        return sum(summary.values())

    def _organize_now_menu(self, *_):
        moved = self._organize_now()
        self._toast("Download Organizer", "", f"Organized {moved} file(s).")

    def _toggle(self):
        # Called from the dashboard HTTP thread or the tray menu.
        if self.watching:
            self.watcher.stop()
            self.watching = False
        else:
            self.watcher.start()
            self.watching = True
        self.icon.update_menu()
        return self.watching

    def _toggle_menu(self, *_):
        self._toggle()

    def _restart(self):
        """Stop the watcher, reload config.json, start it again."""
        if self.watching:
            self.watcher.stop()
        core.reload_config_into(self.cfg)
        self.watcher.start()
        self.watching = True
        self.icon.update_menu()
        self._toast("Download Organizer", "Service restarted",
                    "Watching Downloads (config reloaded).")
        return True

    def _restart_menu(self, *_):
        self._restart()

    def _toggle_mode_menu(self, *_):
        new = "auto" if self.cfg.get("sort_mode", "auto") == "ask" else "ask"
        core.set_mode(self.cfg, new)
        self.icon.update_menu()
        self._toast("Download Organizer", "Sort mode",
                    "Ask before sorting new downloads" if new == "ask"
                    else "Auto-sorting new downloads")

    def _check_updates_menu(self, *_):
        def worker():
            d = core.check_update(force=True)
            if d.get("available"):
                self._toast("Download Organizer",
                            f"Update available — {d['latest']}",
                            f"Downloading {d.get('name') or 'the latest release'}…")
                core.open_update()
            elif d.get("error"):
                self._toast("Download Organizer", "Update check failed", d["error"])
            else:
                self._toast("Download Organizer", "You're up to date",
                            f"Version {d['current']} is the latest.")
        threading.Thread(target=worker, daemon=True).start()

    def _startup_update_check(self):
        d = core.check_update()
        if d.get("available"):
            self._toast("Download Organizer",
                        f"Update available — {d['latest']}",
                        "Tray menu → Check for Updates to download.")

    def _open_downloads(self, *_):
        os.startfile(self.cfg["downloads_dir"])  # noqa: Windows-only API

    def _edit_config(self, *_):
        os.startfile(str(core.CONFIG_PATH))  # opens in default editor

    def _quit(self, *_):
        try:
            self.watcher.stop()
        finally:
            self.icon.stop()

    # ---- lifecycle ----
    def _drain_events(self):
        # The watcher pushes (name, category) tuples for UI consumption; the
        # dashboard reads live state over HTTP instead, so just keep the queue
        # from growing. Toasts are fired separately via the notify hook.
        while True:
            try:
                self.events.get(timeout=60)
            except queue.Empty:
                pass

    def run(self):
        threading.Thread(target=self._drain_events, daemon=True).start()
        threading.Thread(target=self._startup_update_check, daemon=True).start()
        self.watcher.start()
        core.start_server()
        if self.cfg.get("open_dashboard_on_start"):
            # give the server a beat to bind before opening the browser
            threading.Timer(0.6, self._open_dashboard).start()
        self.icon.run()  # blocks on the tray event loop


def main():
    # Single-instance guard: if a copy is already running, just tell it to
    # surface the dashboard and exit.
    alive = core.instance_alive()
    if alive:
        core.request_show_remote(alive)
        return
    WinApp().run()


if __name__ == "__main__":
    if "--once" in sys.argv:
        cfg = core.load_config()
        summary = core.organize_all(cfg, fresh_only=False)
        print("organized:", sum(summary.values()) or "nothing")
    else:
        main()
