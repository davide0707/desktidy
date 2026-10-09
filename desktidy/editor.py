"""Settings in the browser (`desktidy editor`): rules, AI, limits, renaming, archive, deadlines and the other
options of rules.json in a page instead of a JSON file. Nothing to install and nothing online: a tiny web server
on 127.0.0.1 that only this computer can reach, open while the command runs.

Security: the page is served only with a random token in its address; every API call must carry the token in a
header (so other web pages can't call it: browsers don't send custom headers across sites without permission,
and this server never grants it) and the Host header must be 127.0.0.1 or localhost (no DNS rebinding).
Saving validates everything, keeps the previous file as rules.json.bak and applies at the next pass.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import APP_NAME, __version__, config, folders, providers

PAGE = config.PACKAGE_DIR / "editor.html"
IDLE_SECONDS = 1800
KINDS = ["photo", "screenshot", "icon", "scan", "code", "code_python", "code_c", "code_web", "code_shell", "code_sql",
         "project_code", "project_python", "project_web", "project_stm32", "project_kicad", "gerber", "print_3d",
         "font", "installer", "photo_folder", "audio_folder", "video_folder"]
LIST_FIELDS = ("name_words", "content_words", "topics", "recognize", "extensions")


def validate(data) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a whole rules.json. Errors block saving; warnings are shown."""
    errors, warnings = [], []
    if not isinstance(data, dict):
        return ["the settings must be a JSON object"], []
    for key, kind in (("rules", list), ("watched_folders", list), ("variables", dict), ("default_destination", str)):
        if not isinstance(data.get(key), kind):
            errors.append(f"'{key}' is missing or has the wrong type")
    if errors:
        return errors, warnings
    cfg = config.Config(data)
    for i, r in enumerate(data["rules"], 1):
        label = f"rule {i} ({r.get('name', '?')})" if isinstance(r, dict) else f"rule {i}"
        if not isinstance(r, dict):
            errors.append(f"{label} is not an object")
            continue
        if not str(r.get("name", "")).strip():
            errors.append(f"{label} has no name")
        if not str(r.get("destination", "")).strip():
            errors.append(f"{label} has no destination")
            continue
        for f in LIST_FIELDS:
            if f in r and not (isinstance(r[f], list) and all(isinstance(x, str) for x in r[f])):
                errors.append(f"{label}: '{f}' must be a list of words")
        if not any(r.get(f) for f in LIST_FIELDS):
            warnings.append(f"{label} has no words, kinds or extensions: it never matches")
        unknown = set(r.get("recognize", [])) - set(KINDS)
        if unknown:
            warnings.append(f"{label}: unknown kinds {', '.join(sorted(unknown))}")
        dest = cfg.expand(r["destination"])
        if "{" in dest:
            errors.append(f"{label}: unknown variable in {r['destination']}")
        elif not os.path.isdir(dest):
            warnings.append(f"{label}: {config.short(dest)} does not exist yet (it is created at the first move)")
    for w in data["watched_folders"]:
        if not isinstance(w, dict) or not w.get("path"):
            errors.append("a watched folder has no path")
        elif not os.path.isdir(cfg.expand(w["path"])):
            warnings.append(f"watched folder not found: {cfg.expand(w['path'])}")
        elif not isinstance(w.get("wait_seconds", 0), int) or w.get("wait_seconds", 0) < 0:
            errors.append(f"{w['path']}: wait_seconds must be a whole number of seconds")
    ai = data.get("ai", {})
    if ai.get("mode", "off") not in config.AI_MODES:
        errors.append(f"unknown AI mode '{ai.get('mode')}'")
    if ai.get("provider", "groq") not in providers.PROVIDERS:
        errors.append(f"unknown AI service '{ai.get('provider')}'")
    for where, value in (("ai.max_files_per_day", ai.get("max_files_per_day")),
                         ("limits.files_per_day", data.get("limits", {}).get("files_per_day"))):
        if value is not None and value != config.UNLIMITED and not (isinstance(value, int) and value >= 0):
            errors.append(f"{where} must be a number or \"unlimited\"")
    if data.get("rename", {}).get("mode", "smart") not in config.RENAME_MODES:
        errors.append("unknown rename mode")
    return errors, warnings


def state() -> dict:
    cfg = config.load_config()
    return {"rules": dict(cfg), "file": cfg.source, "version": __version__, "kinds": KINDS,
            "ai_modes": {k: v[0] for k, v in config.AI_MODES.items()},
            "rename_modes": config.RENAME_MODES,
            "providers": {k: {"name": p.name, "free": p.free, "model": p.model} for k, p in providers.PROVIDERS.items()},
            "pinned": [p["path"] for p in folders.load_pinned()["pinned"]],
            "expanded": {k: cfg.expand("{" + k + "}") for k in cfg.get("variables", {})}}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.token = secrets.token_urlsafe(24)
        self.last = time.time()
        self.closing = False

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/?t={self.token}"


class Handler(BaseHTTPRequestHandler):
    server: Server

    def log_message(self, *args):
        pass

    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _send(self, code: int, body, kind: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                    "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _authorised(self) -> bool:
        self.server.last = time.time()
        return self._host_ok() and secrets.compare_digest(self.headers.get("X-DeskTidy-Token", ""), self.server.token)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        if self.path.split("?")[0] == "/":
            if f"t={self.server.token}" not in self.path:
                return self._send(403, b"Open the editor with: desktidy editor", "text/plain")
            html = PAGE.read_text(encoding="utf-8").replace("__TOKEN__", self.server.token)
            return self._send(200, html.encode("utf-8"), "text/html")
        if self.path == "/api/state":
            if not self._authorised():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, state())
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > 5_000_000:
            return self._send(413, {"error": "too large"})
        raw = self.rfile.read(length)  # always read: answering before the body arrives breaks the connection
        if not self._authorised():
            return self._send(403, {"error": "forbidden"})
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return self._send(400, {"error": "invalid JSON"})
        if self.path == "/api/check":
            errors, warnings = validate(body)
            return self._send(200, {"errors": errors, "warnings": warnings})
        if self.path == "/api/save":
            errors, warnings = validate(body)
            if errors:
                return self._send(422, {"errors": errors, "warnings": warnings})

            def replace(data):
                data.clear()
                data.update(body)
            config.update_config(replace)
            return self._send(200, {"saved": True, "warnings": warnings, "file": config.path("rules")})
        if self.path == "/api/mkdir":
            cfg = config.Config(body.get("rules") or config.load_config())
            made = []
            for raw in body.get("paths", [])[:200]:
                p = cfg.expand(str(raw))
                if "{" not in p and os.path.isabs(p) and not os.path.isdir(p):
                    os.makedirs(p, exist_ok=True)
                    made.append(p)
            return self._send(200, {"created": made})
        if self.path == "/api/unpin":
            ok = folders.unpin(str(body.get("path", "")))
            return self._send(200, {"unpinned": ok})
        if self.path == "/api/close":
            self.server.closing = True
            self._send(200, {"bye": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        self._send(404, {"error": "not found"})


def serve(open_browser: bool = True, say=print) -> None:
    """Run the editor until the page is closed with its button, Ctrl+C, or 30 idle minutes."""
    server = Server()
    say(f"{APP_NAME} settings: {server.url}")
    if open_browser:
        webbrowser.open(server.url)

    def watchdog():
        while not server.closing:
            time.sleep(5)
            if time.time() - server.last > IDLE_SECONDS:
                server.shutdown()
                return
    threading.Thread(target=watchdog, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
