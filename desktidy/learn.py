"""Learning from your corrections. When DeskTidy puts a file in the wrong place and you move it yourself (or undo
the move and then put the file somewhere), that is a correction. Corrections that point to the same folder and
share words become a proposed rule: "files about 'oscilloscope, probe' go to Study\\Lab". You accept it with one
command and it is added at the top of rules.json.

  desktidy learn                 corrections seen and proposed rules
  desktidy learn accept <n>      add the proposed rule
  desktidy learn reject <n>      never propose it again

How a correction is noticed (every 30 minutes, offline): for the recent moves whose file is no longer where
DeskTidy put it, the file is looked for by name and size in the destination folders.

Learning from the AI, too: when the AI has put 5 files with words in common in the same folder, and they are still
there 3 days later (you agreed), the same kind of rule is proposed. Accepted, it places the next ones offline: less
AI, less spend, and it works without internet. Files the rules already place are not counted.

A learned rule into a private folder (the destination of a private rule) is private too, and a rule for a dated
folder (Bills/2026) points to the dated destination (Bills/{YEAR}), not to that one year.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta

from . import classifier, config, folders
from . import content as ct

MIN_EXAMPLES = 2
MIN_AI_EXAMPLES = 5        # files the AI put in the same folder before a rule is proposed (learn.min_ai_examples)
AI_SETTLE_DAYS = 3         # an AI move counts once the user had time to correct it
DAYS = 60
MAX_FILES_SCANNED = 60_000


def load() -> dict:
    d = config.read_json(config.path("learned"), {})
    if not isinstance(d, dict):
        d = {}
    for k in ("corrections", "proposals", "rejected", "seen", "ai_examples", "ai_seen"):
        d.setdefault(k, [])
    return d


def _save(d: dict) -> None:
    d["corrections"] = d["corrections"][-500:]
    d["seen"] = d["seen"][-3000:]
    d["ai_examples"] = d["ai_examples"][-1000:]
    d["ai_seen"] = d["ai_seen"][-3000:]
    config.write_json(config.path("learned"), d)


def _example(path: str, folder: str, **extra) -> dict:
    an = ct.analyze(path, False, {"analysis": {"ocr": False}})
    return {"at": datetime.now().isoformat(timespec="seconds"), "file": os.path.basename(path), "user": folder,
            "name_terms": list(dict.fromkeys(an.name_terms))[:8], "terms": [s for s, _ in an.keywords(15)],
            "originals": {s: an.original(s) for s, _ in an.keywords(15)}, **extra}


def _same_place(dest: str, folder: str) -> bool:
    if config.is_dated(dest):
        return bool(config.dated_pattern(dest, exact=True).match(os.path.normpath(folder)))
    return os.path.normcase(os.path.normpath(dest)) == os.path.normcase(os.path.normpath(folder))


def _from_ai(d: dict, cfg: config.Config, moves: list[dict]) -> None:
    """The files the AI placed and the user left there: examples for a rule. Each move is looked at once."""
    from .ops import current_path
    from .service import move_id
    seen = set(d["ai_seen"])
    settled = (datetime.now() - timedelta(days=AI_SETTLE_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    for m in moves:
        if m["action"] != "MOVED" or not m["reason"].startswith("AI (") or m["time"] > settled:
            continue
        mid = move_id(m)
        if mid in seen:
            continue
        seen.add(mid)
        path = current_path(m["destination"])
        if not os.path.isfile(path):
            continue  # moved since: if by the user, the corrections learn from it
        folder = os.path.dirname(path)
        try:
            an = ct.analyze(path, False, {"analysis": {"ocr": False}})
            decision = classifier.decide(path, False, cfg, an)
        except OSError:
            continue
        if decision.dest and decision.strength == "strong" and _same_place(decision.dest, folder):
            continue  # the rules place it there already: nothing to learn
        d["ai_examples"].append(_example(path, folder, source="ai"))
    d["ai_seen"] = sorted(seen)


def _destination(cfg: config.Config, folder: str) -> tuple[str, bool]:
    """(how rules.json should write the folder, whether it is private): Bills/2026 made by the rule Bills/{YEAR}
    is that dated destination; a folder inside a private rule's destination is private."""
    from .ops import unexpand
    written = unexpand(cfg, folder)
    private = False
    for r in cfg["rules"]:
        dest = cfg.expand(r["destination"])
        if config.is_dated(dest) and _same_place(dest, folder):
            written = r["destination"]
        if r.get("private") and config.inside(folder, config.undated(dest)):
            private = True
    return written, private


def _names_index(cfg: config.Config) -> dict[str, list[str]]:
    """lower-case file name -> paths, in the destination folders (and their subfolders, a few levels down)."""
    rule_dests = sorted({cfg.expand(r["destination"]) for r in cfg["rules"]})
    out: dict[str, list[str]] = {}
    seen = 0
    for folder in folders.real_folders(cfg, rule_dests, cfg.default_destination) + \
            [cfg.expand(w["path"]) for w in cfg["watched_folders"]]:
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for e in entries:
            if e.is_file():
                out.setdefault(e.name.lower(), []).append(e.path)
                seen += 1
        if seen > MAX_FILES_SCANNED:
            break
    return out


