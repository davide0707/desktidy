# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
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
import re
import secrets
import threading
import time
import webbrowser
from datetime import date
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
        if "{" in config.dated(dest, date.today()):  # {YEAR} and {MONTH} are filled in from each file's date
            errors.append(f"{label}: unknown variable in {r['destination']}")
        elif not os.path.isdir(config.undated(dest)):
            warnings.append(f"{label}: {config.short(config.undated(dest))} does not exist yet (it is created at the "
                            "first move)")
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


# ---------------------------------------------------------------- the Organize and History tabs
def organize_state() -> dict:
    """The crowded folders, the saved plan and what the AI would see (never the key: only whether it is ready)."""
    from . import ai, organize, redact
    cfg = config.load_config()
    p = providers.current(cfg)
    mode = config.ai_mode(cfg)
    spots = [{"path": s.path, "name": os.path.basename(s.path.rstrip(os.sep)) or s.path, "files": s.files,
              "folders": s.folders} for s in organize.crowded(cfg)]
    return {"spots": spots, "plan": organize.load(),
            "ai": {"ready": bool(ai.ready(cfg, lambda m: None, files=False)), "service": p.name, "local": p.local,
                   "mode": mode, "private_sent": mode == config.EVERYTHING, "masked": redact.wanted(cfg)}}


def organize_plan(body: dict) -> tuple[int, dict]:
    from . import ai, organize
    cfg = config.load_config()
    folder = os.path.abspath(os.path.expanduser(str(body.get("folder", ""))))
    if not os.path.isdir(folder) or config.inside(folder, str(config.data_dir())):
        return 422, {"error": f"{folder} is not a folder that can be organised"}
    key = None if body.get("offline") else ai.ready(cfg, lambda m: None, files=False)
    result = organize.plan_folder(folder, cfg, key, lambda m: None)
    data = organize.save([result], cfg, offline=key is None)
    return 200, {"plan": data, "failed": result["failed"]}


def _numbers(body: dict) -> list[int]:
    raw = body.get("numbers")
    return [n for n in raw if isinstance(n, int) and not isinstance(n, bool)][:500] if isinstance(raw, list) else []


def organize_preview(body: dict) -> tuple[int, dict]:
    from . import ops, organize
    groups = organize.load().get("groups", [])
    chosen = [groups[n - 1] for n in _numbers(body) if 1 <= n <= len(groups) and not groups[n - 1].get("applied")]
    if not chosen:
        return 422, {"error": "choose at least one group not applied yet"}
    plan, notes = organize.steps(chosen, config.load_config(), bool(body.get("pin")))
    return 200, {"title": plan.title, "steps": [ops.describe(s) for s in plan.steps][:300], "notes": notes,
                 "problems": plan.problems, "moves": sum(1 for s in plan.steps if s["op"] == "move")}


def organize_apply(body: dict) -> tuple[int, dict]:
    from . import organize
    try:
        entry = organize.apply(_numbers(body), config.load_config(), bool(body.get("pin")))
    except Exception as ex:  # nothing was changed: ops.apply rolls back
        return 422, {"error": f"Stopped and rolled back: {ex}"}
    return 200, {"title": entry["title"], "moved": sum(1 for s in entry["steps"] if s["op"] == "move")}


def organize_undo() -> tuple[int, dict]:
    from . import ops, organize
    latest = next((e for e in reversed(ops.journal()) if not e.get("undone")), None)
    entry = organize.undo(config.load_config())
    if not entry:
        return 409, {"error": f"The latest folder change is not an organize: {latest['title']}" if latest
                     else "Nothing to undo"}
    return 200, {"title": entry["title"], "skipped": entry.get("skipped", []),
                 "back": sum(1 for s in entry["steps"] if s["op"] == "move" and s.get("restored"))}


def history(limit: int = 60) -> dict:
    """The latest moves, newest first, with whether each can still be undone."""
    from .cli import UNDOABLE
    from .ops import current_path
    from .service import move_id, read_moves
    rows = []
    for m in read_moves()[-limit:][::-1]:
        where = current_path(m["destination"])
        rows.append({"id": move_id(m), "time": m["time"], "action": m["action"],
                     "name": os.path.basename(m["source"]), "from": os.path.dirname(m["source"]),
                     "to": where, "reason": m["reason"],
                     "undoable": m["action"] in UNDOABLE and os.path.exists(where)})
    return {"moves": rows}


def undo(body: dict) -> tuple[int, dict]:
    from .cli import UNDOABLE, undo_move
    from .service import move_id, read_moves
    wanted = str(body.get("id", ""))
    if not re.fullmatch(r"[0-9a-f]{8}", wanted):
        return 422, {"error": "invalid id"}
    m = next((m for m in reversed(read_moves()) if move_id(m) == wanted and m["action"] in UNDOABLE), None)
    if not m:
        return 404, {"error": "no such move"}
    try:
        return 200, {"restored": undo_move(m)}
    except OSError as ex:
        return 409, {"error": str(ex)}


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
        reads = {"/api/state": state, "/api/organize": organize_state, "/api/history": history}
        if self.path in reads:
            if not self._authorised():
                return self._send(403, {"error": "forbidden"})
            return self._send(200, reads[self.path]())
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
        if not isinstance(body, dict):  # the other calls take an object (a list here would fail on body.get)
            return self._send(400, {"error": "a JSON object is expected"})
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
        actions = {"/api/organize/plan": organize_plan, "/api/organize/preview": organize_preview,
                   "/api/organize/apply": organize_apply, "/api/organize/undo": lambda b: organize_undo(),
                   "/api/undo": undo}
        if self.path in actions:
            return self._send(*actions[self.path](body))
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
