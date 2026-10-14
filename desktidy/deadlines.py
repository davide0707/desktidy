# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""Deadlines: a bill "to be paid by 30 October", an enrolment "no later than 15/11/2026", a contract that "expires
on 2027-01-31". DeskTidy finds the date (and the amount, when there is one) in every document it tidies, offline,
in Italian and English; the AI is used only when it is reading the file anyway and the date is written in a way
the patterns don't catch. A few days before (7, 1 and 0 days by default) a notification reminds you, with buttons
to open the file or mark it as done.

  desktidy deadlines                  upcoming deadlines
  desktidy deadlines done <n>         paid / submitted: no more reminders
  desktidy deadlines add 2026-10-30 Pay the rent
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from . import config
from . import content as ct

MAX_AHEAD_DAYS = 400
WINDOW = 90                    # characters after a keyword where the date is looked for
REMIND_DAYS = [7, 1, 0]

_MONTHS = {
    "gennaio": 1, "gen": 1, "january": 1, "jan": 1, "febbraio": 2, "feb": 2, "february": 2, "marzo": 3, "mar": 3,
    "march": 3, "aprile": 4, "apr": 4, "april": 4, "maggio": 5, "mag": 5, "may": 5, "giugno": 6, "giu": 6, "june": 6,
    "jun": 6, "luglio": 7, "lug": 7, "july": 7, "jul": 7, "agosto": 8, "ago": 8, "august": 8, "aug": 8,
    "settembre": 9, "set": 9, "sett": 9, "september": 9, "sep": 9, "sept": 9, "ottobre": 10, "ott": 10,
    "october": 10, "oct": 10, "novembre": 11, "nov": 11, "november": 11, "dicembre": 12, "dic": 12,
    "december": 12, "dec": 12,
}
_M = "|".join(sorted(_MONTHS, key=len, reverse=True))
DATES = [
    ("ymd", re.compile(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b")),
    ("dmy", re.compile(r"\b(\d{1,2})\s?[/.\-]\s?(\d{1,2})\s?[/.\-]\s?(\d{4}|\d{2})\b")),
    ("d_month_y", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th|°)?\s+(?:di\s+)?({_M})\.?,?\s+(20\d\d)\b")),
    ("month_d_y", re.compile(rf"\b({_M})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d\d)\b")),
    ("d_month", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th|°)?\s+(?:di\s+)?({_M})\b(?!\.?,?\s+\d)")),
]
KEYWORDS = re.compile(
    r"\b(?:da\s+pagare\s+entro|pagamento\s+entro|pagare\s+entro|versare\s+entro|data\s+(?:di\s+)?scadenza|"
    r"scadenza(?:\s+(?:del\s+)?pagamento)?|data\s+limite|scade(?:\s+il)?|scadra(?:\s+il)?|"
    r"entro\s+e\s+non\s+oltre(?:\s+il)?|entro\s+(?:il|la\s+data\s+del|del)|termine\s+(?:ultimo|di\s+pagamento)|"
    r"consegna\s+entro|rinnovo\s+entro|valid[oa]\s+fino\s+al|"
    r"due\s+date|payment\s+due(?:\s+(?:by|on))?|amount\s+due\s+by|due\s+(?:by|on)|pay\s+by|deadline|"
    r"expires?(?:\s+on)?|expiry\s+date|expiration\s+date|valid\s+until|submit\s+by|no\s+later\s+than)\b")
PAYMENT = re.compile(r"\b(?:pagare|pagamento|importo|totale|fattura|bolletta|rata|versamento|pay|payment|amount|"
                     r"invoice|bill|balance|total)\b")
AMOUNT = re.compile(r"(?:(?P<c1>€|eur(?:o)?\b|\$|usd\b|£|gbp\b)\s?(?P<v1>\d{1,3}(?:[.\s']\d{3})*[.,]\d{2}|\d+[.,]\d{2}))"
                    r"|(?:(?P<v2>\d{1,3}(?:[.\s']\d{3})*[.,]\d{2}|\d+[.,]\d{2})\s?(?P<c2>€|eur(?:o)?\b|\$|usd\b|£))")
AMOUNT_HINT = re.compile(r"\b(?:totale\s+da\s+pagare|importo\s+da\s+pagare|da\s+pagare|importo|totale|amount\s+due|"
                         r"total\s+due|balance\s+due|total)\b")


@dataclass
class Found:
    when: date
    kind: str          # payment | deadline
    amount: str
    snippet: str


def _lower(text: str) -> str:
    return config.strip_accents(text).lower()


def _make(kind: str, m: re.Match, today: date) -> date | None:
    g = m.groups()
    try:
        if kind == "ymd":
            y, mo, d = int(g[0]), int(g[1]), int(g[2])
        elif kind == "dmy":
            d, mo, y = int(g[0]), int(g[1]), int(g[2])
            if mo > 12 and d <= 12:
                d, mo = mo, d  # 10/30/2026 written the American way
            y += 2000 if y < 100 else 0
        elif kind == "d_month_y":
            d, mo, y = int(g[0]), _MONTHS[g[1]], int(g[2])
        elif kind == "month_d_y":
            mo, d, y = _MONTHS[g[0]], int(g[1]), int(g[2])
        else:  # day and month only: the next time that day comes
            d, mo = int(g[0]), _MONTHS[g[1]]
            y = today.year
            if date(y, mo, d) < today - timedelta(days=7):
                y += 1
        return date(y, mo, d)
    except (ValueError, KeyError):
        return None


def _amount(text: str, around: int) -> str:
    """The amount closest to an "amount due / total" label near the deadline."""
    lo, hi = max(0, around - 300), min(len(text), around + 300)
    region = text[lo:hi]
    best, best_distance = "", 10 ** 9
    for m in AMOUNT.finditer(region):
        currency = (m.group("c1") or m.group("c2") or "").strip()
        value = (m.group("v1") or m.group("v2") or "").strip()
        hint = AMOUNT_HINT.search(region, max(0, m.start() - 60), m.start() + 1)
        distance = abs(lo + m.start() - around) - (1000 if hint else 0)
        if distance < best_distance:
            symbol = {"eur": "€", "euro": "€", "usd": "$", "gbp": "£"}.get(currency, currency)
            best, best_distance = f"{symbol} {value}".strip(), distance
    return best


def extract(text: str, today: date | None = None) -> list[Found]:
    """Deadlines written in the text: dates that follow a deadline keyword, between today and 400 days ahead,
    earliest first (at most 3)."""
    today = today or date.today()
    low = _lower(text[:ct.MAX_TEXT])
    found: dict[date, Found] = {}
    for k in KEYWORDS.finditer(low):
        window = low[k.end():k.end() + WINDOW]
        hits = sorted(((m.start(), kind, m) for kind, rx in DATES for m in rx.finditer(window)), key=lambda x: x[0])
        for _, kind, m in hits:
            when = _make(kind, m, today)
            if when is None:
                continue
            if today <= when <= today + timedelta(days=MAX_AHEAD_DAYS) and when not in found:
                around = low[max(0, k.start() - 150):k.end() + 150]
                kind_of = "payment" if PAYMENT.search(around) else "deadline"
                snippet = re.sub(r"\s+", " ", text[k.start():k.end() + m.end()]).strip()[:120]
                found[when] = Found(when, kind_of, _amount(text, k.start()) if kind_of == "payment" else "", snippet)
            break  # only the first date after each keyword
    return sorted(found.values(), key=lambda f: f.when)[:3]


# ---------------------------------------------------------------- the date of the document itself
ISSUED = re.compile(r"\b(?:data(?:\s+(?:documento|fattura|emissione|di\s+emissione))?|emess[ao](?:\s+il)?|del|"
                    r"date(?:\s+of\s+issue)?|invoice\s+date|issue\s+date|issued(?:\s+on)?|dated)\s*:?\s*$")
ISSUE_CHARS = 2000             # where a document says its own date: the top


def issue_date(text: str, today: date | None = None) -> date | None:
    """The date of a document (an invoice "del 12/10/2026", a letter dated 3 March 2025), offline: the first full
    date near the top that is not a deadline and not in the future; one right after "data", "del", "date",
    "issued" wins. None when the text has none."""
    today = today or date.today()
    head = _lower(text[:ISSUE_CHARS])
    due = set()
    for k in KEYWORDS.finditer(head):
        window = head[k.end():k.end() + WINDOW]
        due |= {k.end() + m.start() for _, rx in DATES for m in rx.finditer(window)}
    first, labelled = None, None
    hits = sorted(((m.start(), kind, m) for kind, rx in DATES if kind != "d_month" for m in rx.finditer(head)),
                  key=lambda x: x[0])
    for start, kind, m in hits:
        when = _make(kind, m, today)
        if when is None or start in due or not date(1990, 1, 1) <= when <= today + timedelta(days=1):
            continue
        first = first or when
        if ISSUED.search(head[max(0, start - 40):start]):
            labelled = when
            break
    return labelled or first


def file_date(path: str, an: ct.Analysis | None = None, ai_date: str = "") -> date:
    """The date a dated destination ({YEAR}, {MONTH}) uses for a file: the date the AI read in the document, else
    the one found offline in its text, else the day the file was last changed."""
    try:
        when = date.fromisoformat(ai_date)
        if date(1990, 1, 1) <= when <= date.today() + timedelta(days=1):
            return when
    except (TypeError, ValueError):
        pass
    if an is not None and an.text and not an.is_dir:
        when = issue_date(an.text)
        if when:
            return when
    try:
        return date.fromtimestamp(os.stat(path).st_mtime)
    except OSError:
        return date.today()


# ---------------------------------------------------------------- to a calendar
def _ics_text(s: str) -> str:
    """RFC 5545 TEXT: backslash, semicolon and comma escaped, new lines as \\n."""
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))


