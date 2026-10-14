# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""The week in one notification: files tidied and renamed, duplicates and installers sent to the Recycle Bin, moves
you undid, the deadlines of the coming week, what waits in the to-sort pile, the AI's work and spend.

  desktidy week                     the last 7 days, any time
  desktidy week off | on            the weekly notification (on by default)
  desktidy week day friday          the day it comes (Monday by default)

When: on the first pass on or after the chosen day, at least 6 days after the previous one (a PC that was off on
Monday gets it on Tuesday). The first one comes after a full week of use. A week with nothing to say is skipped.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import date, timedelta

from . import config

WEEKDAYS = {"monday": 0, "lunedi": 0, "tuesday": 1, "martedi": 1, "wednesday": 2, "mercoledi": 2, "thursday": 3,
            "giovedi": 3, "friday": 4, "venerdi": 4, "saturday": 5, "sabato": 5, "sunday": 6, "domenica": 6}


def settings(cfg: dict) -> dict:
    s = cfg.get("summary", {})
    day = config.strip_accents(str(s.get("day", "monday"))).lower()
    return {"weekly": s.get("weekly", True) is not False, "day": WEEKDAYS.get(day, 0)}


def week(cfg: config.Config, today: date | None = None) -> dict:
    """What happened in the 7 days before today (today included), and what comes in the next 7."""
    from . import deadlines, usage
    from .service import read_moves
    today = today or date.today()
    first = today - timedelta(days=6)
    moves = [m for m in read_moves() if first.isoformat() <= m["time"][:10] <= today.isoformat()]
    moved = [m for m in moves if m["action"] == "MOVED"]
    places = Counter(os.path.basename(os.path.dirname(m["destination"])) for m in moved)
    recycled = [m for m in moves if m["action"] == "RECYCLED"]
    soon = sorted((d for d in deadlines.load() if not d.get("done")
                   and 0 <= deadlines.days_left(d, today) <= 7), key=lambda d: d["date"])
    try:
        pile = sum(1 for e in os.scandir(cfg.default_destination) if e.is_file() and not e.name.startswith((".", "!")))
    except OSError:
        pile = 0
    ai_files, ai_usd = usage.between(usage.read(), first.isoformat(), today.isoformat())
    return {
        "from": first.isoformat(), "to": today.isoformat(),
        "tidied": len(moved), "renamed": sum(1 for m in moved if "; renamed (" in m["reason"]),
        "by_ai": sum(1 for m in moved if m["reason"].startswith("AI (")),
        "places": places.most_common(3),
        "duplicates": sum(1 for m in moves if m["action"] == "DUPLICATE_TRASHED")
        + sum(1 for m in recycled if m["reason"].startswith("duplicate of")),
        "installers": sum(1 for m in recycled if m["reason"].startswith("installer of")),
        "undone": sum(1 for m in moves if m["action"] == "UNDONE"),
        "deadlines": [{"date": d["date"], "what": d["what"], "amount": d.get("amount", "")} for d in soon],
        "pile": pile, "ai_files": ai_files, "ai_usd": round(ai_usd, 4),
    }


def quiet(s: dict) -> bool:
    return not (s["tidied"] or s["duplicates"] or s["installers"] or s["deadlines"])


def message(s: dict) -> tuple[str, str]:
    """(title, body) of the notification: short, the numbers first."""
    parts = []
    if s["tidied"]:
        where = ", ".join(f"{name} {n}" for name, n in s["places"])
        parts.append(f"{s['tidied']} file(s) tidied" + (f", {s['renamed']} renamed" if s["renamed"] else "")
                     + (f" ({where})" if where else ""))
    cleaned = s["duplicates"] + s["installers"]
    if cleaned:
        parts.append(f"{cleaned} duplicate(s) and old installer(s) to the Recycle Bin")
    if s["deadlines"]:
        first = s["deadlines"][0]
        parts.append(f"{len(s['deadlines'])} deadline(s) this week: {first['what']} on {first['date']}"
                     + (f" ({first['amount']})" if first.get("amount") else ""))
    if s["pile"]:
        parts.append(f"{s['pile']} file(s) wait in the to-sort pile")
    if s["ai_files"]:
        parts.append(f"AI: {s['ai_files']} file(s)" + (f", ${s['ai_usd']:.2f}" if s["ai_usd"] else ", free"))
    return "DeskTidy: your week", ". ".join(parts) + "."


def _next(last: date, day: int) -> date:
    ahead = (day - last.weekday()) % 7 or 7
    when = last + timedelta(days=ahead)
    return when if (when - last).days >= 6 else when + timedelta(days=7)


def due(cfg: dict, today: date | None = None) -> bool:
    """Time for the weekly summary? The first call only starts counting."""
    s = settings(cfg)
    if not s["weekly"]:
        return False
    today = today or date.today()
    state = config.read_json(config.path("summary"), {}) or {}
    try:
        last = date.fromisoformat(state["last"])
    except (KeyError, TypeError, ValueError):
        config.write_json(config.path("summary"), {"last": today.isoformat()})
        return False
    return today >= _next(last, s["day"])


def sent(today: date | None = None) -> None:
    config.write_json(config.path("summary"), {"last": (today or date.today()).isoformat()})
