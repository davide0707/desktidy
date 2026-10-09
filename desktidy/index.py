"""Search by content: `desktidy find electricity bill september` finds a file by what it says, not by its name.

Every file DeskTidy tidies is added to a local full-text index (SQLite FTS5, part of Python): its name, title,
one-line summary, key terms and up to 20,000 characters of text (OCR included). Existing files are indexed in the
background once a day (`desktidy find --rebuild` does it now). Everything stays in index.db, in the data folder:
nothing is sent anywhere. Words are matched ignoring accents, plural and singular ("bollette" finds "bolletta").
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from . import config, system
from . import content as ct

BODY_CHARS = 20_000
_COLLATE = "" if system.LINUX else "COLLATE NOCASE"  # paths: case-sensitive on Linux, not on Windows and macOS
WEIGHTS = (6.0, 4.0, 4.0, 2.0, 1.0)     # bm25 weight of name, title, summary, keywords, body
MARK = ("", "")         # around the matched words in a snippet (never found in real text)
INDEXABLE = ct.DOCUMENT_EXT | ct.TEXT_EXT | ct.HTML_EXT | {".eml", ".epub", ".ipynb", ".rtf"}
_lock = threading.Lock()
_fts: dict = {}


def db_path() -> str:
    return str(config.data_dir() / "index.db")


def _has_fts5() -> bool:
    if "ok" not in _fts:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
            _fts["ok"] = True
        except sqlite3.Error:
            _fts["ok"] = False
        finally:
            con.close()
    return _fts["ok"]


def connect() -> sqlite3.Connection:
    """A connection to the index (one per call: safe from any thread)."""
    config.data_dir().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path(), timeout=15)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(f"CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, path TEXT UNIQUE {_COLLATE}, "
                "size INTEGER, mtime REAL, added TEXT, title TEXT, summary TEXT)")
    if _has_fts5():
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(name, title, summary, keywords, body, "
                    "tokenize='unicode61 remove_diacritics 2', prefix='2 3')")
    else:  # very old SQLite: plain table, LIKE search
        con.execute("CREATE TABLE IF NOT EXISTS docs (rowid INTEGER PRIMARY KEY, name TEXT, title TEXT, summary TEXT, "
                    "keywords TEXT, body TEXT)")
    return con


@contextmanager
def _db():
    """A connection that commits (or rolls back) and is closed at the end: Windows keeps open files locked."""
    con = connect()
    try:
        with con:
            yield con
    finally:
        con.close()


def _name_words(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[_\-.]+", " ", ct.split_camel(stem))


def add(path: str, an: ct.Analysis | None = None, summary: str = "", title: str = "") -> bool:
    """Add (or refresh) one file. Without an analysis the file is read now, without OCR."""
    try:
        st = os.stat(path)
        if an is None:
            an = ct.analyze(path, False, {"analysis": {"ocr": False}})
    except OSError:
        return False
    if not title and an.ext in ct.DOCUMENT_EXT and "code" not in an.tags:  # a "title" of code or data is noise
        from .naming import title as find_title
        title = find_title(an) or ""
    keywords = " ".join(an.original(s) for s, _ in an.keywords(25)) + " " + " ".join(sorted(an.tags))
    with _lock, _db() as con:
        old = con.execute("SELECT id, summary FROM files WHERE path = ?", (path,)).fetchone()
        if old:
            summary = summary or old[1] or ""
            con.execute("DELETE FROM docs WHERE rowid = ?", (old[0],))
            con.execute("DELETE FROM files WHERE id = ?", (old[0],))
        cur = con.execute("INSERT INTO files (path, size, mtime, added, title, summary) VALUES (?, ?, ?, ?, ?, ?)",
                          (path, st.st_size, st.st_mtime, datetime.now().isoformat(timespec="seconds"), title, summary))
        con.execute("INSERT INTO docs (rowid, name, title, summary, keywords, body) VALUES (?, ?, ?, ?, ?, ?)",
                    (cur.lastrowid, _name_words(path), title, summary, keywords, an.text[:BODY_CHARS]))
    return True


def moved(old: str, new: str) -> None:
    """A file changed place or name: keep its entry (and summary) pointing at it."""
    with _lock, _db() as con:
        row = con.execute("SELECT id FROM files WHERE path = ?", (old,)).fetchone()
        if row:
            con.execute("DELETE FROM files WHERE path = ? AND id != ?", (new, row[0]))
            con.execute("UPDATE files SET path = ? WHERE id = ?", (new, row[0]))
            con.execute("UPDATE docs SET name = ? WHERE rowid = ?", (_name_words(new), row[0]))


def moved_folder(old: str, new: str) -> None:
    """A whole folder moved: every file indexed inside it follows."""
    old, new = old.rstrip(os.sep), new.rstrip(os.sep)
    with _lock, _db() as con:
        rows = con.execute("SELECT id, path FROM files WHERE path LIKE ? ESCAPE '|'",
                           (old.replace("|", "||").replace("%", "|%").replace("_", "|_") + os.sep + "%",)).fetchall()
        for row_id, path in rows:
            con.execute("UPDATE files SET path = ? WHERE id = ?", (new + path[len(old):], row_id))


def remove(path: str) -> None:
    with _lock, _db() as con:
        row = con.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()
        if row:
            con.execute("DELETE FROM docs WHERE rowid = ?", (row[0],))
            con.execute("DELETE FROM files WHERE id = ?", (row[0],))


def summary_of(path: str) -> str:
    try:
        with _db() as con:
            row = con.execute("SELECT summary, title FROM files WHERE path = ?", (path,)).fetchone()
    except sqlite3.Error:
        return ""
    return (row[0] or row[1] or "") if row else ""


@dataclass
class Hit:
    path: str
    title: str
    summary: str
    snippet: str
    mtime: float


def _terms(query: str) -> list[str]:
    """'Bollette luce, settembre!' -> ['bollett', 'luce', 'settembr']: accent-free stems used as prefixes, so that
    singular, plural and other endings all match."""
    out = []
    for w in ct.normalize(query).split():
        if len(w) < 2:
            continue
        s = ct.stem(w)
        out.append(s if len(s) >= 3 else w)
    return list(dict.fromkeys(out))


def search(query: str, limit: int = 15) -> list[Hit]:
    """Files whose name, title, summary or text contain all the words (or, failing that, most of them), best
    first. Entries of files that no longer exist are dropped on the way."""
    terms = _terms(query)
    if not terms:
        return []
    hits: list[Hit] = []
    with _db() as con:
        if _has_fts5():
            for joiner in (" AND ", " OR "):
                match = joiner.join(f'"{t}"*' for t in terms)
                rows = con.execute(
                    "SELECT f.path, f.title, f.summary, snippet(docs, 4, ?, ?, '...', 14), f.mtime FROM docs "
                    "JOIN files f ON f.id = docs.rowid WHERE docs MATCH ? ORDER BY bm25(docs, ?, ?, ?, ?, ?) "
                    "LIMIT ?", (MARK[0], MARK[1], match, *WEIGHTS, limit * 2)).fetchall()
                if rows or len(terms) == 1:
                    break
        else:
            where = " AND ".join("(d.name || ' ' || d.title || ' ' || d.summary || ' ' || d.body) LIKE ?" for _ in terms)
            rows = con.execute(f"SELECT f.path, f.title, f.summary, '', f.mtime FROM docs d JOIN files f ON f.id = "
                               f"d.rowid WHERE {where} LIMIT ?", (*[f"%{t}%" for t in terms], limit * 2)).fetchall()
    gone = []
    for path, title_, summary, snippet, mtime in rows:
        if not os.path.exists(path):
            gone.append(path)
            continue
        hits.append(Hit(path, title_ or "", summary or "", re.sub(r"\s+", " ", snippet or "").strip(), mtime or 0))
    for path in gone:
        remove(path)
    return hits[:limit]


def stats() -> dict:
    try:
        with _db() as con:
            files = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    except sqlite3.Error:
        files = 0
    size = sum(os.path.getsize(p) for p in (db_path(), db_path() + "-wal") if os.path.exists(p))
    return {"files": files, "bytes": size}


def refresh(cfg: config.Config, limit: int = 2000, ocr: bool = False, progress=None) -> dict:
    """Index the documents already in the destination folders (candidate folders, rule destinations, pinned
    folders), skipping the ones already indexed and unchanged, and forget the files that are gone."""
    from . import folders
    if not cfg.get("search", {}).get("enabled", True):
        return {"added": 0, "removed": 0}
    rule_dests = sorted({cfg.expand(r["destination"]) for r in cfg["rules"]})
    private = [cfg.expand(r["destination"]) for r in cfg["rules"] if r.get("private")]
    skip_private = not cfg.get("search", {}).get("index_private", True)
    with _db() as con:
        known = {os.path.normcase(p): (s, m) for p, s, m in con.execute("SELECT path, size, mtime FROM files")}
    removed = 0
    for key in list(known):
        if not os.path.exists(key):
            remove(key)
            removed += 1
    added = 0
    for folder in folders.candidate_folders(cfg, rule_dests, cfg.default_destination):
        if skip_private and any(config.inside(folder, p) for p in private):
            continue
        try:
            entries = [e for e in os.scandir(folder) if e.is_file() and not e.name.startswith(("~$", ".", "!"))]
        except OSError:
            continue
        for e in entries:
            ext = os.path.splitext(e.name)[1].lower()
            if ext not in INDEXABLE and not (ocr and ext in ct.IMAGE_EXT):
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            if known.get(os.path.normcase(e.path)) == (st.st_size, st.st_mtime) or st.st_size > 60_000_000:
                continue
            an = ct.analyze(e.path, False, {"analysis": {"ocr": ocr}})
            if add(e.path, an):
                added += 1
                if progress:
                    progress(e.path)
            if added >= limit:
                return {"added": added, "removed": removed}
    return {"added": added, "removed": removed}
