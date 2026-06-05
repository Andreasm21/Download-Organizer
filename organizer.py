#!/usr/bin/env python3
"""Download Organizer - macOS menu-bar app that auto-sorts ~/Downloads into
category subfolders the moment files land (and on demand).

Run modes:
  python organizer.py            launch the menu-bar app
  python organizer.py --once     organize everything once, then exit (headless)
  python organizer.py --watch    headless watch (no menu bar), for debugging

Categorization is rule-based and config-driven (config.json). Files whose type
isn't recognised go to the unknown folder; _Sensitive / NFT are never touched.
"""
import os, sys, json, time, shutil, threading, queue, datetime, subprocess
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

FROZEN = bool(getattr(sys, "frozen", False))

APP_VERSION = "1.2.0"                       # bumped at release time
GITHUB_REPO = "Andreasm21/Download-Organizer"


def _platform_data_dir():
    """Per-user writable data dir for a distributed (frozen) build."""
    if sys.platform == "darwin":
        return Path(os.path.expanduser("~/Library/Application Support/Download Organizer"))
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return Path(base) / "Download Organizer"
    return Path(os.path.expanduser("~/.local/share/Download Organizer"))


if FROZEN:
    # Standalone build: read-only files are bundled, writable data goes to a
    # per-user dir so the app works from any location (emailed, /Applications,
    # Program Files, Downloads, ...).
    if hasattr(sys, "_MEIPASS"):
        RES_DIR = Path(sys._MEIPASS)                       # PyInstaller (Windows/Linux)
    else:
        RES_DIR = Path(sys.executable).resolve().parent.parent / "Resources"  # py2app (.app)
    DATA_DIR = _platform_data_dir()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DASHBOARD_HTML = RES_DIR / "dashboard.html"
    DEFAULT_CONFIG = RES_DIR / "config.json"
    CONFIG_PATH = DATA_DIR / "config.json"
    LOG_PATH = DATA_DIR / "activity.log"
    STATE_PATH = DATA_DIR / "state.json"
    PORT_FILE = DATA_DIR / ".dash_port"
    if not CONFIG_PATH.exists():
        try:
            shutil.copyfile(DEFAULT_CONFIG, CONFIG_PATH)
        except Exception:
            pass
else:
    # Dev mode: everything sits next to the script (workspace layout).
    APP_DIR = Path(__file__).resolve().parent
    CONFIG_PATH = APP_DIR / "config.json"
    LOG_PATH = APP_DIR / "activity.log"
    STATE_PATH = APP_DIR / "state.json"
    PORT_FILE = APP_DIR / ".dash_port"
    DASHBOARD_HTML = APP_DIR / "dashboard.html"

# ----------------------------- persistent recent state -----------------------------
RECENT = []                 # newest first: {name, cat, dest, ts}
TOTAL = [0]                 # all-time sorted counter
KEPT = set()                # paths the user chose to keep at the top level
RECENT_LOCK = threading.Lock()


def load_recent():
    try:
        d = json.loads(STATE_PATH.read_text())
        RECENT[:] = d.get("recent", [])[:200]
        TOTAL[0] = int(d.get("total", 0))
        KEPT.clear()
        KEPT.update(d.get("kept", []))
    except Exception:
        pass


def _save_state():
    try:
        STATE_PATH.write_text(json.dumps({
            "total": TOTAL[0], "recent": RECENT[:200], "kept": sorted(KEPT),
        }))
    except OSError:
        pass


def record_sort(name, cat, dest):
    with RECENT_LOCK:
        RECENT.insert(0, {
            "name": name, "cat": cat, "dest": dest,
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        })
        del RECENT[200:]
        TOTAL[0] += 1
        _save_state()


# ----------------------------- config / engine -----------------------------
def load_config():
    cfg = json.loads(CONFIG_PATH.read_text())
    cfg["downloads_dir"] = os.path.expanduser(cfg["downloads_dir"])
    # build a fast extension -> category lookup
    ext2cat = {}
    for cat, exts in cfg["categories"].items():
        for e in exts:
            ext2cat[e.lower()] = cat
    cfg["_ext2cat"] = ext2cat
    cfg["_temp"] = {e.lower() for e in cfg.get("temp_extensions", [])}
    cfg["_ignore"] = set(cfg.get("ignore_names", []))
    cfg["_never"] = set(cfg.get("never_touch", []))
    return cfg


