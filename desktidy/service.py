"""The background service: every few seconds it looks at the watched folders and files away what is new.

It starts at sign-in, without a window (Task Scheduler on Windows, a launchd agent on macOS, the desktop's autostart
or a systemd user service on Linux), and is controlled with the `desktidy` command.
Run it in the foreground with:  desktidy-service --dry-run --once --now   (shows what it would do).
"""

from __future__ import annotations

import argparse
import csv
import errno
import hashlib
import logging
import os
import queue
import shutil
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from logging.handlers import RotatingFileHandler

from . import APP_NAME, __version__, classifier, config, folders, naming, system, usage
from . import content as ct

TEMPORARY = {".crdownload", ".part", ".partial", ".download", ".opdownload", ".tmp", ".!ut", ".aria2",
             ".desktidy_tmp"}
IGNORED_NAMES = {"desktop.ini", "thumbs.db", ".ds_store", ".localized", ".directory"}
IGNORED_EXT = {".lnk", ".url", ".desktop", ".webloc", ".inetloc"}  # shortcuts and launchers
JOB_POLL_SECONDS = 45
JOB_GIVE_UP_HOURS = 26

log = logging.getLogger("desktidy")


@dataclass
class Options:
    dry_run: bool = False        # show what would happen, change nothing
    once: bool = False           # one pass, then exit
    no_ai: bool = False
    now: bool = False            # ignore the waiting times (dry runs)
    config_file: str | None = None
    say: object = field(default=print, repr=False)   # where dry-run results go


def setup_logging(opts: Options) -> None:
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S")
    if not opts.dry_run:
        handler = RotatingFileHandler(config.path("log"), maxBytes=2_000_000, backupCount=1, encoding="utf-8")
        handler.setFormatter(fmt)
        log.addHandler(handler)
    if sys.stdout and not opts.dry_run:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        log.addHandler(console)


