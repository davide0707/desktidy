"""The AI: mode, service and key, the AI test, spend, organisation advice."""

from __future__ import annotations

import getpass
import os
import sys
from datetime import date, timedelta

from .. import config, folders, system, usage
from . import ui
from .ui import C, ago, ask, bar, confirm, fail, hint, info, ok, row, title, usd, warn


# ================================================================ commands: AI
def cmd_spend(args):
    sub = args[0].lower() if args else ""
    if sub in ("credit", "balance", "topup"):
        value = args[1] if len(args) > 1 else (ask(f"Balance right now in USD (see {config.BILLING_URL}):")
                                               if ui.INTERACTIVE else "")
        try:
            amount = float(value.replace("$", "").replace(",", "."))
        except ValueError:
            fail("Write the balance in dollars, e.g.  desktidy spend credit 4.85")
            return
        usage.set_credit(amount)
        ok(f"Credit saved: {usd(amount, 2)}. From now on the remainder is estimated automatically.")
        cfg = config.load_config()
        if cfg.ai.get("budget_usd", 5.0) <= usage.read()["total_usd"] + 0.05:
            warn("the spending budget is already reached: raise it with  desktidy spend budget <usd>")
        return
    if sub == "budget":
        value = args[1] if len(args) > 1 else (ask("New total budget in USD:") if ui.INTERACTIVE else "")
        try:
            budget = round(float(value.replace("$", "").replace(",", ".")), 2)
        except ValueError:
            fail("Write a number, e.g.  desktidy spend budget 10")
            return
        config.update_config(lambda d: d.setdefault("ai", {}).__setitem__("budget_usd", budget))
        ok(f"Budget: {usd(budget, 2)} (the AI stops by itself when the total spend reaches it)")
        return
    if sub in ("web", "console", "billing"):
        info(f"Opening {config.BILLING_URL}")
        system.open_path(config.BILLING_URL)
        return

    cfg = config.load_config()
    u = usage.read()
    from .. import providers
    p, model, price = providers.current(cfg), config.ai_model(cfg), providers.prices(cfg)
    title("AI spend")
    if price is None:
        cost = f'{C.Y}price unknown{C.X} (set "price_per_million" in rules.json)'
    elif not any(price):
        cost = f"{C.G}free plan{C.X}"
    else:
        cost = f"${price[0]:g} in / ${price[1]:g} out per million tokens" + ("; batch = half" if p.batch else "")
    row("Model", f"{p.name} · {model}  {C.GR}({cost}{C.GR}){C.X}")
    today = date.today()
    row("Today", f"{usd(u['today_usd'])}   {u['today_files']} files   "
                 f"{C.GR}(limit {config.limit_text(config.daily_limit(cfg))}){C.X}")
    f7, s7 = usage.between(u, (today - timedelta(days=6)).isoformat())
    row("Last 7 days", f"{usd(s7)}   {f7} files")
    fm, sm = usage.between(u, today.replace(day=1).isoformat())
    row("This month", f"{usd(sm)}   {fm} files")
    avg = u["total_usd"] / u["total_files"] if u["total_files"] else 0
    row("Total", f"{C.BOLD}{usd(u['total_usd'])}{C.X}   {u['total_files']} files"
                 + (f"   {C.GR}(avg {usd(avg)} per file){C.X}" if avg else ""))
    budget = cfg.ai.get("budget_usd", 5.0)
    fraction = u["total_usd"] / budget if budget else 1
    row("Budget", f"{bar(fraction)} {fraction:.0%} of {usd(budget, 2)}")
    left = usage.credit_left(u)
    if left is None:
        row("Credit", f"not set  {C.GR}->{C.X} check it ({C.W}desktidy spend web{C.X}) and type it: "
                      f"{C.W}desktidy spend credit 4.85{C.X}")
    else:
        c = u["credit"]
        files = f"  {C.GR}(~{int(left / avg):,} files){C.X}" if avg and left > 0 else ""
        color = C.G if left > 1 else C.Y if left > 0.2 else C.R
        row("Credit", f"{usd(c['usd'], 2)} on {c['at'][:10]}  ->  about {color}{C.BOLD}{usd(left, 2)}{C.X} left{files}")
    if u.get("warning"):
        warn(u["warning"]["text"])
    elif config.ai_mode(cfg) != "off" and (block := usage.block_reason(cfg, u)):
        warn(f"AI paused: {block}")
    days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    values = [u["days"].get(d, {"files": 0, "usd": 0.0}) for d in days]
    top = max((v["usd"] for v in values), default=0) or 1
    print(f"\n  {C.GR}Last 7 days:{C.X}")
    for d, v in zip(days, values):
        length = round(v["usd"] / top * 30)
        print(f"   {d[8:10]}/{d[5:7]} {C.CY}{'█' * length}{C.X}{'▏' if not length else ''} "
              f"{C.GR}{usd(v['usd'])} · {v['files']} files{C.X}")
    hint("\n  Exact figures from the token counts of every answer. Anthropic does not expose the prepaid balance to\n"
         "  API keys: check it with  desktidy spend web  and type it with  desktidy spend credit <usd>.")
    if ui.INTERACTIVE:
        value = ask("Balance you see NOW in the Anthropic console, in USD (Enter = skip, 'web' = open it):")
        if value.lower() == "web":
            system.open_path(config.BILLING_URL)
            value = ask("Balance in USD (Enter = skip):")
        if value:
            cmd_spend(["credit", value])