def reload_config_into(cfg):
    """Re-read config.json and update the shared cfg dict IN PLACE, so every
    reference (watcher, dashboard state, menus) sees the new settings without
    being rebound. Used by the Restart action."""
    fresh = load_config()
    cfg.clear()
    cfg.update(fresh)
    return cfg


def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


# A platform front-end (e.g. the Windows tray icon) can register a notifier here:
#   NOTIFY_HOOK[0] = lambda title, subtitle, msg: ...
# When set, it takes precedence over the built-in macOS osascript banner.
NOTIFY_HOOK = [None]


def notify(title, subtitle, msg, cfg=None):
    """Show a desktop notification.

    macOS: native banner via osascript (works from launchd/headless, unlike
    rumps.notification which needs a fully-bundled signed app).
    Other platforms: delegate to NOTIFY_HOOK if a front-end registered one
    (the Windows build wires this to the system-tray toast)."""
    if cfg is not None and not cfg.get("notify", True):
        return

    hook = NOTIFY_HOOK[0]
    if hook is not None:
        try:
            hook(title, subtitle, msg)
        except Exception as e:
            log(f"notify hook failed: {e}")
        return

    if sys.platform != "darwin":
        return  # no built-in notifier off macOS; rely on the hook

    def esc(s):
        return str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

    parts = [f'display notification "{esc(msg)}"', f'with title "{esc(title)}"']
    if subtitle:
        parts.append(f'subtitle "{esc(subtitle)}"')
    try:
        subprocess.Popen(["osascript", "-e", " ".join(parts)])
    except Exception as e:
        log(f"notify failed: {e}")


def category_for(name, cfg):
    """Return target category folder for a filename, or the unknown folder."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return cfg["_ext2cat"].get(ext, cfg["unknown_folder"])


def is_candidate(name, cfg):
    """True if a top-level entry name is a sortable file (not temp/ignored)."""
    if name.startswith("."):
        return False
    if name in cfg["_ignore"]:
        return False
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in cfg["_temp"]:
        return False
    return True


def safe_move(src: Path, dest_dir: Path):
    """Move src into dest_dir, renaming on collision. Returns final Path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / src.name
    if target.exists():
        stem, suf = src.stem, src.suffix
        n = 1
        while target.exists():
            target = dest_dir / f"{stem} ({n}){suf}"
            n += 1
    shutil.move(str(src), str(target))
    return target


def organize_file(path: Path, cfg):
    """Sort one file. Returns (category, final_path) or None if skipped."""
    name = path.name
    if not path.is_file() or not is_candidate(name, cfg):
        return None
    cat = category_for(name, cfg)
    final = safe_move(path, Path(cfg["downloads_dir"]) / cat)
    log(f"sorted  {name}  ->  {cat}/")
    record_sort(name, cat, str(final))
    return cat, final


def settle(path: Path, cfg, tries=20):
    """Wait until a file stops growing (download finished). False if it vanished."""
    secs = cfg.get("settle_seconds", 2)
    last = -1
    for _ in range(tries):
        if not path.exists():
            return False
        try:
            sz = path.stat().st_size
        except OSError:
            return False
        if sz == last:
            return True
        last = sz
        time.sleep(secs)
    return True


def organize_all(cfg, fresh_only=False, max_age=720):
    """Sweep every sortable top-level file. Returns dict {category: count}."""
    dl = Path(cfg["downloads_dir"])
    now = time.time()
    summary = {}
    for entry in sorted(dl.iterdir()):
        if entry.is_dir():
            continue
        if entry.name in cfg["_never"]:
            continue
        if not is_candidate(entry.name, cfg):
            continue
        if fresh_only and (now - entry.stat().st_mtime) > max_age:
            continue
        res = organize_file(entry, cfg)
        if res:
            summary[res[0]] = summary.get(res[0], 0) + 1
    return summary


