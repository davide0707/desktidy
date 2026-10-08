"""Learning from your corrections. When DeskTidy puts a file in the wrong place and you move it yourself (or undo
the move and then put the file somewhere), that is a correction. Corrections that point to the same folder and
share words become a proposed rule: "files about 'oscilloscope, probe' go to Study\\Lab". You accept it with one
command and it is added at the top of rules.json.

  desktidy learn                 corrections seen and proposed rules
  desktidy learn accept <n>      add the proposed rule
  desktidy learn reject <n>      never propose it again

How a correction is noticed (every 30 minutes, offline): for the recent moves whose file is no longer where
DeskTidy put it, the file is looked for by name and size in the destination folders.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta

from . import config, folders
from . import content as ct

MIN_EXAMPLES = 2
DAYS = 60
MAX_FILES_SCANNED = 60_000


def load() -> dict:
    d = config.read_json(config.path("learned"), {})
    if not isinstance(d, dict):
        d = {}
    for k in ("corrections", "proposals", "rejected", "seen"):
        d.setdefault(k, [])
    return d


def _save(d: dict) -> None:
    d["corrections"] = d["corrections"][-500:]
    d["seen"] = d["seen"][-3000:]
    config.write_json(config.path("learned"), d)


def _names_index(cfg: config.Config) -> dict[str, list[str]]:
    """lower-case file name -> paths, in the destination folders (and their subfolders, a few levels down)."""
    rule_dests = sorted({cfg.expand(r["destination"]) for r in cfg["rules"]})
    out: dict[str, list[str]] = {}
    seen = 0
    for folder in folders.candidate_folders(cfg, rule_dests, cfg.default_destination) + \
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
    if not candidates:
        return []
    names = _names_index(cfg)
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
    new = _propose(d, cfg)
    _save(d)
    return new


def _propose(d: dict, cfg: config.Config) -> list[dict]:
    """Corrections towards the same folder that share words -> a rule."""
    minimum = cfg.get("learn", {}).get("min_examples", MIN_EXAMPLES)
    by_folder: dict[str, list[dict]] = {}
    for c in d["corrections"]:
        by_folder.setdefault(os.path.normcase(c["user"]), []).append(c)
    known = {p["key"] for p in d["proposals"]} | set(d["rejected"])
    new = []
    for examples in by_folder.values():
        if len(examples) < minimum:
            continue
        need = max(2, round(0.6 * len(examples)))
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
        key = os.path.normcase(folder) + "|" + ",".join(sorted(name_words + topics))
        if key in known:
            continue
        from .ops import unexpand
        rule = {"name": f"Learned: {os.path.basename(folder)}",
                "name_words": [originals.get(t, t) for t in name_words],
                "topics": [originals.get(t, t) for t in topics], "min_topics": 2,
                "destination": unexpand(cfg, folder), "learned": datetime.now().date().isoformat()}
        if not rule["name_words"]:
            del rule["name_words"]
        proposal = {"key": key, "rule": rule, "examples": [c["file"] for c in examples][-5:],
                    "at": datetime.now().isoformat(timespec="seconds")}
        d["proposals"].append(proposal)
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