AI_ALIASES = {
    "off": "off", "none": "off", "no": "off", "disable": "off", "0": "off",
    "limited": "limited", "limit": "limited", "low": "limited", "1": "limited",
    "moderate": "moderate", "medium": "moderate", "2": "moderate",
    "ai-only": "ai-only", "aionly": "ai-only", "only": "ai-only", "3": "ai-only",
    "all": "all", "always": "all", "everything": "all", "sempre": "all", "tutto": "all", "4": "all",
    "rules": "off", "regole": "off", "offline": "off",
}


def provider_table(cfg) -> list:
    """Print the AI services, numbered; returns their ids in the same order."""
    from .. import providers
    current = providers.provider_id(cfg)
    ids = list(providers.PROVIDERS)
    for i, pid in enumerate(ids, 1):
        p = providers.PROVIDERS[pid]
        mark = f"{C.G}●{C.X}" if pid == current else f"{C.GR}○{C.X}"
        if p.free:
            cost = f"{C.G}FREE{C.X} - {p.free}"
        else:
            cost = "your own server: usually free" if p.local else f"{C.Y}paid{C.X}"
        if not p.key_env or p.local:
            key_state = ""
        else:
            key_state = f"  {C.GR}·{C.X} {C.G}key set{C.X}" if system.api_key(p.key_env) else f"  {C.GR}· no key{C.X}"
        print(f"   {mark} {C.W}{i}){C.X} {C.BOLD}{pid:<11}{C.X}{p.name}{key_state}\n"
              f"        {cost}\n        {C.GR}model {p.model or '(set one)'} · {p.privacy}"
              f"{' · reads images' if p.vision else ' · text only'}{C.X}")
    return ids


def choose_provider(pid: str) -> bool:
    from .. import providers
    pid = pid.lower()
    if pid not in providers.PROVIDERS:
        fail(f"Unknown service '{pid}'. Choose: {', '.join(providers.PROVIDERS)}")
        return False

    def change(d):
        ai = d.setdefault("ai", {})
        ai["provider"] = pid
        for k in ("model", "base_url", "vision", "price_per_million"):
            ai.pop(k, None)  # the new service's defaults apply
    config.update_config(change)
    p = providers.PROVIDERS[pid]
    ok(f"AI service: {C.BOLD}{p.name}{C.X} (model {p.model or 'to be set'})" + (f" - {C.G}free{C.X}" if p.free else ""))
    if p.privacy:
        info(p.privacy)
    if pid == "ollama":
        info("Install Ollama from ollama.com, then:  ollama pull " + p.model)
    elif pid == "custom":
        info('Set the server in rules.json: "ai": {"base_url": "http://localhost:1234/v1", "model": "..."}')
    if p.key_env and not system.api_key(p.key_env):
        warn(f"no {p.name} key yet: {C.W}desktidy key{C.X}  (get one at {p.key_url})")
        if ui.INTERACTIVE and confirm("Paste the key now?", default_yes=True):
            cmd_key([])
    return True