# ----------------------------- watcher -----------------------------
class Watcher:
    """FSEvents-backed watcher; settles files then sorts them. Sorted results
    are pushed to `events` queue for the UI to consume."""
    def __init__(self, cfg, events: queue.Queue):
        self.cfg = cfg
        self.events = events
        self._observer = None
        self._pending = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def _on_fs_event(self, src_path):
        name = os.path.basename(src_path)
        if not is_candidate(name, self.cfg):
            return
        parent = os.path.dirname(src_path)
        if os.path.abspath(parent) != os.path.abspath(self.cfg["downloads_dir"]):
            return  # only top-level of Downloads
        with self._lock:
            self._pending[src_path] = time.time()

    def _settle_loop(self):
        while not self._stop.is_set():
            time.sleep(1)
            with self._lock:
                paths = list(self._pending.keys())
            for p in paths:
                pp = Path(p)
                if not pp.exists():
                    with self._lock:
                        self._pending.pop(p, None)
                    continue
                if settle(pp, self.cfg):
                    with self._lock:
                        self._pending.pop(p, None)
                    if self.cfg.get("sort_mode", "auto") == "ask":
                        # Hold for a decision: leave the file in place, just
                        # surface it as pending and ping the user.
                        cat = category_for(pp.name, self.cfg)
                        self.events.put((pp.name, f"pending:{cat}"))
                        notify("📥 New download", pp.name,
                               f"Open the dashboard to sort to {cat}/ or keep it.",
                               self.cfg)
                        continue
                    res = None
                    try:
                        res = organize_file(pp, self.cfg)
                    except Exception as e:
                        log(f"ERROR sorting {pp.name}: {e}")
                    if res:
                        self.events.put((pp.name, res[0]))
                        notify("📥 Download sorted", pp.name,
                               f"Moved to {res[0]}/", self.cfg)

    def start(self):
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        self._stop.clear()  # allow a fresh settle loop after a prior stop()
        outer = self

        class H(FileSystemEventHandler):
            def on_created(self, e):
                if not e.is_directory:
                    outer._on_fs_event(e.src_path)

            def on_moved(self, e):
                if not e.is_directory:
                    outer._on_fs_event(e.dest_path)

        self._observer = Observer()
        self._observer.schedule(H(), self.cfg["downloads_dir"], recursive=False)
        self._observer.start()
        threading.Thread(target=self._settle_loop, daemon=True).start()
        log("watcher started")

    def stop(self):
        self._stop.set()
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None
        log("watcher stopped")


# ----------------------------- dashboard state + server -----------------------------
CTX = {}  # filled in by run_app: cfg, state(), organize(), toggle()


def build_state(cfg, watching):
    dl = Path(cfg["downloads_dir"])
    home = os.path.expanduser("~")
    folders = []
    seen = set()
    for nm in list(cfg["categories"].keys()) + [cfg["unknown_folder"]]:
        if nm in seen:
            continue
        seen.add(nm)
        fp = dl / nm
        if fp.is_dir():
            try:
                cnt = sum(1 for x in fp.iterdir() if x.is_file() and not x.name.startswith("."))
            except OSError:
                cnt = 0
            folders.append({"name": nm, "path": str(fp), "count": cnt})
    folders.sort(key=lambda f: -f["count"])
    organized_existing = any(f["count"] > 0 for f in folders)

    pending_list = build_pending(cfg)
    pending = len(pending_list)

    with RECENT_LOCK:
        recent = [dict(r) for r in RECENT[:60]]
        total = TOTAL[0]
    today = datetime.date.today().isoformat()
    sorted_today = sum(1 for r in recent if r.get("ts", "")[:10] == today)

    return {
        "watching": watching,
        "downloads_dir": str(dl),
        "downloads_pretty": str(dl).replace(home, "~", 1),
        "config_path": str(CONFIG_PATH),
        "log_path": str(LOG_PATH),
        "recent": recent,
        "folders": folders,
        "pending": pending,
        "pending_list": pending_list,
        "sort_mode": cfg.get("sort_mode", "auto"),
        "sorted_total": total,
        "sorted_today": sorted_today,
        "decider_unlocked": total > 0 or organized_existing,
    }


def _dir_size(p: Path):
    total = 0
    for dp, _, fns in os.walk(p):
        for f in fns:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def move_to_trash(path: Path):
    """Move a file/folder to the OS Trash/Recycle Bin (recoverable).
    Prefers send2trash (cross-platform); falls back to ~/.Trash on macOS."""
    try:
        from send2trash import send2trash
        send2trash(str(path))
        return True
    except Exception:
        pass
    if sys.platform == "darwin":
        try:
            trash = Path(os.path.expanduser("~/.Trash"))
            trash.mkdir(exist_ok=True)
            target = trash / path.name
            n = 1
            while target.exists():
                if path.is_file():
                    target = trash / f"{path.stem} ({n}){path.suffix}"
                else:
                    target = trash / f"{path.name} ({n})"
                n += 1
            shutil.move(str(path), str(target))
            return True
        except Exception as e:
            log(f"trash fallback failed: {e}")
    return False


