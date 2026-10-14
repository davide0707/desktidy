# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Di Filippo Davide
"""The AI services DeskTidy can use. Claude is called through its official SDK; every other service speaks the
OpenAI-compatible chat API, so one small HTTP client (standard library only) covers them all.

Free options (October 2026): Groq (free plan, prompts not used for training), Google Gemini (free tier on the
Flash models), Mistral (free "Experiment" plan), OpenRouter (":free" models) and Ollama (runs on your own PC).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from urllib.parse import urlsplit

from . import config


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    kind: str                     # "anthropic" or "openai" (OpenAI-compatible chat completions)
    model: str                    # default model
    base_url: str = ""
    key_env: str | None = None    # user environment variable holding the key (None: no key needed)
    key_url: str = ""
    free: str = ""                # what is free ("" = paid)
    privacy: str = ""
    vision: bool = False          # can read images
    batch: bool = False           # half-price batch API supported by DeskTidy
    tokens_param: str = "max_tokens"
    reasoning_room: int = 0       # extra output tokens for models that think before answering
    extra: dict = field(default_factory=dict)   # extra request fields (dropped automatically if refused)
    local: bool = False


PROVIDERS: dict[str, Provider] = {p.id: p for p in [
    Provider("claude", "Anthropic Claude", "anthropic", "claude-haiku-4-5", key_env="ANTHROPIC_API_KEY",
             key_url="https://platform.claude.com/settings/keys",
             privacy="API data is not used for training", vision=True, batch=True),
    Provider("groq", "Groq", "openai", "openai/gpt-oss-20b", "https://api.groq.com/openai/v1", "GROQ_API_KEY",
             "https://console.groq.com/keys", free="free plan: about 1,000 requests a day, no card",
             privacy="prompts are not used for training", reasoning_room=1200, extra={"reasoning_effort": "low"}),
    Provider("gemini", "Google Gemini", "openai", "gemini-3.5-flash-lite",
             "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY",
             "https://aistudio.google.com/apikey", free="free tier on the Flash and Flash-Lite models",
             privacy="free tier: Google may use prompts to improve its products", vision=True, reasoning_room=800),
    Provider("mistral", "Mistral", "openai", "mistral-small-latest", "https://api.mistral.ai/v1", "MISTRAL_API_KEY",
             "https://console.mistral.ai/api-keys", free="free Experiment plan (phone verification)",
             privacy="free plan: prompts may be used for training", vision=True),
    Provider("openrouter", "OpenRouter", "openai", "google/gemma-4-31b-it:free", "https://openrouter.ai/api/v1",
             "OPENROUTER_API_KEY", "https://openrouter.ai/keys",
             free="':free' models: 50 requests a day (1,000 after a $10 top-up)",
             privacy="free models: the hosting provider may log prompts"),
    Provider("ollama", "Ollama (on this PC)", "openai", "gemma3:4b", "http://localhost:11434/v1", None,
             "https://ollama.com/download", free="free and offline: runs on your own PC",
             privacy="nothing leaves your PC", vision=True, local=True),
    Provider("openai", "OpenAI", "openai", "gpt-5-nano", "https://api.openai.com/v1", "OPENAI_API_KEY",
             "https://platform.openai.com/api-keys", privacy="API data is not used for training by default",
             vision=True, tokens_param="max_completion_tokens", reasoning_room=600,
             extra={"reasoning_effort": "minimal"}),
    Provider("custom", "Any OpenAI-compatible server (LM Studio, vLLM...)", "openai", "",
             "http://localhost:1234/v1", "DESKTIDY_CUSTOM_API_KEY", "",
             privacy="depends on the server", local=True),
]}
CLAUDE_MODELS = {"haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}


def provider_id(cfg: dict) -> str:
    pid = cfg.get("ai", {}).get("provider", "claude")
    return pid if pid in PROVIDERS else "claude"


def on_this_pc(url: str) -> bool:
    """A server address on this computer (localhost, 127.x, ::1): what is sent there never leaves the PC."""
    host = (urlsplit(url).hostname or "").lower()
    return host in ("localhost", "::1") or host.startswith("127.") or host.endswith(".localhost")


def current(cfg: dict) -> Provider:
    """The chosen provider, with the overrides from rules.json (ai.base_url, ai.vision). A local service moved to
    another machine with ai.base_url is not local any more (privacy notices and masking depend on it)."""
    p = PROVIDERS[provider_id(cfg)]
    ai = cfg.get("ai", {})
    changes = {}
    if ai.get("base_url"):
        changes["base_url"] = ai["base_url"].rstrip("/")
        if p.local and not on_this_pc(changes["base_url"]):
            changes["local"] = False
    if isinstance(ai.get("vision"), bool):
        changes["vision"] = ai["vision"]
    return replace(p, **changes) if changes else p


def model(cfg: dict) -> str:
    p = current(cfg)
    chosen = cfg.get("ai", {}).get("model") or p.model
    return CLAUDE_MODELS.get(chosen, chosen) if p.kind == "anthropic" else chosen


def prices(cfg: dict) -> tuple[float, float] | None:
    """USD per million tokens (input, output); (0, 0) on free plans; None when unknown."""
    override = cfg.get("ai", {}).get("price_per_million")
    if isinstance(override, list) and len(override) == 2:
        return float(override[0]), float(override[1])
    m = model(cfg)
    if m in config.PRICES:
        return config.PRICES[m]
    p = current(cfg)
    return (0.0, 0.0) if p.free or p.local else None