def cmd_ai(args):
    from .. import providers
    cfg = config.load_config()
    current = config.ai_mode(cfg)
    sub = args[0].lower() if args else ""
    raw = args[1] if len(args) > 1 else ""
    value = raw.lower()
    if sub in ("test", "benchmark", "prova"):
        return ai_test(cfg, "--dry" in args, "--yes" in args)
    if sub in ("provider", "service", "providers", "services"):
        if raw:
            choose_provider(raw)
            return
        title("AI services")
        ids = provider_table(cfg)
        hint("\n  Free and private: groq (cloud, not used for training) or ollama (on this PC).\n"
             "  Switch with: desktidy ai provider <name>   then: desktidy key")
        if ui.INTERACTIVE:
            choice = ask("Number or name (Enter = keep):").lower()
            if choice:
                choose_provider(ids[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(ids) else choice)
        return
    if sub == "max":
        limit = config.parse_limit(value)
        if value == "auto":
            config.update_config(lambda d: d["ai"].pop("max_files_per_day", None))
            ok(f"AI daily limit: the mode's default ({config.AI_MODES[current][1]} files)")
        elif limit == config.UNLIMITED:
            config.update_config(lambda d: d["ai"].__setitem__("max_files_per_day", config.UNLIMITED))
            ok("The AI may look at any number of files a day (no limit)")
            hint("  The budget still applies: desktidy spend budget <usd>")
        elif isinstance(limit, int):
            config.update_config(lambda d: d["ai"].__setitem__("max_files_per_day", limit))
            ok(f"The AI will look at {limit} files a day at most")
        else:
            fail("Examples:  desktidy ai max 50   ·   desktidy ai max unlimited   ·   desktidy ai max auto")
        return
    if sub == "model":
        if not raw:
            fail("Example: desktidy ai model haiku   (Claude: haiku, sonnet, opus; other services: the model id)")
            return
        model = providers.CLAUDE_MODELS.get(value, raw) if providers.provider_id(cfg) == "claude" else raw
        config.update_config(lambda d: d["ai"].__setitem__("model", model))
        price = providers.prices(config.load_config())
        if price is None:
            ok(f"Model: {model}")
            warn('unknown price: add  "price_per_million": [input, output]  to the ai section of rules.json')
        elif any(price):
            ok(f"Model: {model} (${price[0]:g} / ${price[1]:g} per million tokens)")
        else:
            ok(f"Model: {model} (free plan)")
        return
    if sub == "confidence":
        if value not in ("high", "medium"):
            fail("Type high (only sure answers, recommended) or medium")
            return
        config.update_config(lambda d: d["ai"].__setitem__("min_confidence", value))
        ok(f"AI answers accepted with confidence: {value}" + (" or high" if value == "medium" else ""))
        return
    if sub == "delivery":
        if value not in ("batch", "instant"):
            fail("Type batch (half price, answer in minutes - Claude only) or instant (answer in seconds)")
            return
        config.update_config(lambda d: d["ai"].__setitem__("delivery", value))
        note = "" if providers.current(cfg).batch else " (applies to Claude; the other services always answer at once)"
        ok(f"AI delivery: {value}{note}")
        return
    if not sub:
        p = providers.current(cfg)
        title(f"How much to use the AI ({p.name})")
        for i, (mode, (text, limit)) in enumerate(config.AI_MODES.items()):
            mark = f"{C.G}●{C.X}" if mode == current else f"{C.GR}○{C.X}"
            per_day = f" {C.GR}(max {limit}/day){C.X}" if limit else ""
            print(f"   {mark} {C.W}{i}){C.X} {C.BOLD}{mode:<9}{C.X} {text}{per_day}")
        hint(f"\n  Service {p.id} · model {config.ai_model(cfg)} · delivery {config.ai_delivery(cfg)} · "
             f"min confidence {cfg.ai.get('min_confidence', 'high')}\n"
             "  More: desktidy ai provider (Claude, OpenAI, Gemini, Groq, Mistral, OpenRouter, Ollama)\n"
             "        ai max <n|unlimited>\n"
             "        ai model <name>  ·  ai delivery batch|instant  ·  ai confidence high|medium")
        if not ui.INTERACTIVE:
            return
        sub = ask("New mode (0-4 or name, Enter = keep):").lower()
        if not sub:
            return
    mode = AI_ALIASES.get(sub)
    if not mode:
        fail(f"Unknown mode '{sub}'. Choose: off, limited, moderate, ai-only, all  (or: ai provider)")
        return
    if mode == config.EVERYTHING and current != mode and not confirm_everything(cfg):
        return

    def change(d):
        d.setdefault("ai", {})["mode"] = mode
        d["ai"].pop("max_files_per_day", None)  # the new mode's limit applies
    config.update_config(change)
    text, limit = config.AI_MODES[mode]
    ok(f"AI: {C.BOLD}{mode}{C.X} - {text}" + (f" (max {limit} files/day)" if limit else ""))
    info("Applies from the next pass (within 30 seconds), no restart needed")
    p = providers.current(cfg)
    if mode != "off" and p.key_env and not system.api_key(p.key_env):
        warn(f"no {p.name} key yet: {C.W}desktidy key{C.X}")


def ai_test(cfg, dry: bool = False, yes: bool = False) -> None:
    """desktidy ai test: how well the chosen service sorts and names 18 made-up documents."""
    from .. import ai, evaluate, providers
    p = providers.current(cfg)
    title(f"AI test: {p.name} · {config.ai_model(cfg)}")
    if dry:
        report = evaluate.run(cfg, "", hint, send=False)
        info(f"{report['documents']} made-up documents in {report['requests']} request(s), "
             f"{report['chars']:,} characters (~{report['chars'] // 4:,} tokens). Nothing was sent.")
        return
    key = ai.ready(cfg, print, files=False)
    if not key:
        fail("The AI is not available: choose a service and a key first (desktidy ai provider · desktidy key)")
        return
    price = providers.prices(cfg)
    cost = "free plan" if p.free or p.local else (
        f"about {usd((len(evaluate.CASES) * 700 * price[0] + len(evaluate.CASES) * 90 * price[1]) / 1e6, 3)}"
        if price else "price unknown")
    if not yes and not confirm(f"Send {p.name} {len(evaluate.CASES)} made-up documents (never yours)? ({cost})", True):
        return
    report = evaluate.run(cfg, key, hint)
    def mark(v, width: int) -> str:  # padded before coloring, so the columns line up with and without colors
        return {True: C.G, False: C.R, None: C.GR}[v] + {True: "ok", False: "no", None: "-"}[v].ljust(width) + C.X

    print(f"\n  {'document':<22} {'folder':<7} {'name':<5} {'date':<5} {'due':<5} answer")
    for r in report["results"]:
        print(f"  {r.case.file[:22]:<22} {mark(r.folder_ok, 7)} {mark(r.name_ok, 5)} {mark(r.date_ok, 5)} "
              f"{mark(r.due_ok, 5)} {C.GR}{r.shown}{' · ' + r.name if r.name else ''}{C.X}")
    s = report["summary"]
    if not report["results"]:
        fail("No usable answer (desktidy log errors)")
        return
    print()
    for label, key_ in (("Folders", "folder"), ("Names", "name"), ("Document dates", "date"), ("Deadlines", "due")):
        good, total = s[key_]
        row(label, f"{good}/{total}" + (f"  ({100 * good // total}%)" if total else ""))
    row("Time", f"{report['seconds']} s, {report['requests']} request(s)")
    hint("  The spend is in: desktidy spend. Compare services: desktidy ai provider <name>, then desktidy ai test.")


def confirm_everything(cfg) -> bool:
    """Before private documents start going to the AI: say where they go, and ask when someone can answer."""
    from .. import providers
    p = providers.current(cfg)
    if p.local:
        info(f"Always AI with {p.name}: the AI runs on this PC, your documents never leave it")
        return True
    warn(f"Always AI: bills, payslips, IDs and other private documents will be sent to {C.BOLD}{p.name}{C.X} "
         f"(an excerpt of each). {p.privacy}".rstrip())
    from .. import redact
    if redact.wanted(cfg):
        hint("  IBANs, card numbers, tax codes, VAT numbers, e-mails and phone numbers are masked before sending;\n"
             "  names and addresses are not.")
    else:
        warn("Masking is off (ai.redact: false): IBANs, tax codes and phone numbers are sent as they are.")
    hint("  To keep them on this PC, use Ollama: desktidy ai provider ollama. Photos and screenshots are never sent.")
    if not (ui.INTERACTIVE or sys.stdin.isatty()):
        return True  # typed as a command: that is the choice
    return confirm("Send them to the AI?", False)


def cmd_key(args):
    from .. import providers
    cfg = config.load_config()
    p = providers.current(cfg)
    if not p.key_env:
        info(f"{p.name} needs no API key." + (" Make sure Ollama is running." if p.id == "ollama" else ""))
        _test_key(None, cfg)
        return
    sub = args[0] if args else ""
    current = system.api_key(p.key_env)
    if sub.lower() in ("remove", "delete", "clear"):
        system.set_api_key(None, p.key_env)
        ok(f"{p.name} key removed")
        return
    if sub.lower() in ("test", "check"):
        if not current:
            fail(f"No {p.name} key set")
            return
        _test_key(current, cfg)
        return
    new = sub
    if not new:
        info(f"{p.name} key ({p.key_env}): {system.mask(current)}  {C.GR}(kept in {system.KEYS_WHERE}){C.X}")
        if not ui.INTERACTIVE and not sys.stdin.isatty():
            hint("Usage: desktidy key <NEW-KEY>   ·   desktidy key test   ·   desktidy key remove\n"
                 "  (for another service first: desktidy ai provider <name>)")
            return
        if p.key_url:
            info(f"Get one at {p.key_url} (it stays hidden while you paste it)")
        try:
            new = getpass.getpass(f"  {C.CY}[?]{C.X} Paste the new {p.name} key (Enter = cancel): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not new:
            return
    looks_wrong = p.id == "claude" and not new.startswith("sk-ant-")
    if looks_wrong and not confirm("Claude keys start with 'sk-ant-'. Save it anyway?"):
        return
    if _test_key(new, cfg) is False and not confirm("The key was rejected. Save it anyway?"):
        return
    system.set_api_key(new, p.key_env)
    usage.clear_warning()
    ok(f"{p.name} key saved ({system.mask(new)}). The service uses it right away, no restart needed.")


def _test_key(key: str | None, cfg) -> bool | None:
    from .. import ai, providers
    p = providers.current(cfg)
    if not ai.available(cfg):
        warn("the anthropic library is not installed: pip install anthropic")
        return None
    info(f"Checking with {p.name} (free)...")
    valid, message = ai.check_key(key, cfg)
    (ok if valid else fail if valid is False else warn)(message)
    return valid


def print_tips(data: dict) -> None:
    from ..ops import AUTOMATIC
    for i, t in enumerate(data.get("tips", []), 1):
        auto = f"  {C.G}(advice apply {i}){C.X}" if t["kind"] in AUTOMATIC and t.get("paths") else ""
        print(f"\n   {C.W}{i}){C.X} {C.CY}[{t['kind']}]{C.X} {C.BOLD}{t['title']}{C.X}{auto}")
        if t.get("detail"):
            print(f"      {t['detail']}")
        for p in t.get("paths", [])[:4]:
            print(f"      {C.GR}-> {config.short(p)}{C.X}")
        if t.get("new_name"):
            print(f"      {C.GR}new name: {t['new_name']}{C.X}")


def cmd_advice(args):
    """Tips to organise files and folders better: from the AI (automatic in ai-only mode) plus offline findings."""
    from .. import advice
    sub = args[0].lower() if args else ""
    cfg = config.load_config()
    if sub in ("new", "now", "refresh", "ask"):
        from .. import ai, providers
        p = providers.current(cfg)
        key = ai.ready(cfg, print, files=False)
        if not key:
            fail("The AI is not available: choose a service and a key first (desktidy ai provider · desktidy key)")
            return
        price = "free plan" if p.free or p.local else "about $0.005"
        if (ui.INTERACTIVE or sys.stdin.isatty()) and not confirm(
                f"Send {p.name} the names of your folders and a few file names (never the content)? ({price})", True):
            return
        info("Looking at your folders...")
        result = advice.generate(cfg, lambda m: hint(m), key)
        if not result:
            fail("No usable answer (desktidy log errors)")
            return
        data = result
    elif sub in ("open", "show") and len(args) > 1 or sub.isdigit():
        n = args[1] if len(args) > 1 else sub
        tips = advice.load().get("tips", [])
        tip = tips[int(n) - 1] if n.isdigit() and 1 <= int(n) <= len(tips) else None
        if not tip or not tip["paths"]:
            fail(f"Tip {n} has no folder to open")
            return
        system.open_path(tip["paths"][0])
        return
    elif sub == "pin":
        tips = advice.load().get("tips", [])
        n = args[1] if len(args) > 1 else ""
        tip = tips[int(n) - 1] if n.isdigit() and 1 <= int(n) <= len(tips) else None
        if not tip or not tip["paths"]:
            fail("Usage: desktidy advice pin <tip number>   (pins the first folder of that tip)")
            return
        folders.pin(tip["paths"][0])
        ok(f"Pinned {C.BOLD}{os.path.basename(tip['paths'][0])}{C.X}")
        return
    elif sub == "apply":
        return apply_tip(args[1] if len(args) > 1 else "", cfg, "--yes" in args)
    elif sub == "undo":
        from .. import ops
        entry = ops.undo_last(cfg)
        if entry:
            ok(f"Undone: {C.BOLD}{entry['title']}{C.X} ({len(entry['steps']) - len(entry['skipped'])} step(s) "
               "reverted, rules and pinned folders restored)")
            for s in entry["skipped"]:
                warn(f"could not revert: {s}")
        else:
            info("No applied tip to undo")
        return
    else:
        data = advice.load()
    title("Organisation advice")
    if data.get("tips"):
        hint(f"From {data.get('service', 'the AI')} · {data.get('model', '')} · {ago(data.get('at'))}. "
             "Nothing is changed for you: these are ideas.")
        print_tips(data)
    elif sub not in ("new", "now", "refresh", "ask"):
        if advice.enabled(cfg):
            need = cfg.ai.get("advice_after_files", 30)
            info(f"No AI advice yet: it comes by itself once DeskTidy has an overview of your files "
                 f"({advice.moved_count()}/{need} files tidied). Ask now: {C.W}desktidy advice new{C.X}")
        else:
            info(f"No AI advice yet. Ask now: {C.W}desktidy advice new{C.X}  (automatic in mode ai-only)")
    findings = advice.overview(cfg).findings
    if findings:
        print(f"\n  {C.GR}Seen on this PC (offline, now):{C.X}")
        for f in findings:
            warn(f)
    hint("\n  desktidy advice new · advice apply <n> (do it, after a preview) · advice undo · advice open <n> "
         f"({system.FILE_MANAGER}) · advice pin <n>")
    if ui.INTERACTIVE and data.get("tips"):
        n = ask(f"Number to open in {system.FILE_MANAGER}, 'a' + number to apply it (Enter = back):")
        n = n.lower().replace(" ", "")
        if n.isdigit():
            cmd_advice(["open", n])
        elif n.startswith("a") and n[1:].isdigit():
            apply_tip(n[1:], cfg)


def apply_tip(n: str, cfg, yes: bool = False) -> None:
    """Show what a tip would do, then do it (undoable with: desktidy advice undo)."""
    from .. import advice, ops
    tips = advice.load().get("tips", [])
    if not (n.isdigit() and 1 <= int(n) <= len(tips)):
        fail("Usage: desktidy advice apply <tip number>   (see: desktidy advice)")
        return
    tip = tips[int(n) - 1]
    plan = ops.plan(tip, cfg)
    title(f"Apply: {tip['title']}")
    for p in plan.problems:
        fail(p)
    if not plan.ok:
        hint("  Nothing was changed.")
        return
    moves = [s for s in plan.steps if s["op"] == "move"]
    for step in plan.steps[:25]:
        print(f"   {C.CY}·{C.X} {ops.describe(step)}")
    if len(plan.steps) > 25:
        print(f"   {C.GR}... and {len(plan.steps) - 25} more{C.X}")
    hint(f"\n  {len(moves)} move(s). Files are never deleted; rules and pinned folders follow the folders.")
    if not yes and not confirm("Do it?", default_yes=False):
        return
    try:
        entry = ops.apply(plan, cfg, tip)
    except Exception as ex:
        fail(f"Stopped and rolled back: {ex}")
        return
    updated = f", {len(entry['changes'])} setting(s) updated" if entry["changes"] else ""
    ok(f"Done: {len(entry['steps'])} step(s){updated}")
    info(f"Changed your mind? {C.W}desktidy advice undo{C.X}")