def _known_folders(cfg):
    return set(cfg["categories"].keys()) | {cfg["unknown_folder"]}


def decider_list(cfg, cat):
    """List entries inside one category folder as swipe cards (biggest first).
    `cat` must be a known category folder (guards against arbitrary paths)."""
    if cat not in _known_folders(cfg):
        return []
    folder = Path(cfg["downloads_dir"]) / cat
    if not folder.is_dir():
        return []
    items = []
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    for e in entries:
        if e.name.startswith("."):
            continue
        try:
            size = e.stat().st_size if e.is_file() else _dir_size(e)
        except OSError:
            size = 0
        items.append({
            "name": e.name, "path": str(e), "size": size,
            "cat": cat, "dir": e.is_dir(),
        })
    items.sort(key=lambda x: -x["size"])
    return items


def decider_trash(cfg, paths):
    """Move the given paths to Trash. Only paths inside downloads_dir are
    accepted. Returns {trashed, freed, errors}."""
    dl = Path(cfg["downloads_dir"]).resolve()
    freed = 0
    n = 0
    errors = []
    for p in paths:
        try:
            pp = Path(p).resolve()
        except Exception:
            continue
        if dl not in pp.parents:      # must live under ~/Downloads
            continue
        if not pp.exists():
            continue
        try:
            size = pp.stat().st_size if pp.is_file() else _dir_size(pp)
        except OSError:
            size = 0
        if move_to_trash(pp):
            freed += size
            n += 1
            log(f"trashed  {pp.name}  ({size} bytes)")
        else:
            errors.append(pp.name)
    return {"trashed": n, "freed": freed, "errors": errors}


# ----------------------------- ask-before-sort (pending decisions) -----------------------------
def set_mode(cfg, mode):
    """Persist the sort mode ('auto' or 'ask') to config.json and cfg in place."""
    mode = "ask" if mode == "ask" else "auto"
    try:
        raw = json.loads(CONFIG_PATH.read_text())
        raw["sort_mode"] = mode
        CONFIG_PATH.write_text(json.dumps(raw, indent=2))
    except Exception as e:
        log(f"set_mode write failed: {e}")
    cfg["sort_mode"] = mode
    return mode


def build_pending(cfg):
    """Top-level files awaiting a decision (everything sortable not kept)."""
    dl = Path(cfg["downloads_dir"])
    items = []
    try:
        entries = list(dl.iterdir())
    except OSError:
        return items
    for e in entries:
        if not e.is_file() or e.name in cfg["_never"]:
            continue
        if not is_candidate(e.name, cfg):
            continue
        try:
            if str(e.resolve()) in KEPT:
                continue
            stat = e.stat()
        except OSError:
            continue
        items.append({"name": e.name, "path": str(e), "size": stat.st_size,
                      "cat": category_for(e.name, cfg), "ts": stat.st_mtime})
    items.sort(key=lambda x: -x["ts"])  # newest first
    return items


def pending_sort(cfg, path, cat=None):
    """Sort one held file into a category (suggested unless overridden)."""
    pp = Path(path)
    dl = Path(cfg["downloads_dir"]).resolve()
    try:
        rp = pp.resolve()
    except Exception:
        return {"ok": False}
    if rp.parent != dl or not pp.is_file():
        return {"ok": False}
    cat = cat or category_for(pp.name, cfg)
    final = safe_move(pp, dl / cat)
    log(f"sorted (ask)  {pp.name}  ->  {cat}/")
    KEPT.discard(str(rp))
    record_sort(pp.name, cat, str(final))   # also persists KEPT
    return {"ok": True, "cat": cat, "dest": str(final)}


def pending_keep(cfg, path):
    """Mark a file to stay in Downloads (stop showing it as pending)."""
    dl = Path(cfg["downloads_dir"]).resolve()
    try:
        rp = Path(path).resolve()
    except Exception:
        return {"ok": False}
    if rp.parent != dl:
        return {"ok": False}
    KEPT.add(str(rp))
    with RECENT_LOCK:
        _save_state()
    return {"ok": True}


def pending_sort_all(cfg):
    moved = 0
    for it in build_pending(cfg):
        if pending_sort(cfg, it["path"], it["cat"]).get("ok"):
            moved += 1
    return moved


