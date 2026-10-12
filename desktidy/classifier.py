"""Where does a file belong? Everything is decided on the PC first; the AI is only consulted when the chosen
AI mode allows it and the offline answer is missing or weak.

Offline decision order:
  0. PINNED folders: the file name contains the folder name (or one of its extra words)
  1. NAME words ("name_words"): exact, then plural/singular, then one typo
  2. CONTENT: strong words ("content_words"), topics ("topics": a few are needed), recognised kinds
     ("recognize": photo, screenshot, code, projects...), pinned folders that the content talks about.
     A "generic" rule (e.g. "notes") found in the name gives way to a confident content match.
  3. SIMILARITY with the names of the files already in each folder (a "weak" decision)
  4. FILE TYPE (rules with "extensions" only)
"""

from __future__ import annotations

import importlib.util
import math
import os
from dataclasses import dataclass, field

from . import config, folders
from . import content as ct

PROGRAMS = {".exe", ".msi", ".msix", ".msixbundle", ".appx", ".appxbundle",   # Windows
            ".dmg", ".pkg",                                                   # macOS
            ".deb", ".rpm", ".appimage", ".flatpakref", ".snap"}              # Linux
ARCHIVES = {".zip", ".7z", ".rar"}
TAG_POINTS = 6.0   # a recognised kind (photo, screenshot, project...) outweighs topics
THRESHOLD = 3.0    # minimum content score for a decision
AI_AVAILABLE = importlib.util.find_spec("anthropic") is not None   # needed only by the Claude provider


@dataclass
class Decision:
    dest: str | None = None
    reason: str = ""
    strength: str = "none"          # strong | weak | none
    private: bool = False
    source: str = ""                # pinned | name | content | similarity | type
    candidates: list = field(default_factory=list)   # [(points, folder, reason)] best first

    @property
    def ranked(self) -> list[str]:
        return [c[1] for c in self.candidates]


def _allowed(dest: str, ext: str, cfg: config.Config) -> bool:
    """Programs only go to the installers folder."""
    return not (ext in PROGRAMS and cfg.installer_dir and not os.path.normcase(dest).startswith(cfg.installer_dir))


def _rules(cfg: config.Config, ext: str) -> list[tuple[dict, str]]:
    out = []
    for r in cfg["rules"]:
        dest = cfg.expand(r["destination"])
        if _allowed(dest, ext, cfg):
            out.append((r, dest))
    return out


def _kind_ok(rule: dict, is_dir: bool) -> bool:
    kind = rule.get("type", "file")
    return kind in ("folder", "both") if is_dir else kind != "folder"


def _ext_ok(rule: dict, an: ct.Analysis) -> bool:
    return an.is_dir or not rule.get("extensions") or an.ext in rule["extensions"]


def rule_score(rule: dict, an: ct.Analysis) -> tuple[float, str]:
    """(points, reason) of the file content for one rule."""
    points, reasons = 0.0, []
    if _kind_ok(rule, an.is_dir) and _ext_ok(rule, an):
        strong = [(w, n) for w in rule.get("content_words", []) if (n := an.count(w))]
        if strong:
            points += sum(3 + min(2.0, math.log2(n)) for _, n in strong)
            reasons.append("text contains " + ", ".join(f"'{w}'" for w, _ in strong[:3]))
        if rule.get("topics") and an.is_document:
            found = [(w, n) for w in rule["topics"] if (n := an.count(w))]
            needed = rule.get("min_topics", 3 if an.words > 150 else 2)
            if len(found) >= needed:
                found.sort(key=lambda x: -x[1])
                points += len(found) + 0.5 * math.log2(1 + sum(n for _, n in found))
                reasons.append("about " + ", ".join(w for w, _ in found[:4]))
    tags = set(rule.get("recognize", [])) & an.tags  # recognised kinds count regardless of type/extension
    if tags:
        points += TAG_POINTS
        reasons.insert(0, "recognised: " + ", ".join(sorted(tags)))
    return points, "; ".join(reasons)