def _fold(line: str) -> str:
    """Lines longer than 75 octets go on with CRLF + a space, never inside a UTF-8 character."""
    out, current = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(current) + len(b) > (75 if not out else 74):
            out.append(current.decode("utf-8"))
            current = b""
        current += b
    out.append(current.decode("utf-8"))
    return "\r\n ".join(out)


def to_ics(items: list[dict], remind_days=None, now: datetime | None = None) -> str:
    """The open deadlines as an iCalendar file (Outlook, Google Calendar, Apple Calendar...): an all-day event on
    each date, with alarms at 9:00 on the reminder days (7, 1 and 0 days before by default). The same deadline
    keeps the same UID, so importing again updates it instead of adding a copy."""
    remind_days = sorted(REMIND_DAYS if remind_days is None else remind_days, reverse=True)
    moment = now or datetime.now(timezone.utc)
    dtstamp = (moment if moment.tzinfo else moment.astimezone()).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DeskTidy//Deadlines//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:DeskTidy"]
    for i in items:
        if i.get("done"):
            continue
        day = date.fromisoformat(i["date"])
        verb = "Pay" if i.get("kind") == "payment" else "Deadline"
        summary = f"{verb}: {i['what']}" + (f" · {i['amount']}" if i.get("amount") else "")
        details = "\n".join(x for x in (i.get("found", ""), i.get("path", "")) if x)
        lines += ["BEGIN:VEVENT", f"UID:{i['id']}@desktidy", f"DTSTAMP:{dtstamp}",
                  f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
                  f"SUMMARY:{_ics_text(summary)}", "TRANSP:TRANSPARENT"]
        if details:
            lines.append(f"DESCRIPTION:{_ics_text(details)}")
        for t in remind_days:
            trigger = "PT9H" if t <= 0 else f"-PT{24 * t - 9}H"  # 9:00 on the day, or t days before
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_text(summary)}", f"TRIGGER:{trigger}",
                      "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def export_ics(path: str, cfg: dict | None = None) -> int:
    """Write the open deadlines to `path`; returns how many."""
    remind = (cfg or {}).get("deadlines", {}).get("remind_days", REMIND_DAYS)
    items = [i for i in load() if not i.get("done")]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(to_ics(items, remind))
    return len(items)


