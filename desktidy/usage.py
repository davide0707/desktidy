# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""AI spend: per day, per model, budget, declared credit and the reasons to pause the AI.

Costs are computed from the token counts Anthropic returns with every answer, so they match the bill
(the Batch API is billed at half price). Anthropic does not expose the prepaid balance to API keys:
the user can declare it (`desktidy spend credit 4.85`) and DeskTidy keeps an estimate from there.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from . import config


def read() -> dict:
    u = config.read_json(config.path("usage"), {})
    if not isinstance(u, dict):
        u = {}
    u.setdefault("total_usd", 0.0)
    u.setdefault("total_files", 0)
    u.setdefault("days", {})
    u.setdefault("models", {})
    today = u["days"].get(date.today().isoformat(), {})
    u["today_files"] = today.get("files", 0)
    u["today_usd"] = today.get("usd", 0.0)
    return u


def _save(u: dict) -> None:
    config.write_json(config.path("usage"), {k: v for k, v in u.items() if not k.startswith("today_")})


def cost(model: str, input_tokens: int, output_tokens: int, cache_write: int = 0, cache_read: int = 0,
         batch: bool = False, price: tuple[float, float] | None = None) -> float:
    price_in, price_out = price or config.PRICES.get(model, (0.0, 0.0))
    usd = (input_tokens * price_in + cache_write * price_in * 1.25 + cache_read * price_in * 0.1
           + output_tokens * price_out) / 1_000_000
    return usd * (0.5 if batch else 1.0)


def record(model: str, files: int, input_tokens: int, output_tokens: int, cache_write: int = 0,
           cache_read: int = 0, batch: bool = False, price: tuple[float, float] | None = None) -> float:
    """Add one API answer (covering `files` files) to the books; returns its cost in USD."""
    usd = cost(model, input_tokens, output_tokens, cache_write, cache_read, batch, price)
    u = read()
    day = u["days"].setdefault(date.today().isoformat(), {"files": 0, "usd": 0.0, "requests": 0})
    day["files"] += files
    day["requests"] = day.get("requests", 0) + 1
    day["usd"] = round(day["usd"] + usd, 6)
    m = u["models"].setdefault(model, {"files": 0, "usd": 0.0, "input_tokens": 0, "output_tokens": 0})
    m["files"] += files
    m["usd"] = round(m["usd"] + usd, 6)
    m["input_tokens"] += input_tokens + cache_write + cache_read
    m["output_tokens"] += output_tokens
    u["total_files"] += files
    u["total_usd"] = round(u["total_usd"] + usd, 6)
    oldest = (date.today() - timedelta(days=400)).isoformat()
    u["days"] = {d: v for d, v in sorted(u["days"].items()) if d >= oldest}
    u.pop("warning", None)  # a successful call clears any previous problem
    _save(u)
    return usd


def warn(text: str) -> None:
    """A problem to show in `desktidy status` (invalid key, credit exhausted...)."""
    u = read()
    u["warning"] = {"at": datetime.now().isoformat(timespec="seconds"), "text": text}
    _save(u)


def clear_warning() -> None:
    u = read()
    if u.pop("warning", None):
        _save(u)


def between(u: dict, first: str, last: str | None = None) -> tuple[int, float]:
    """(files, USD) between two ISO dates, inclusive."""
    last = last or date.today().isoformat()
    rows = [v for d, v in u["days"].items() if first <= d <= last]
    return sum(v["files"] for v in rows), sum(v["usd"] for v in rows)


def set_credit(usd: float) -> None:
    """Remember the balance shown in the Anthropic console right now; the remainder is estimated from here."""
    u = read()
    u["credit"] = {"usd": round(float(usd), 2), "at": datetime.now().isoformat(timespec="seconds"),
                   "spent_before": u["total_usd"]}
    _save(u)


def credit_left(u: dict) -> float | None:
    c = u.get("credit")
    if not c:
        return None
    return round(c["usd"] - (u["total_usd"] - c.get("spent_before", 0.0)), 4)


NO_LIMIT = 10 ** 9


def files_left_today(cfg: dict, u: dict | None = None) -> int:
    """Files the AI may still look at today (a very large number when the limit is "unlimited")."""
    limit = config.daily_limit(cfg)
    if limit is None:
        return NO_LIMIT
    u = u or read()
    return max(0, limit - u["today_files"])


def block_reason(cfg: dict, u: dict | None = None, files: bool = True) -> str | None:
    """Why the AI must not be used right now (budget, credit, daily file limit when files=True), or None."""
    u = u or read()
    ai = cfg.get("ai", {})
    budget = ai.get("budget_usd", 5.0)
    if u["total_usd"] >= budget:
        return (f"budget reached ({u['total_usd']:.2f} of {budget:.2f} USD) - "
                "after a top-up raise it with: desktidy spend budget <usd>")
    left = credit_left(u)
    if left is not None and left <= ai.get("credit_reserve_usd", 0.10):
        return f"estimated credit almost gone ({left:.2f} USD) - after a top-up: desktidy spend credit <balance>"
    if files and files_left_today(cfg, u) <= 0:
        return (f"daily limit reached ({u['today_files']}/{config.daily_limit(cfg)} files) - "
                "raise it with: desktidy ai max <n|unlimited>")
    return None