def decide(path: str, is_dir: bool, cfg: config.Config, an: ct.Analysis | None = None) -> Decision:
    an = an or ct.analyze(path, is_dir, cfg)
    rules = _rules(cfg, an.ext)
    pinned = [p for p in folders.active_pinned() if _allowed(p.path, an.ext, cfg) and not config.inside(p.path, path)]

    # 0) pinned folders, by name
    for p in pinned:
        word = p.name_match(an)
        if word:
            return Decision(p.path, f"named like the pinned folder '{word}'", "strong", False, "pinned")

    # 1) name words: exact (as always), then plural/singular, then one typo
    generic, generic_word = None, ""
    for mode in ("exact", "stem", "fuzzy"):
        for r, dest in rules:
            if r.get("name_words") and _kind_ok(r, is_dir) and _ext_ok(r, an):
                word = an.in_name(r["name_words"], mode)
                if word:
                    note = {"exact": "", "stem": " (similar form)", "fuzzy": " (one typo away)"}[mode]
                    d = Decision(dest, f"name contains '{word}'{note}" + (" (private)" if r.get("private") else ""),
                                 "weak" if mode == "fuzzy" else "strong", bool(r.get("private")), "name")
                    if not r.get("generic"):
                        return d
                    if generic is None:
                        generic, generic_word = d, word

    # 2) content
    scored = []
    for i, (r, dest) in enumerate(rules):
        points, reason = rule_score(r, an)
        if points:
            scored.append((points, -i, dest, reason, bool(r.get("private"))))
    for p in pinned:
        points, reason = p.score(an)
        if points:
            scored.append((points + 0.5, 1, p.path, f"pinned folder: {reason}", False))
    scored.sort(reverse=True)
    candidates = [(s[0], s[2], s[3]) for s in scored]
    if scored and scored[0][0] >= THRESHOLD:
        best = scored[0]
        second = next((s[0] for s in scored[1:] if os.path.normcase(s[2]) != os.path.normcase(best[2])), 0)
        strength = "strong" if best[0] >= 4 and best[0] >= 1.5 * second else "weak"
        if generic is None or (strength == "strong" and os.path.normcase(best[2]) != os.path.normcase(generic.dest)):
            note = f" (the name only says '{generic_word}')" if generic else ""
            return Decision(best[2], best[3] + note + (" (private)" if best[4] else ""), strength,
                            best[4] or an.is_private, "content", candidates)
    if generic:
        generic.candidates = candidates
        return generic

    # 3) similarity with the files already in the folders (names only)
    if cfg.get("analysis", {}).get("similarity", True) and an.ext not in PROGRAMS:
        default = cfg.default_destination
        exclude = [cfg.installer_dir] if cfg.installer_dir and an.ext not in ARCHIVES else []
        similar = folders.catalog(cfg, sorted({d for _, d in rules}), default).similar(an, exclude)
        candidates += [(round(s * 10, 2), p, "similar names: " + ", ".join(an.original(w) for w in ws))
                       for s, p, ws in similar[:3]]
        if similar:
            s, p, shared = similar[0]
            runner_up = next((x[0] for x in similar[1:] if not config.inside(x[1], p) and not config.inside(p, x[1])), 0)
            if s >= 0.25 and len(shared) >= 2 and s >= 1.4 * runner_up:
                return Decision(p, "like the files already there (" + ", ".join(an.original(w) for w in shared[:3]) + ")",
                                "weak", an.is_private, "similarity", candidates)

    # 4) file type only
    if not is_dir:
        for r, dest in rules:
            if not (r.get("name_words") or r.get("content_words") or r.get("topics")) \
                    and an.ext in r.get("extensions", []) and _kind_ok(r, False):
                return Decision(dest, f"{an.ext} file", "strong", bool(r.get("private")) or an.is_private, "type",
                                candidates)
    return Decision(None, "no rule matched", "none", an.is_private, "", candidates)


def wants_ai(d: Decision, an: ct.Analysis, cfg: config.Config, no_ai: bool = False) -> bool:
    """Whether the chosen AI mode asks the AI about this file. Programs, photos and screenshots never; private
    documents only in the "all" mode, which the user chose for that."""
    mode = config.ai_mode(cfg)
    claude = cfg.get("ai", {}).get("provider", "claude") == "claude"
    if (claude and not AI_AVAILABLE) or no_ai or mode == "off" or an.ext in PROGRAMS or an.is_private:
        return False
    if mode == config.EVERYTHING:
        return True
    if d.private:
        return False
    if mode == "ai-only":
        return True
    if mode == "moderate":
        return d.strength in ("none", "weak")
    return d.strength == "none"  # limited