# ---------------------------------------------------------------- the list
def _file() -> str:
    return config.path("deadlines")


def load() -> list[dict]:
    data = config.read_json(_file(), {})
    return data.get("items", []) if isinstance(data, dict) else []


def _save(items: list[dict]) -> None:
    config.write_json(_file(), {"items": sorted(items, key=lambda i: i["date"])})


def _id(what: str, when: str) -> str:
    return hashlib.blake2b(f"{what.lower()}|{when}".encode(), digest_size=4).hexdigest()


def add(when: date, what: str, kind: str = "deadline", amount: str = "", path: str = "", snippet: str = "",
        source: str = "manual") -> dict | None:
    """Add a deadline (None if the same one is already listed)."""
    items = load()
    new = {"id": _id(what, when.isoformat()), "date": when.isoformat(), "what": what.strip()[:100], "kind": kind,
           "amount": amount, "path": path, "found": snippet, "source": source, "notified": [], "done": False,
           "added": datetime.now().isoformat(timespec="seconds")}
    if any(i["id"] == new["id"] for i in items):
        return None
    _save(items + [new])
    return new


def add_for_file(path: str, an: ct.Analysis, title: str = "", ai_due: str = "") -> list[dict]:
    """Look for deadlines in a document that was just tidied; the AI's date is used when the patterns found none."""
    if not an.is_document or an.words < 15 or "code" in an.tags:
        return []
    what = title or os.path.splitext(os.path.basename(path))[0].replace("_", " ")
    added = []
    found = extract(an.text)
    for f in found:
        item = add(f.when, what, f.kind, f.amount, path, f.snippet, "offline")
        if item:
            added.append(item)
    if not found and ai_due:
        try:
            when = date.fromisoformat(ai_due)
        except ValueError:
            return added
        if date.today() <= when <= date.today() + timedelta(days=MAX_AHEAD_DAYS):
            item = add(when, what, "payment" if PAYMENT.search(_lower(an.text[:4000])) else "deadline", "", path,
                       "", "ai")
            if item:
                added.append(item)
    return added


