"""Photos and videos from a memory card or USB stick: when one with a DCIM folder is plugged in, DeskTidy offers to
import the new pictures (notification with an "Import" button), sorted by the date they were taken:
Pictures\\2026\\2026-10\\IMG_2034.jpg, Videos\\2026\\2026-10\\MVI_0042.mp4.

  desktidy import [E:]          preview, then import (asks first)
  desktidy import auto on|off   import without asking

Safe: files are COPIED (the card is never changed unless import.delete_after is true), each copy is checked by size
before it counts, and what was already imported (from any card) is skipped. Photos never go to the AI.
Phones connected by cable (MTP) have no drive letter: copy from them by hand, or use the phone's own app.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime

from . import config, winapi
from . import content as ct

RAW_EXT = {".dng", ".raw", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".raf"}
PHOTO_EXT = (ct.IMAGE_EXT - {".ico", ".gif", ".bmp"}) | RAW_EXT
VIDEO_EXT = ct.VIDEO_EXT | {".mts", ".m2ts"}
DEFAULT = {"enabled": True, "ask": True, "auto": False, "photos": "{HOME}\\Pictures", "videos": "{HOME}\\Videos",
           "pattern": "{year}\\{year}-{month}", "delete_after": False, "folders": ["DCIM"]}


@dataclass
class Media:
    path: str
    size: int
    taken: datetime
    video: bool

    @property
    def key(self) -> str:
        return f"{os.path.basename(self.path).lower()}|{self.size}|{self.taken:%Y%m%d%H%M%S}"


def settings(cfg: dict) -> dict:
    return {**DEFAULT, **cfg.get("import", {})}


def _taken(path: str) -> datetime:
    """When the picture was taken (EXIF), otherwise the file's own date."""
    if os.path.splitext(path)[1].lower() in ct.IMAGE_EXT:
        try:
            from PIL import Image
            with Image.open(path) as im:
                exif = im.getexif()
                raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
            if raw:
                return datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S")
        except Exception:
            pass
    return datetime.fromtimestamp(os.path.getmtime(path))


def media_on(root: str, cfg: dict) -> list[Media]:
    out = []
    for name in settings(cfg)["folders"]:
        top = os.path.join(root, name)
        for folder, subdirs, files in os.walk(top):
            subdirs[:] = [d for d in subdirs if not d.startswith(".")]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in PHOTO_EXT or ext in VIDEO_EXT:
                    p = os.path.join(folder, f)
                    try:
                        out.append(Media(p, os.path.getsize(p), _taken(p), ext in VIDEO_EXT))
                    except OSError:
                        continue
    return sorted(out, key=lambda m: m.taken)


def imported_keys() -> set[str]:
    data = config.read_json(config.path("imports"), {})
    return set(data.get("keys", [])) if isinstance(data, dict) else set()


def new_media(root: str, cfg: dict) -> list[Media]:
    done = imported_keys()
    return [m for m in media_on(root, cfg) if m.key not in done]


def cards(cfg: dict) -> list[dict]:
    """Removable drives with a DCIM (or configured) folder."""
    names = settings(cfg)["folders"]
    return [d for d in winapi.removable_drives() if any(os.path.isdir(os.path.join(d["root"], n)) for n in names)]


def target_for(m: Media, cfg: config.Config) -> str:
    s = settings(cfg)
    base = cfg.folder(s["videos"] if m.video else s["photos"])
    sub = s["pattern"].format(year=m.taken.year, month=f"{m.taken.month:02d}", day=f"{m.taken.day:02d}")
    return os.path.join(base, sub)


def run(root: str, cfg: config.Config, progress=None) -> dict:
    """Copy the new photos and videos of a card. Returns {"copied", "bytes", "skipped", "failed", "folders"}."""
    from .service import free_name
    s = settings(cfg)
    data = config.read_json(config.path("imports"), {})
    data = data if isinstance(data, dict) else {}
    keys = set(data.get("keys", []))
    stats = {"copied": 0, "bytes": 0, "skipped": 0, "failed": 0, "folders": set()}
    for m in media_on(root, cfg):
        if m.key in keys:
            stats["skipped"] += 1
            continue
        folder = target_for(m, cfg)
        os.makedirs(folder, exist_ok=True)
        name = os.path.basename(m.path)
        existing = os.path.join(folder, name)
        if os.path.exists(existing) and os.path.getsize(existing) == m.size:
            keys.add(m.key)
            stats["skipped"] += 1
            continue
        target = free_name(folder, name, False)
        tmp = target + ".desktidy_tmp"
        try:
            shutil.copy2(m.path, tmp)
            if os.path.getsize(tmp) != m.size:
                raise OSError("incomplete copy")
            os.replace(tmp, target)
        except OSError:
            stats["failed"] += 1
            try:
                os.remove(tmp)
            except OSError:
                pass
            continue
        keys.add(m.key)
        stats["copied"] += 1
        stats["bytes"] += m.size
        stats["folders"].add(folder)
        if s["delete_after"]:
            try:
                os.remove(m.path)
            except OSError:
                pass
        if progress:
            progress(stats["copied"], m)
        if stats["copied"] % 50 == 0:  # a long import interrupted keeps what was done
            config.write_json(config.path("imports"), {**data, "keys": sorted(keys)})
    data.update(keys=sorted(keys), last=datetime.now().isoformat(timespec="seconds"))
    config.write_json(config.path("imports"), data)
    stats["folders"] = sorted(stats["folders"])
    return stats