def search_downloads(cfg, q, limit=300):
    """Recursively search every file under Downloads by name (case-insensitive)."""
    q = (q or "").strip().lower()
    if not q:
        return []
    dl = Path(cfg["downloads_dir"])
    out = []
    for dp, dirs, files in os.walk(dl):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.startswith(".") or q not in f.lower():
                continue
            full = os.path.join(dp, f)
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            rel = os.path.relpath(dp, dl)
            out.append({"name": f, "path": full, "size": size,
                        "folder": "" if rel == "." else rel})
            if len(out) >= limit:
                out.sort(key=lambda x: -x["size"])
                return out
    out.sort(key=lambda x: -x["size"])
    return out


# ----------------------------- self-update (check + fetch from GitHub) -----------------------------
_UPDATE_CACHE = {"ts": 0.0, "data": None}
UPDATE_TTL = 6 * 3600  # don't hammer the GitHub API


def _ver_tuple(s):
    """'v1.2.0' -> (1,2,0); robust to junk so comparison never throws."""
    parts = []
    for chunk in (s or "").lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _os_asset(assets):
    """Pick the release asset matching this OS: .dmg (mac), .exe (win), .zip (else)."""
    if sys.platform == "darwin":
        suffix = ".dmg"
    elif sys.platform.startswith("win"):
        suffix = ".exe"
    else:
        suffix = ".zip"
    for a in assets:
        name = (a.get("name") or "").lower()
        if name.endswith(suffix):
            return a.get("name"), a.get("browser_download_url")
    return None, None


def check_update(force=False):
    """Query GitHub for the latest release and pick the asset for this OS.
    Returns {available, current, latest, name, url, page, error}. Cached."""
    now = time.time()
    if (not force and _UPDATE_CACHE["data"] is not None
            and now - _UPDATE_CACHE["ts"] < UPDATE_TTL):
        return _UPDATE_CACHE["data"]
    data = {"available": False, "current": APP_VERSION, "latest": None,
            "name": None, "url": None, "page": None, "error": None}
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "DownloadOrganizer"})
        with urllib.request.urlopen(req, timeout=6) as r:
            rel = json.loads(r.read())
        latest = rel.get("tag_name") or rel.get("name")
        data["latest"] = latest
        data["page"] = rel.get("html_url")
        data["name"], data["url"] = _os_asset(rel.get("assets") or [])
        data["available"] = _ver_tuple(latest) > _ver_tuple(APP_VERSION)
    except Exception as e:
        data["error"] = str(e)
    _UPDATE_CACHE.update(ts=now, data=data)
    return data


def open_update(prefer_asset=True):
    """Open the OS-specific download (or the release page) in the browser."""
    d = check_update()
    target = (d.get("url") if prefer_asset else None) or d.get("page")
    if not target:
        target = f"https://github.com/{GITHUB_REPO}/releases/latest"
    _open_url(target)
    return target


def _open_url(url):
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", url])
        elif sys.platform.startswith("win"):
            os.startfile(url)  # noqa: B606 (Windows-only)
        else:
            subprocess.Popen(["xdg-open", url])
    except Exception as e:
        log(f"open url failed: {e}")


def _open_path(body):
    p = body.get("path", "")
    if not p:
        return
    if body.get("reveal"):
        args = ["open", "-R", p]
    elif body.get("text"):
        args = ["open", "-t", p]
    else:
        args = ["open", p]
    try:
        subprocess.Popen(args)
    except Exception as e:
        log(f"open failed: {e}")


class DashHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                return self._send(200, DASHBOARD_HTML.read_bytes(), "text/html; charset=utf-8")
            except OSError:
                return self._send(500, b"dashboard.html missing", "text/plain")
        if self.path == "/api/state":
            return self._send(200, json.dumps(CTX["state"]()))
        if self.path.startswith("/api/decider/list"):
            from urllib.parse import urlparse, parse_qs, unquote
            q = parse_qs(urlparse(self.path).query)
            cat = unquote((q.get("cat") or [""])[0])
            return self._send(200, json.dumps(decider_list(CTX["cfg"], cat)))
        if self.path == "/api/update/check":
            return self._send(200, json.dumps(check_update()))
        if self.path.startswith("/api/search"):
            from urllib.parse import urlparse, parse_qs, unquote
            q = parse_qs(urlparse(self.path).query)
            term = unquote((q.get("q") or [""])[0])
            return self._send(200, json.dumps(search_downloads(CTX["cfg"], term)))
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        ln = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(ln) if ln else b""
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {}
        if self.path == "/api/organize":
            return self._send(200, json.dumps({"moved": CTX["organize"]()}))
        if self.path == "/api/toggle":
            return self._send(200, json.dumps({"watching": CTX["toggle"]()}))
        if self.path == "/api/restart":
            CTX["restart"]()
            return self._send(200, b'{"ok":true}')
        if self.path == "/api/decider/trash":
            res = decider_trash(CTX["cfg"], body.get("paths") or [])
            return self._send(200, json.dumps(res))
        if self.path == "/api/update/open":
            target = open_update(prefer_asset=bool(body.get("asset", True)))
            return self._send(200, json.dumps({"opened": target}))
        if self.path == "/api/pending/sort":
            return self._send(200, json.dumps(
                pending_sort(CTX["cfg"], body.get("path", ""), body.get("cat"))))
        if self.path == "/api/pending/keep":
            return self._send(200, json.dumps(
                pending_keep(CTX["cfg"], body.get("path", ""))))
        if self.path == "/api/pending/sortall":
            return self._send(200, json.dumps({"moved": pending_sort_all(CTX["cfg"])}))
        if self.path == "/api/mode":
            return self._send(200, json.dumps({"mode": set_mode(CTX["cfg"], body.get("mode", "auto"))}))
        if self.path == "/api/open":
            _open_path(body)
            return self._send(200, b'{"ok":true}')
        if self.path == "/api/show":
            CTX["show"]()
            return self._send(200, b'{"ok":true}')
        self._send(404, b'{"error":"not found"}')


SERVER_PORT = [0]
_DASH = {"win": None}  # single native dashboard window, reused


def start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), DashHandler)
    port = srv.server_address[1]
    SERVER_PORT[0] = port
    try:
        PORT_FILE.write_text(str(port))
    except OSError:
        pass
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"dashboard server on http://127.0.0.1:{port}")
    return port


def open_or_focus_dashboard():
    """Open (or re-focus) the dashboard as a NATIVE window inside this process,
    so it belongs to the official app bundle — no separate 'Python' process.
    Must be called on the main thread."""
    try:
        from AppKit import (NSWindow, NSBackingStoreBuffered, NSApp,
                            NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
                            NSWindowStyleMaskResizable, NSWindowStyleMaskMiniaturizable,
                            NSViewWidthSizable, NSViewHeightSizable)
        from WebKit import WKWebView, WKWebViewConfiguration
        from Foundation import NSURL, NSURLRequest, NSMakeRect
    except Exception as e:
        log(f"native window unavailable: {e}")
        return

    if _DASH["win"] is not None:
        _DASH["win"].makeKeyAndOrderFront_(None)
        try:
            NSApp.activateIgnoringOtherApps_(True)
        except Exception:
            pass
        return

    url = f"http://127.0.0.1:{SERVER_PORT[0]}/"
    rect = NSMakeRect(0, 0, 940, 660)
    style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
             | NSWindowStyleMaskResizable | NSWindowStyleMaskMiniaturizable)
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, style, NSBackingStoreBuffered, False)
    win.setTitle_("Download Organizer")
    win.setReleasedWhenClosed_(False)
    win.setMinSize_((700, 540))

    conf = WKWebViewConfiguration.alloc().init()
    wv = WKWebView.alloc().initWithFrame_configuration_(rect, conf)
    wv.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
    wv.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(url)))
    win.setContentView_(wv)
    win.center()
    win.makeKeyAndOrderFront_(None)
    try:
        NSApp.activateIgnoringOtherApps_(True)
    except Exception:
        pass
    _DASH["win"] = win


def instance_alive():
    """Return the port of an already-running instance, or None. Lets a second
    launch (e.g. clicking the Dock icon) just reopen the dashboard window."""
    try:
        port = PORT_FILE.read_text().strip()
        if not port:
            return None
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=0.4).read()
        return port
    except Exception:
        return None