# ---------------------------------------------------------------- moving files
def _fingerprint(p: str) -> str:
    h = hashlib.blake2b(digest_size=20)
    with open(p, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def find_duplicate(src: str, folder: str) -> str | None:
    """An identical file already in the destination folder (same size and same content)."""
    try:
        size = os.path.getsize(src)
        me = os.path.normcase(os.path.abspath(src))
        same_size = [e.path for e in os.scandir(folder)
                     if e.is_file() and e.stat().st_size == size and os.path.normcase(e.path) != me]
    except OSError:
        return None
    if not same_size:
        return None
    mine = _fingerprint(src)
    return next((c for c in same_size if _fingerprint(c) == mine), None)


def free_name(folder: str, name: str, is_dir: bool) -> str:
    dst = os.path.join(folder, name)
    stem, ext = (name, "") if is_dir else os.path.splitext(name)
    n = 2
    while os.path.exists(dst):
        dst = os.path.join(folder, f"{stem}_v{n}{ext}")
        n += 1
    return dst


def _same_disk(src: str, folder: str) -> bool:
    try:
        return os.lstat(src).st_dev == os.stat(folder).st_dev
    except OSError:
        return False


def move(src: str, folder: str, name: str, is_dir: bool) -> tuple[str, str]:
    """("MOVED", final path) or ("DUPLICATE_TRASHED", the identical file already there)."""
    os.makedirs(folder, exist_ok=True)
    if not is_dir:
        twin = find_duplicate(src, folder)
        if twin:
            if system.recycle(src):
                return "DUPLICATE_TRASHED", twin
            raise OSError(f"duplicate could not be sent to the {system.TRASH}")
    dst = free_name(folder, name, is_dir)
    if _same_disk(src, folder):
        try:
            os.rename(src, dst)
            return "MOVED", dst
        except OSError as ex:
            if ex.errno != errno.EXDEV and getattr(ex, "winerror", None) != 17:
                raise  # 17 = ERROR_NOT_SAME_DEVICE: copied below, like any other disk
    tmp = dst + ".desktidy_tmp"
    if is_dir:
        shutil.copytree(src, tmp)
        os.rename(tmp, dst)
        shutil.rmtree(src)  # the copy is already complete at the destination
    else:
        shutil.copy2(src, tmp)
        if os.path.getsize(tmp) != os.path.getsize(src):
            os.remove(tmp)
            raise OSError("incomplete copy")
        os.replace(tmp, dst)
        try:
            os.remove(src)
        except OSError:
            os.remove(dst)  # the original is locked: try again at the next pass
            raise
    return "MOVED", dst


_record_lock = threading.Lock()
FOLLOWED = {"MOVED", "UNDONE", "ARCHIVED", "ARCHIVED_ZIP", "RECYCLED", "RENAMED"}


def move_id(m: dict) -> str:
    """A short stable id of a moves.csv row (used by the notification buttons and `desktidy undo <id>`)."""
    key = f"{m['time']}|{m['action']}|{m['source']}|{m['destination']}"
    return hashlib.blake2b(key.encode("utf-8"), digest_size=4).hexdigest()


def record(action: str, src: str, dst: str, reason: str) -> str:
    """Log one move (moves.csv) and keep the search index and the deadlines pointing at the file. Returns its id."""
    row = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "action": action, "source": src,
           "destination": dst, "reason": reason}
    file = config.path("moves")
    with _record_lock:
        new = not os.path.exists(file)
        with open(file, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new:
                w.writerow(list(row))
            w.writerow(list(row.values()))
    if action in FOLLOWED:
        from . import deadlines, index
        try:
            if action in ("RECYCLED", "ARCHIVED_ZIP"):
                index.remove(src)
            else:
                index.moved(src, dst)
            deadlines.moved(src, dst)
        except Exception as ex:  # the log line is what matters; a busy index must not lose the move
            log.info(f"ERROR updating the index for {dst}: {ex!r}")
    return move_id(row)


def read_moves() -> list[dict]:
    try:
        with open(config.path("moves"), encoding="utf-8-sig", newline="") as f:
            return [r for r in csv.DictReader(f) if r.get("time")]
    except OSError:
        return []


_today_count: dict = {"stamp": None, "value": 0}


def tidied_today() -> int:
    """Files tidied today (moves.csv), counted again only when the log changes."""
    try:
        st = os.stat(config.path("moves"))
    except OSError:
        return 0
    stamp = (st.st_mtime_ns, st.st_size, date.today())
    if _today_count["stamp"] != stamp:
        today = date.today().isoformat()
        value = sum(1 for m in read_moves() if m["time"].startswith(today) and m["action"] in ("MOVED", "DUPLICATE_TRASHED"))
        _today_count.update(stamp=stamp, value=value)
    return _today_count["value"]


# ---------------------------------------------------------------- the service
class Service:
    def __init__(self, opts: Options):
        self.opts = opts
        self.errors: dict[str, str] = {}
        self.settled: dict[str, tuple] = {}     # items that stay where they are, until they change
        self.questions: queue.Queue = queue.Queue()
        self.asked: set[str] = set()
        self.setup_warned: str | None = None
        self.ai_hold: dict[str, float] = {}     # files gathered for one AI request: when first ready
        self.advising = False                   # organisation advice being prepared in the background
        self.ids: list[str] = []                # moves of the current pass (notification buttons)
        self.last_run: dict[str, float] = {}    # housekeeping: when each periodic task last ran
        self.busy: set[str] = set()             # housekeeping tasks running in the background
        self.cards: set[str] = set()            # memory cards already seen (serial numbers)
        self.limit_said: str | None = None
        self.denied: set[str] = set()           # watched folders the system does not let us read (said once)
        self.stopping = False                   # a stop signal arrived (SIGTERM from launchd, systemd, desktidy stop)
        self.tray = None
        self.state = {"pid": os.getpid(), "version": __version__,
                      "started": datetime.now().isoformat(timespec="seconds"),
                      "date": date.today().isoformat(), "moved_today": 0}

    # ------------------------------------------------ which items to look at
    @staticmethod
    def ignored(entry: os.DirEntry, watched: dict) -> bool:
        name = entry.name.lower()
        if name.startswith("!"):
            return True  # "!" at the start of the name = never tidy
        if name in IGNORED_NAMES or name.startswith(("~$", ".~lock")) or entry.name in watched.get("ignore", []):
            return True
        if os.path.splitext(name)[1] in IGNORED_EXT | TEMPORARY:
            return True
        return system.is_hidden(entry)

    @staticmethod
    def last_change(path: str, is_dir: bool, enough: float | None = None) -> float:
        """Latest change of the item (for a folder, of anything inside). Stops at the first change newer than
        `enough`: a folder still being written is not walked to the end at every pass."""
        st = os.stat(path)
        t = max(st.st_mtime, st.st_ctime)
        if is_dir:
            for root, _, files in os.walk(path):
                for f in files:
                    if os.path.splitext(f)[1].lower() in TEMPORARY:
                        return time.time()
                    try:
                        s = os.stat(os.path.join(root, f))
                        t = max(t, s.st_mtime, s.st_ctime)
                    except OSError:
                        return time.time()
                    if enough is not None and t >= enough:
                        return t
        return t

    def ready(self, path: str, is_dir: bool, wait: int) -> bool:
        if not self.opts.now and time.time() - self.last_change(path, is_dir, time.time() - wait) < wait:
            return False
        if not is_dir:
            if any(os.path.exists(path + e) for e in (".part", ".crdownload", ".download")):
                return False
            if system.file_in_use(path):
                return False
        return True

    @staticmethod
    def is_kept(path: str) -> bool:
        """Restored by `desktidy undo`: left alone until the user changes it."""
        kept = config.read_json_cached(config.path("kept"), [])
        if not kept:
            return False
        key = os.path.normcase(path)
        for entry in kept:
            if os.path.normcase(entry["path"]) == key:
                try:
                    st = os.stat(path)
                except OSError:
                    return False
                if (st.st_size, round(st.st_mtime, 3)) == (entry["size"], round(entry["mtime"], 3)):
                    return True
                config.write_json(config.path("kept"), [k for k in kept if k is not entry])
                return False
        return False

    # ------------------------------------------------ one pass
    def tick(self, cfg: config.Config) -> list[str]:
        missing = folders.setup_missing(cfg)
        self.state["setup_missing"] = missing
        if missing:  # first-run setup not finished: watch only, move nothing
            if self.setup_warned != missing:
                self.setup_warned = missing
                log.info(f"waiting for the setup ({missing}): run  desktidy setup")
            return []
        self.ids = []
        done = [] if self.opts.dry_run else self.finish_jobs(cfg)
        pending = self.pending_paths()
        pinned = folders.active_pinned()
        room = self.room_today(cfg, len(pending))
        for_ai = []
        for watched in cfg["watched_folders"]:
            base = cfg.expand(watched["path"])
            try:
                entries = list(os.scandir(base))
            except PermissionError:
                self.no_access(base)
                continue
            except OSError:
                continue
            for e in entries:
                if room is not None and room <= 0:
                    break  # daily limit reached: the rest waits for tomorrow
                try:
                    if self.ignored(e, watched):
                        continue
                    is_dir = e.is_dir(follow_symlinks=False)
                    if is_dir and (not watched.get("include_folders", False) or folders.holds_pinned(e.path, pinned)):
                        continue  # pinned folders (or folders holding one) are never moved
                    key = os.path.normcase(e.path)
                    st = e.stat()
                    if key in pending or self.settled.get(key) == (st.st_size, st.st_mtime) or self.is_kept(e.path):
                        continue
                    if not self.ready(e.path, is_dir, watched.get("wait_seconds", 120)):
                        continue
                    an = ct.analyze(e.path, is_dir, cfg)
                    d = classifier.decide(e.path, is_dir, cfg, an)
                    plan = naming.plan(an, cfg)
                    if room is not None:
                        room -= 1
                    if classifier.wants_ai(d, an, cfg, self.opts.no_ai):
                        for_ai.append((e.path, is_dir, base, an, d, plan))
                        continue
                    done += self.finish(cfg, e.path, is_dir, base, d.dest, d.reason,
                                        plan.new_stem or plan.fallback, plan.reason, an=an)
                except Exception as ex:
                    self.error(e.path, ex)
        ripe = self.gathered(for_ai, cfg)
        if ripe:
            done += self.dispatch(ripe, cfg)
        return done

    def room_today(self, cfg: config.Config, pending: int = 0) -> int | None:
        """How many more items may be tidied today (limits.files_per_day), None = no limit. Files waiting for an
        AI answer already count."""
        limit = config.tidy_limit(cfg)
        if limit is None or self.opts.dry_run:
            return None
        room = limit - tidied_today() - pending
        today = date.today().isoformat()
        if room <= 0 and self.limit_said != today:
            self.limit_said = today
            log.info(f"daily limit reached ({limit} files): the rest waits for tomorrow (desktidy limit)")
            if not self.opts.once:
                system.notify(f"{APP_NAME}: daily limit reached", f"{limit} files tidied today. The others wait for "
                              "tomorrow. Change it: desktidy limit", [("Settings", "desktidy:status")])
        return max(0, room)

    def gathered(self, for_ai: list[tuple], cfg: config.Config) -> list[tuple]:
        """Files for the AI wait a little (ai.gather_seconds, 90 by default) so that several share one request:
        the instructions and the folder list are paid once, and free plans counting requests last longer.
        They leave together when the oldest has waited enough or a request is full."""
        from . import ai
        now = time.time()
        self.ai_hold = {os.path.normcase(x[0]): self.ai_hold.get(os.path.normcase(x[0]), now) for x in for_ai}
        if not for_ai:
            return []
        wait = cfg.ai.get("gather_seconds", 90)
        if self.opts.dry_run or len(for_ai) >= ai.MAX_FILES_PER_REQUEST or now - min(self.ai_hold.values()) >= wait:
            self.ai_hold = {}
            return for_ai
        if not ai.ready(cfg, log.info) or usage.files_left_today(cfg) <= 0:  # no AI now: no reason to wait
            self.ai_hold = {}
            return for_ai
        return []

    def finish(self, cfg: config.Config, path: str, is_dir: bool, base: str, dest: str | None, reason: str,
               new_stem: str | None, rename_reason: str, an: ct.Analysis | None = None, summary: str = "",
               due: str = "") -> list[str]:
        """Move (and maybe rename) one item; returns the line for the notification. Then the file is added to the
        search index, its deadlines are noted and older versions next to it are pointed out."""
        if not dest:
            dest = cfg.default_destination
            if reason in ("", "no rule matched"):
                reason = "no rule matched: left to sort by hand"
        original = os.path.basename(path)
        name = naming.final_name(original, new_stem, is_dir)
        renamed = new_stem is not None and os.path.splitext(name)[0] != os.path.splitext(config.clean_name(original))[0]
        why = reason + (f"; renamed ({rename_reason})" if renamed and rename_reason else "")
        if os.path.normcase(dest) == os.path.normcase(base):
            st = os.stat(path)
            self.settled[os.path.normcase(path)] = (st.st_size, st.st_mtime)
            return []
        if self.opts.dry_run:
            self.opts.say(f"{original}  ->  {os.path.join(config.short(dest), name)}   ({why})")
            return []
        action, final = move(path, dest, name, is_dir)
        self.ids.append(record(action, path, final, why))
        log.info(f"{action}: {path} -> {final} ({why})")
        self.state["moved_today"] += 1
        self.errors.pop(path, None)
        if action == "DUPLICATE_TRASHED":
            return [f"{original}: duplicate of {os.path.basename(final)}, sent to the {system.TRASH}"]
        if not is_dir:
            self.after_move(cfg, final, an, summary, due)
        return [f"{original} -> {config.short(os.path.dirname(final))}" + (f" as {name}" if renamed else "")]

    def after_move(self, cfg: config.Config, final: str, an: ct.Analysis | None, summary: str, due: str) -> None:
        """Index the file, note its deadlines, point out older versions. Never blocks the move itself."""
        from . import deadlines, index, versions
        try:
            if an is None:  # an AI answer collected after a restart: read the file again, without OCR
                an = ct.analyze(final, False, {"analysis": {"ocr": False}})
            title = naming.title(an) or ""
            if cfg.get("search", {}).get("enabled", True) and os.path.splitext(final)[1].lower() in index.INDEXABLE | \
                    (ct.IMAGE_EXT if an.info.get("ocr") else set()):
                index.add(final, an, summary, title)
            if cfg.get("deadlines", {}).get("enabled", True):
                for d in deadlines.add_for_file(final, an, title, due):
                    log.info(f"DEADLINE {d['date']}: {d['what']}" + (f" ({d['amount']})" if d.get("amount") else ""))
            family = versions.family_of(final)
            if family and not self.opts.once:
                system.notify(f"{APP_NAME}: older versions of {os.path.basename(final)}",
                              f"{len(family.older)} older version(s) in {config.short(family.folder)}. "
                              "Move them aside: desktidy versions", [("Show", "desktidy:versions")])
        except Exception as ex:
            log.info(f"ERROR after moving {final}: {ex!r}")

    # ------------------------------------------------ the AI
    def dispatch(self, items: list[tuple], cfg: config.Config) -> list[str]:
        from . import ai, providers
        key = ai.ready(cfg, log.info)
        allowed = usage.files_left_today(cfg) if key else 0
        done = []
        for path, is_dir, base, _an, d, plan in items[allowed:]:  # beyond the daily limit: offline decision
            done += self.finish(cfg, path, is_dir, base, d.dest, d.reason, plan.new_stem or plan.fallback, plan.reason)
        work = [ai.item_for(path, is_dir, base, an, d, plan, cfg) for path, is_dir, base, an, d, plan in items[:allowed]]
        if work and not providers.current(cfg).vision:  # a text-only service can't judge a picture without text
            blind = [i for i in work if ai.needs_image(i)]
            work = [i for i in work if not ai.needs_image(i)]
            for item in blind:
                done += self.finish_item(item, None, cfg)
        instant = config.ai_delivery(cfg) == "instant" or self.opts.dry_run
        for start in range(0, len(work), ai.MAX_FILES_PER_REQUEST):
            chunk = work[start:start + ai.MAX_FILES_PER_REQUEST]
            if instant:
                answers = ai.ask(chunk, cfg, key, log.info) or {}
                for n, item in enumerate(chunk, 1):
                    done += self.finish_item(item, answers.get(n), cfg)
                continue
            job = ai.submit(chunk, cfg, key, log.info)
            if job:
                data = config.read_json(config.path("jobs"), {"jobs": []})
                data["jobs"].append(job)
                config.write_json(config.path("jobs"), data)
            else:
                for item in chunk:
                    done += self.finish_item(item, None, cfg)
        return done

    def finish_item(self, item, answer, cfg: config.Config) -> list[str]:
        dest, reason = item.dest, item.reason
        accepted = ("high", "medium") if cfg.ai.get("min_confidence") == "medium" else ("high",)
        if answer:
            if answer.confidence in accepted and answer.folder:
                dest, reason = answer.folder, f"AI ({answer.confidence}): {answer.why}"
            elif item.dest is None:
                maybe = f": maybe {folders.label(answer.folder, folders.aliases(cfg))}" if answer.folder else ""
                reason = f"AI unsure ({answer.confidence}){maybe}"
        from . import ai
        ai_name = ai.name_for(item, answer)
        new_stem = item.new_stem or ai_name or item.fallback_stem
        if ai_name and not item.ask_name:
            rename_reason = "the AI found the name didn't match the content"
        else:
            rename_reason = item.rename_reason + ("; name suggested by AI" if ai_name else "")
        return self.finish(cfg, item.path, item.is_dir, item.base, dest, reason, new_stem, rename_reason,
                           an=item.analysis, summary=answer.summary if answer else "", due=answer.due if answer else "")

    @staticmethod
    def pending_paths() -> set[str]:
        data = config.read_json(config.path("jobs"), {"jobs": []})
        return {os.path.normcase(i["path"]) for job in data.get("jobs", []) for i in job["items"]}

    def finish_jobs(self, cfg: config.Config) -> list[str]:
        data = config.read_json(config.path("jobs"), {"jobs": []})
        if not data.get("jobs"):
            return []
        from . import ai
        done, waiting = [], []
        for job in data["jobs"]:
            age_hours = (datetime.now() - datetime.fromisoformat(job["created"])).total_seconds() / 3600
            if age_hours < JOB_GIVE_UP_HOURS and time.time() - job.get("polled", 0) < JOB_POLL_SECONDS:
                waiting.append(job)
                continue
            job["polled"] = time.time()
            finished, answers = ai.collect(job, log.info) if age_hours < JOB_GIVE_UP_HOURS else (True, None)
            if not finished:
                waiting.append(job)
                continue
            for n, raw in enumerate(job["items"], 1):
                item = ai.Item.from_dict(raw)
                try:
                    st = os.stat(item.path)
                except OSError:
                    continue  # moved or deleted meanwhile
                if (st.st_size, st.st_mtime) != (item.size, item.mtime):
                    continue  # edited meanwhile: the next pass decides again
                try:
                    done += self.finish_item(item, (answers or {}).get(n), cfg)
                except Exception as ex:
                    self.error(item.path, ex)
        data["jobs"] = waiting
        config.write_json(config.path("jobs"), data)
        return done

    # ------------------------------------------------ pinned folders: "pin it?"
    def _answer_questions(self) -> None:
        """Thread: one message box at a time, so tidying never waits for the user."""
        while True:
            folder = self.questions.get()
            name = os.path.basename(folder)
            text = (f'You created the folder "{name}" in {config.short(os.path.dirname(folder))}.\n\n'
                    f"PIN it?\nNew files about \"{name}\" (by name or by content) and files similar to the ones "
                    "you put inside will be filed there.\n\nYou can change your mind any time:  desktidy pinned")
            try:
                yes = system.ask_yes_no(text, f"{APP_NAME} - new folder")
                if yes is None or not os.path.isdir(folder):
                    continue  # nobody could answer (no dialog tool): it stays in "desktidy pinned suggest"
                if yes:
                    folders.pin(folder)
                    log.info(f"PINNED: {folder}")
                else:
                    folders.never_ask(folder)
                    log.info(f"not pinned (answered no): {folder}")
            except Exception as ex:
                log.info(f"ERROR asking about {folder}: {ex!r}")

    def suggest_pins(self, cfg: config.Config) -> None:
        if self.opts.dry_run or self.opts.once or not cfg.get("pinned_folders", {}).get("ask", True):
            return
        new = [p for p in folders.suggestions(cfg) if os.path.normcase(p) not in self.asked]
        if not new:
            return
        d = folders.load_pinned()
        d["seen"] += new  # asked once, whatever the answer
        folders.save_pinned(d)
        for p in new:
            self.asked.add(os.path.normcase(p))
            self.questions.put(p)

    # ------------------------------------------------ organisation advice
    def maybe_advise(self, cfg: config.Config) -> None:
        """Once DeskTidy has an overview of your files (ai-only mode, enough files tidied), the AI suggests how to
        organise them better: prepared in the background about once a week, announced with a notification."""
        from . import advice
        if self.opts.dry_run or self.opts.once or self.advising or not advice.due(cfg):
            return
        self.advising = True

        def work():
            try:
                result = advice.generate(cfg, log.info)
                if result and result["tips"]:
                    n = len(result["tips"])
                    system.notify(f"{APP_NAME}: {n} idea{'s' if n > 1 else ''} to organise your files",
                                  "\n".join(t["title"] for t in result["tips"][:3]),
                                  [("See them", "desktidy:advice")], "desktidy:advice")
            except Exception as ex:
                log.info(f"ERROR preparing the organisation advice: {ex!r}")
            finally:
                self.advising = False
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------ housekeeping
    def due(self, name: str, seconds: float) -> bool:
        if time.time() - self.last_run.get(name, 0) < seconds:
            return False
        self.last_run[name] = time.time()
        return True

    def background(self, name: str, work) -> None:
        """Run `work` on its own thread, unless the same task is still running."""
        if name in self.busy:
            return
        self.busy.add(name)

        def wrapper():
            try:
                work()
            except Exception as ex:
                log.info(f"ERROR in {name}: {ex!r}")
            finally:
                self.busy.discard(name)
        threading.Thread(target=wrapper, name=name, daemon=True).start()

    def housekeeping(self, cfg: config.Config) -> None:
        """The periodic jobs: deadline reminders, new memory cards, learning from corrections, the search index,
        the archive and the update check. Each at its own pace; the slow ones in the background."""
        from . import archive, deadlines, importer, index, learn, updates
        if self.opts.dry_run or self.opts.once:
            return
        if self.due("deadlines", 600):
            for d in deadlines.remind(cfg, system.notify):
                log.info(f"REMINDER: {d['what']} due {d['date']}")
        if importer.settings(cfg)["enabled"]:
            self.check_cards(cfg)
        if self.due("learn", 1800):
            def learn_work():
                for p in learn.scan(cfg):
                    rule = p["rule"]
                    log.info(f"LEARNED: a rule for {rule['destination']} from {len(p['examples'])} corrections")
                    system.notify(f"{APP_NAME} learned from your corrections",
                                  f"Files like {', '.join(p['examples'][:2])} go to {os.path.basename(rule['destination'])}."
                                  " Add the rule?", [("Review", "desktidy:learn")])
            self.background("learn", learn_work)
        if self.due("index", 86400) and cfg.get("search", {}).get("enabled", True):
            self.background("index", lambda: log.info(f"search index: {index.refresh(cfg)}"))
        if self.due("archive", 86400) and archive.settings(cfg)["enabled"]:
            def archive_work():
                lines = archive.run(cfg, log.info)
                if lines:
                    system.notify(f"{APP_NAME}: {len(lines)} old item(s) archived", "\n".join(lines[:3]),
                                  [("Show", "desktidy:where")])
            self.background("archive", archive_work)
        if self.due("updates", 3600) and updates.due(cfg):
            self.background("updates", lambda: updates.check(system.notify))

    def check_cards(self, cfg: config.Config) -> None:
        """A memory card with photos was plugged in: offer to import the new ones (or import them, if auto)."""
        from . import importer
        present = importer.cards(cfg)
        for card in present:
            if card["serial"] in self.cards:
                continue
            self.cards.add(card["serial"])
            label = card["label"] or "memory card"

            def work(card=card, label=label):  # reading the dates of many photos takes a while
                new = importer.new_media(card["root"], cfg)
                if not new:
                    return
                if importer.settings(cfg)["auto"]:
                    s = importer.run(card["root"], cfg)
                    log.info(f"IMPORTED {s['copied']} photos/videos from {label}")
                    system.notify(f"{APP_NAME}: {s['copied']} photos/videos imported from {label}",
                                  ", ".join(config.short(f) for f in s["folders"][:3]))
                else:
                    where = label if label == card["name"] else f"{label} ({card['name']})"
                    system.notify(f"{len(new)} new photos/videos on {where}", "Import them into Pictures, sorted by date?",
                                  [("Import", f"desktidy:import?card={card['serial']}"), ("Not now", "desktidy:status")])
            self.background(f"card-{card['serial']}", work)
        self.cards &= {c["serial"] for c in present}  # a card taken out is offered again when it comes back

    def notify_moves(self, lines: list[str]) -> None:
        """One notification for the pass, with Open and Undo buttons."""
        ids = self.ids[-20:]
        if len(lines) == 1 and ids:
            buttons = [("Open", f"desktidy:open?id={ids[-1]}"), ("Undo", f"desktidy:undo?ids={ids[-1]}")]
        else:
            buttons = [("Show", "desktidy:where")] + ([("Undo all", f"desktidy:undo?ids={','.join(ids)}")] if ids else [])
        system.notify(f"{APP_NAME}: {len(lines)} item{'s' if len(lines) > 1 else ''} tidied",
                      "\n".join(lines[:4]) + ("\n..." if len(lines) > 4 else ""), buttons, "desktidy:where")

    def tooltip(self, paused: bool) -> str:
        from . import deadlines
        soon = [d for d in deadlines.upcoming(past_days=0) if deadlines.days_left(d) <= 7]
        state = "paused" if paused else f"{tidied_today()} tidied today"
        return f"{APP_NAME} · {state}" + (f" · {len(soon)} deadline(s) this week" if soon else "")

    # ------------------------------------------------ bookkeeping
    def error(self, path: str, ex: Exception) -> None:
        if self.errors.get(path) != repr(ex):  # don't repeat the same error at every pass
            self.errors[path] = repr(ex)
            log.info(f"ERROR with {path}: {ex!r}")
            self.state["last_error"] = f"{datetime.now():%Y-%m-%d %H:%M} {os.path.basename(path)}: {ex}"

    def save_state(self, **extra) -> None:
        if self.opts.dry_run or self.opts.once:
            return
        if self.state["date"] != date.today().isoformat():
            self.state.update(date=date.today().isoformat(), moved_today=0)
        self.state.update(extra)
        try:
            config.write_json(config.path("state"), self.state)
        except OSError:
            pass

    def no_access(self, folder: str) -> None:
        """The system refuses to let DeskTidy read a watched folder (macOS privacy settings): say how, once."""
        if folder in self.denied:
            return
        self.denied.add(folder)
        how = ("System Settings > Privacy & Security > Files and Folders (or Full Disk Access): allow Python"
               if system.MACOS else "check the folder permissions")
        log.info(f"ERROR: no permission to read {folder}: {how}")
        if not (self.opts.dry_run or self.opts.once):
            system.notify(f"{APP_NAME} can't read {os.path.basename(folder)}", how[0].upper() + how[1:])

    def wait(self, seconds: float) -> bool:
        """Sleep until the next pass; False if a stop was requested meanwhile (STOP file, or a stop signal)."""
        end = time.time() + seconds
        stop = config.path("stop")
        while time.time() < end:
            if self.stopping or os.path.exists(stop):
                return False
            time.sleep(1)
        return not (self.stopping or os.path.exists(stop))

    def _on_signal(self, signum, frame) -> None:
        self.stopping = True  # the current pass ends normally, then the service exits cleanly

    def run(self) -> None:
        if not (self.opts.dry_run or self.opts.once):
            if not system.claim_single_instance(config.SERVICE_MUTEX):
                return
            try:
                os.remove(config.path("stop"))  # a stop request left over from before
            except OSError:
                pass
            if threading.current_thread() is threading.main_thread():
                for name in ("SIGTERM", "SIGHUP"):
                    if hasattr(signal, name):
                        signal.signal(getattr(signal, name), self._on_signal)
            threading.Thread(target=self._answer_questions, daemon=True).start()
            try:
                if config.load_config(self.opts.config_file).get("tray", True):
                    from . import tray
                    self.tray = tray.start()
            except Exception as ex:
                log.info(f"tray icon not available: {ex!r}")
        log.info(f"start v{__version__}" + (" (dry run)" if self.opts.dry_run else ""))
        while True:
            interval = 30
            try:
                cfg = config.load_config(self.opts.config_file)
                interval = cfg.get("interval_seconds", 30)
                paused, _ = paused_until()
                if not paused:
                    lines = self.tick(cfg)
                    if lines and not self.opts.dry_run:
                        self.notify_moves(lines)
                    self.suggest_pins(cfg)
                    self.maybe_advise(cfg)
                self.housekeeping(cfg)
                if self.tray:
                    self.tray.update(self.tooltip(paused))
                self.save_state(last_pass=datetime.now().isoformat(timespec="seconds"), paused=paused,
                                ai_pending=len(self.pending_paths()) + len(self.ai_hold))
            except Exception as ex:
                log.info(f"ERROR: {ex!r}")
                self.save_state(last_error=f"{datetime.now():%Y-%m-%d %H:%M} {ex}")
            if self.opts.dry_run or self.opts.once:
                return
            if not self.wait(interval):
                log.info("stop requested (desktidy stop)")
                if self.tray:
                    self.tray.stop()
                try:
                    os.remove(config.path("stop"))
                except OSError:
                    pass
                self.save_state(stopped=datetime.now().isoformat(timespec="seconds"))
                return


def paused_until() -> tuple[bool, datetime | None]:
    """(paused?, until when or None). An expired pause is removed."""
    file = config.path("pause")
    if not os.path.exists(file):
        return False, None
    try:
        with open(file, encoding="utf-8") as f:
            text = f.read().strip()
    except OSError:
        return True, None
    if text.startswith("until="):
        try:
            until = datetime.fromisoformat(text[6:])
        except ValueError:
            return True, None
        if datetime.now() >= until:
            try:
                os.remove(file)
            except OSError:
                pass
            return False, None
        return True, until
    return True, None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="desktidy-service", description=f"{APP_NAME} background service")
    parser.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument("--no-ai", action="store_true", help="never ask the AI")
    parser.add_argument("--now", action="store_true", help="ignore waiting times (with --dry-run)")
    parser.add_argument("--config", help="use another rules.json")
    a = parser.parse_args(argv)
    opts = Options(a.dry_run, a.once or a.dry_run, a.no_ai, a.now and a.dry_run, a.config)
    setup_logging(opts)
    Service(opts).run()


if __name__ == "__main__":
    main()