def upcoming(include_done: bool = False, past_days: int = 30) -> list[dict]:
    """Not yet done (or all), from `past_days` ago onwards, soonest first."""
    first = (date.today() - timedelta(days=past_days)).isoformat()
    return [i for i in load() if i["date"] >= first and (include_done or not i.get("done"))]


def find(key: str) -> dict | None:
    """By id, or by number in the `upcoming()` list."""
    items = upcoming()
    if key.isdigit() and 1 <= int(key) <= len(items):
        return items[int(key) - 1]
    return next((i for i in load() if i["id"] == key), None)


def update(item_id: str, **changes) -> bool:
    items = load()
    for i in items:
        if i["id"] == item_id:
            i.update(changes)
            _save(items)
            return True
    return False


def remove(item_id: str) -> bool:
    items = load()
    kept = [i for i in items if i["id"] != item_id]
    if len(kept) == len(items):
        return False
    _save(kept)
    return True


def moved(old: str, new: str) -> None:
    """Keep the file of a deadline reachable after a move, rename or undo."""
    items = load()
    changed = False
    for i in items:
        if i.get("path") and os.path.normcase(i["path"]) == os.path.normcase(old):
            i["path"], changed = new, True
    if changed:
        _save(items)


def moved_folder(old: str, new: str) -> None:
    """A whole folder moved: the deadlines of the files inside it follow."""
    items = load()
    changed = False
    for i in items:
        if i.get("path") and config.inside(i["path"], old):
            i["path"], changed = new + i["path"][len(old):], True
    if changed:
        _save(items)


def days_left(item: dict, today: date | None = None) -> int:
    return (date.fromisoformat(item["date"]) - (today or date.today())).days


def when_text(item: dict, today: date | None = None) -> str:
    n = days_left(item, today)
    return {0: "today", 1: "tomorrow", -1: "yesterday"}.get(n, f"in {n} days" if n > 0 else f"{-n} days ago")


def remind(cfg: dict, notify, today: date | None = None) -> list[dict]:
    """Send the reminders that are due (each threshold once; "overdue" once). Returns the items reminded."""
    if not cfg.get("deadlines", {}).get("enabled", True):
        return []
    thresholds = sorted(cfg.get("deadlines", {}).get("remind_days", REMIND_DAYS), reverse=True)
    today = today or date.today()
    items, sent = load(), []
    for i in items:
        if i.get("done"):
            continue
        n = days_left(i, today)
        notified = set(i.get("notified", []))
        due = [t for t in thresholds if n <= t and t not in notified]
        overdue = n < 0 and "overdue" not in notified and n >= -3
        if not due and not overdue:
            continue
        i["notified"] = sorted(notified | set(due) | ({"overdue"} if n < 0 else set()), key=str)
        what = i["what"] + (f" · {i['amount']}" if i.get("amount") else "")
        verb = "Pay" if i.get("kind") == "payment" else "Deadline"
        title = f"{verb} {when_text(i, today)}" if n >= 0 else f"Overdue since {date.fromisoformat(i['date']):%d %b}"
        buttons = ([("Open", f"desktidy:deadline-open?id={i['id']}")] if i.get("path") else []) + \
            [("Done", f"desktidy:deadline-done?id={i['id']}")]
        notify(f"{title}: {date.fromisoformat(i['date']):%a %d %b}", what, buttons)
        sent.append(i)
    if sent:
        _save(items)
    return sent