def request_show_remote(port):
    """Tell an already-running instance to bring its dashboard to the front."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/show", method="POST")
        urllib.request.urlopen(req, timeout=1).read()
    except Exception:
        pass


# ----------------------------- menu-bar app -----------------------------
def run_app():
    # If another instance is already running, tell it to show its dashboard and
    # exit immediately (so clicking the Dock icon focuses the existing app
    # instead of spawning a duplicate process).
    alive = instance_alive()
    if alive:
        request_show_remote(alive)
        return

    # The launcher execs the framework interpreter, so mainBundle resolves to
    # "Python.app" and our LSUIElement flag is ignored. Relabel the in-memory
    # bundle name so the menu bar reads "Download Organizer" instead of "Python".
    try:
        from Foundation import NSBundle as _NSB
        _info = _NSB.mainBundle().infoDictionary()
        if _info is not None:
            _info["CFBundleName"] = "Download Organizer"
    except Exception:
        pass

    import rumps

    cfg = load_config()
    load_recent()
    events: queue.Queue = queue.Queue()
    watcher = Watcher(cfg, events)

    class DownloadOrganizer(rumps.App):
        def __init__(self):
            super().__init__("📥", quit_button=None)
            self.recent = []
            self.watching = False
            self._toggle_req = False
            self._restart_req = False
            self._show_req = bool(cfg.get("open_dashboard_on_start"))
            self._setup_done = False
            self.status_item = rumps.MenuItem("Status: starting…")
            self.toggle_item = rumps.MenuItem("Pause Watching", callback=self.toggle)
            self.mode_item = rumps.MenuItem("Ask before sorting", callback=self.toggle_mode)
            self.mode_item.state = 1 if cfg.get("sort_mode", "auto") == "ask" else 0
            self.recent_menu = rumps.MenuItem("Recent")
            # Populate the submenu inline so its underlying NSMenu is created;
            # calling .clear()/.add() on an empty submenu raises (NSMenu is None).
            self.recent_menu.add(rumps.MenuItem("(nothing sorted yet)"))
            self.menu = [
                rumps.MenuItem("Open Dashboard", callback=self.open_dashboard, key="d"),
                self.status_item,
                self.toggle_item,
                self.mode_item,
                rumps.MenuItem("Organize Now", callback=self.organize_now),
                rumps.MenuItem("Restart Service", callback=self.restart_now, key="r"),
                None,
                self.recent_menu,
                None,
                rumps.MenuItem("Open Downloads", callback=self.open_downloads),
                rumps.MenuItem("Edit Categories…", callback=self.edit_config),
                rumps.MenuItem("Open Activity Log", callback=self.open_log),
                None,
                rumps.MenuItem("Check for Updates…", callback=self.check_updates),
                rumps.MenuItem("Quit", callback=self.quit_app),
            ]

            threading.Thread(target=self._startup_update_check, daemon=True).start()
            if cfg.get("organize_on_start"):
                threading.Thread(target=self._startup_sweep, daemon=True).start()
            if cfg.get("watch_on_start", True):
                self.start_watching()
            else:
                self.status_item.title = "Status: paused"

            rumps.Timer(self.drain, 1).start()

        # ---- helpers ----
        def _set_recent_placeholder(self):
            self.recent_menu.clear()
            self.recent_menu.add(rumps.MenuItem("(nothing sorted yet)"))

        def _startup_sweep(self):
            summary = organize_all(cfg, fresh_only=False)
            if summary:
                for cat, n in summary.items():
                    for _ in range(n):
                        events.put(("(startup sweep)", cat))
                self._notify("Organized existing files",
                             ", ".join(f"{n}->{c}" for c, n in summary.items()))

        def _notify(self, title, msg):
            notify(title, "", msg, cfg)

        def _startup_update_check(self):
            d = check_update()
            if d.get("available"):
                self._notify(f"Update available — {d['latest']}",
                             "Open the menu → Check for Updates to download.")

        def check_updates(self, _):
            def worker():
                d = check_update(force=True)
                if d.get("available"):
                    self._notify(f"Update available — {d['latest']}",
                                 f"Downloading {d.get('name') or 'the latest release'}…")
                    open_update()
                elif d.get("error"):
                    self._notify("Update check failed", d["error"])
                else:
                    self._notify("You're up to date", f"Version {d['current']} is the latest.")
            threading.Thread(target=worker, daemon=True).start()

        def start_watching(self):
            if not self.watching:
                watcher.start()
                self.watching = True
                self.status_item.title = "Status: watching ~/Downloads"
                self.toggle_item.title = "Pause Watching"

        def stop_watching(self):
            if self.watching:
                watcher.stop()
                self.watching = False
                self.status_item.title = "Status: paused"
                self.toggle_item.title = "Resume Watching"

        # ---- menu callbacks ----
        def toggle(self, _):
            if self.watching:
                self.stop_watching()
            else:
                self.start_watching()

        def restart_service(self):
            """Stop the watcher, reload config.json, start a fresh watcher."""
            if self.watching:
                self.stop_watching()
            reload_config_into(cfg)
            self.start_watching()
            self._notify("Service restarted", "Watching ~/Downloads (config reloaded).")

        def restart_now(self, _):
            # Menu callbacks already run on the main thread.
            self.restart_service()

        def request_restart(self):
            """Called from the server thread; the real restart runs on the main
            thread in drain()."""
            self._restart_req = True

        def toggle_mode(self, _):
            new = "auto" if cfg.get("sort_mode", "auto") == "ask" else "ask"
            set_mode(cfg, new)
            self.mode_item.state = 1 if new == "ask" else 0
            self._notify("Sort mode",
                         "Ask before sorting new downloads" if new == "ask"
                         else "Auto-sorting new downloads")

        def organize_now(self, _):
            summary = organize_all(cfg, fresh_only=False)
            if summary:
                for cat, n in summary.items():
                    for _ in range(n):
                        events.put(("(manual)", cat))
                self._notify("Organized", ", ".join(f"{n}->{c}" for c, n in summary.items()))
            else:
                self._notify("Nothing to organize", "Top level of ~/Downloads is clean.")

        def open_dashboard(self, _):
            open_or_focus_dashboard()

        def request_show(self):
            """Called from the server thread; the actual window open runs on the
            main thread in drain() (AppKit must be main-threaded)."""
            self._show_req = True

        def request_toggle(self):
            """Called from the server thread; the real toggle runs on the main
            thread in drain() to keep AppKit calls main-threaded."""
            self._toggle_req = True
            return not self.watching

        def open_downloads(self, _):
            os.system(f'open {json.dumps(cfg["downloads_dir"])}')

        def edit_config(self, _):
            os.system(f'open -t {json.dumps(str(CONFIG_PATH))}')

        def open_log(self, _):
            LOG_PATH.touch(exist_ok=True)
            os.system(f'open -t {json.dumps(str(LOG_PATH))}')

        def quit_app(self, _):
            try:
                watcher.stop()
            finally:
                rumps.quit_application()

        # ---- pump background results onto the menu (main thread) ----
        def drain(self, _):
            if not self._setup_done:
                self._setup_done = True
                # Accessory policy: hide this process from the Dock and Cmd-Tab
                # (no stray "Python" icon). The status-bar item still shows, and
                # the pinned official .app shortcut remains the only Dock icon.
                try:
                    from AppKit import NSApp
                    NSApp.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory
                except Exception as e:
                    log(f"accessory policy failed: {e}")
            if self._toggle_req:
                self._toggle_req = False
                self.toggle(None)
            if self._restart_req:
                self._restart_req = False
                self.restart_service()
            if self._show_req:
                self._show_req = False
                open_or_focus_dashboard()
            changed = False
            while True:
                try:
                    name, cat = events.get_nowait()
                except queue.Empty:
                    break
                ts = datetime.datetime.now().strftime("%H:%M")
                self.recent.insert(0, f"{ts}  {name} -> {cat}")
                self.recent = self.recent[:12]
                changed = True
                # per-download banners are fired by the watcher (notify())
            if changed:
                self.recent_menu.clear()
                if self.recent:
                    for r in self.recent:
                        self.recent_menu.add(rumps.MenuItem(r))
                else:
                    self._set_recent_placeholder()

    app = DownloadOrganizer()

    def _organize():
        summary = organize_all(cfg, fresh_only=False)
        moved = sum(summary.values())
        for cat, n in summary.items():
            for _ in range(n):
                events.put(("(manual)", cat))
        return moved

    CTX["cfg"] = cfg
    CTX["state"] = lambda: build_state(cfg, app.watching)
    CTX["organize"] = _organize
    CTX["toggle"] = app.request_toggle
    CTX["restart"] = app.request_restart
    CTX["show"] = app.request_show
    start_server()
    # on-start dashboard open is handled via app._show_req in drain() (main thread)

    app.run()


# ----------------------------- entrypoint -----------------------------
if __name__ == "__main__":
    if "--once" in sys.argv:
        c = load_config()
        s = organize_all(c, fresh_only=False)
        print("organized:", s or "nothing")
    elif "--watch" in sys.argv:
        c = load_config()
        q: queue.Queue = queue.Queue()
        w = Watcher(c, q)
        w.start()
        print("watching… ctrl-c to stop")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            w.stop()
    else:
        run_app()