def scan(cfg: config.Config) -> list[dict]:
    """Look for new corrections; returns the new proposals (also saved)."""
    from .service import move_id, read_moves
    d = load()
    seen = set(d["seen"])
    first = (datetime.now() - timedelta(days=DAYS)).strftime("%Y-%m-%d")
    moves = [m for m in read_moves() if m["time"] >= first]
    undone_from = {os.path.normcase(m["source"]): m for m in moves if m["action"] == "UNDONE"}
    candidates = []
    for m in moves:
        if m["action"] != "MOVED" or move_id(m) in seen:
            continue
        dest = m["destination"]
        undo = undone_from.get(os.path.normcase(dest))
        where_now = undo["destination"] if undo else dest   # after an undo the file was in the watched folder
        if os.path.exists(where_now):
            continue  # still where DeskTidy (or the undo) put it: nothing learned yet
        candidates.append((m, where_now, undo is not None))
    names = _names_index(cfg) if candidates else {}
    inbox = cfg.default_destination
    for m, where_now, undone in candidates:
        found = [p for p in names.get(os.path.basename(where_now).lower(), [])
                 if os.path.normcase(os.path.dirname(p)) not in
                 (os.path.normcase(os.path.dirname(where_now)), os.path.normcase(inbox))]
        seen.add(move_id(m))
        if len(found) != 1:
            continue
        new_place = found[0]
        try:
            an = ct.analyze(new_place, False, {"analysis": {"ocr": False}})
        except OSError:
            continue
        d["corrections"].append({
            "at": datetime.now().isoformat(timespec="seconds"), "file": os.path.basename(new_place),
            "chosen": os.path.dirname(m["destination"]), "user": os.path.dirname(new_place), "undone": undone,
            "name_terms": list(dict.fromkeys(an.name_terms))[:8],
            "terms": [s for s, _ in an.keywords(15)], "originals": {s: an.original(s) for s, _ in an.keywords(15)}})
    d["seen"] = sorted(seen)
    _from_ai(d, cfg, moves)
    new = _propose(d, cfg)
    _save(d)
    return new


def _propose(d: dict, cfg: config.Config) -> list[dict]:
    """Corrections, or AI decisions, towards the same folder that share words -> a rule."""
    learn = cfg.get("learn", {})
    known = {p["key"] for p in d["proposals"]} | set(d["rejected"])
    new = []
    for source, pool, minimum in (("corrections", d["corrections"], learn.get("min_examples", MIN_EXAMPLES)),
                                  ("ai", d["ai_examples"], learn.get("min_ai_examples", MIN_AI_EXAMPLES))):
        new += _proposals(d, cfg, source, pool, minimum, known)
    return new


def _proposals(d: dict, cfg: config.Config, source: str, pool: list[dict], minimum: int, known: set) -> list[dict]:
    by_folder: dict[str, list[dict]] = {}
    for c in pool:  # Bills/2025 and Bills/2026 made by Bills/{YEAR} count together
        by_folder.setdefault(os.path.normcase(_destination(cfg, c["user"])[0]), []).append(c)
    new = []
    for examples in by_folder.values():
        if len(examples) < minimum:
            continue
        need = max(2 if source == "corrections" else 3, round(0.6 * len(examples)))
        name_count = Counter(t for c in examples for t in set(c["name_terms"]))
        term_count = Counter(t for c in examples for t in set(c["terms"]))
        ranked = lambda c: sorted(c.items(), key=lambda x: (-x[1], x[0]))  # noqa: E731 - same order every run
        name_words = [t for t, n in ranked(name_count)[:4] if n >= need]
        topics = [t for t, n in ranked(term_count)[:8] if n >= need]
        if not name_words and len(topics) < 2:
            continue
        originals = {}
        for c in examples:
            originals.update(c.get("originals", {}))
        folder = examples[-1]["user"]
        written, private = _destination(cfg, folder)
        key = os.path.normcase(written) + "|" + ",".join(sorted(name_words + topics))
        if key in known:
            continue
        shown = os.path.basename(config.undated(cfg.expand(written)))
        rule = {"name": f"Learned{' from the AI' if source == 'ai' else ''}: {shown}",
                "name_words": [originals.get(t, t) for t in name_words],
                "topics": [originals.get(t, t) for t in topics], "min_topics": 2,
                "destination": written, "learned": datetime.now().date().isoformat()}
        if not rule["name_words"]:
            del rule["name_words"]
        if private:
            rule["private"] = True  # into a private folder: what it matches is private too
        proposal = {"key": key, "rule": rule, "examples": [c["file"] for c in examples][-5:], "source": source,
                    "count": len(examples), "at": datetime.now().isoformat(timespec="seconds")}
        d["proposals"].append(proposal)
        known.add(key)
        new.append(proposal)
    return new


def accept(n: int) -> dict | None:
    """Add proposal n (1-based) at the top of the rules, so it wins over the bundled ones."""
    d = load()
    if not 1 <= n <= len(d["proposals"]):
        return None
    proposal = d["proposals"].pop(n - 1)
    config.update_config(lambda data: data["rules"].insert(0, proposal["rule"]))
    d["rejected"].append(proposal["key"])  # never proposed again
    _save(d)
    return proposal


def reject(n: int) -> dict | None:
    d = load()
    if not 1 <= n <= len(d["proposals"]):
        return None
    proposal = d["proposals"].pop(n - 1)
    d["rejected"].append(proposal["key"])
    _save(d)
    return proposal
