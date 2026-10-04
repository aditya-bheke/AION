"""Select the LLM provider.

Source of truth, in order:
  1. a test override (set_provider_override)
  2. the provider chosen in the dashboard (table ai_provider_config, API key encrypted)
  3. environment variables / backend/.env (AION_LLM_PROVIDER, ANTHROPIC_API_KEY, AION_OPENAI_*)
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Optional

from aion.ai.providers.base import LLMProvider
from aion.config import Settings

# Presets shown in the dashboard. Model ids are typed by the admin (except local
# defaults), because hosted providers rename models over time.
PRESETS: dict[str, dict] = {
    "none": {"label": "No LLM (deterministic analyzer + revert)", "kind": "none", "needs_key": False},
    "anthropic": {"label": "Anthropic Claude (API key)", "kind": "anthropic", "needs_key": True,
                  "default_model": "claude-opus-5-5"},
    "openai": {"label": "OpenAI (API key)", "kind": "openai_compat", "needs_key": True,
               "base_url": "https://api.openai.com/v1"},
    "groq": {"label": "Groq (API key)", "kind": "openai_compat", "needs_key": True,
             "base_url": "https://api.groq.com/openai/v1"},
    "openrouter": {"label": "OpenRouter (API key)", "kind": "openai_compat", "needs_key": True,
                   "base_url": "https://openrouter.ai/api/v1"},
    "gemini": {"label": "Google Gemini (API key, OpenAI-compatible endpoint)", "kind": "openai_compat",
               "needs_key": True, "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    "ollama": {"label": "Local: Ollama", "kind": "openai_compat", "needs_key": False,
               "base_url": "http://127.0.0.1:11434/v1", "default_model": "qwen2.5-coder:7b"},
    "lmstudio": {"label": "Local: LM Studio", "kind": "openai_compat", "needs_key": False,
                 "base_url": "http://127.0.0.1:1234/v1"},
    "custom": {"label": "Custom OpenAI-compatible endpoint", "kind": "openai_compat", "needs_key": False},
    "mcp": {"label": "MCP connector (an AI agent such as Claude Code / Claude Desktop answers)", "kind": "mcp",
            "needs_key": False},
}


@dataclass
class ResolvedConfig:
    source: str                 # "dashboard" | "environment"
    preset: str
    kind: str
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    api_key_hint: str = ""
    effort: str = "high"
    updated_by: str = ""


_override: Optional[LLMProvider] = None
_UNSET = object()
_cached: object = _UNSET
_lock = threading.Lock()


def set_provider_override(provider: Optional[LLMProvider]) -> None:
    """Used by tests to inject a scripted provider."""
    global _override
    _override = provider
    invalidate_cache()


def invalidate_cache() -> None:
    global _cached
    with _lock:
        _cached = _UNSET


def resolve_provider_kind(settings: Settings) -> str:
    kind = settings.llm_provider.lower()
    if kind != "auto":
        return kind
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if settings.openai_base_url and settings.openai_model:
        return "openai_compat"
    return "none"


def _from_dashboard() -> Optional[ResolvedConfig]:
    from aion.db import _SessionLocal, session_scope
    from aion.models import AIProviderConfig
    from aion.secrets_store import decrypt

    if _SessionLocal is None:  # database not initialised (e.g. a bare script)
        return None
    with session_scope() as s:
        row = s.get(AIProviderConfig, 1)
        if row is None:
            return None
        key = decrypt(row.api_key_encrypted) if row.api_key_encrypted else ""
        return ResolvedConfig("dashboard", row.preset, row.kind, row.model, row.base_url, key,
                              row.api_key_hint, row.effort, row.updated_by)


def _from_environment(settings: Settings) -> ResolvedConfig:
    kind = resolve_provider_kind(settings)
    if kind == "anthropic":
        return ResolvedConfig("environment", "anthropic", kind, settings.anthropic_model, "",
                              os.getenv("ANTHROPIC_API_KEY", ""), "", settings.anthropic_effort)
    if kind == "openai_compat":
        return ResolvedConfig("environment", "custom", kind, settings.openai_model, settings.openai_base_url,
                              settings.openai_api_key)
    if kind == "mcp":
        return ResolvedConfig("environment", "mcp", kind)
    return ResolvedConfig("environment", "none", "none")


def current_config(settings: Settings) -> ResolvedConfig:
    return _from_dashboard() or _from_environment(settings)


def build_provider(cfg: ResolvedConfig, settings: Settings) -> Optional[LLMProvider]:
    if cfg.kind == "anthropic":
        from aion.ai.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg.model or settings.anthropic_model, cfg.effort or "high",
                                 settings.llm_timeout_seconds, api_key=cfg.api_key or None)
    if cfg.kind == "openai_compat":
        from aion.ai.providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(cfg.base_url, cfg.model, cfg.api_key, settings.llm_timeout_seconds,
                                    settings.openai_max_tokens)
    if cfg.kind == "mcp":
        from aion.ai.providers.mcp_bridge import MCPBridgeProvider

        return MCPBridgeProvider()
    if cfg.kind == "none":
        return None
    raise ValueError(f"Unknown LLM provider kind {cfg.kind!r}")


def get_provider(settings: Settings) -> Optional[LLMProvider]:
    """Return the configured provider, or None for the deterministic (no-LLM) analyzer."""
    global _cached
    if _override is not None:
        return _override
    with _lock:
        if _cached is not _UNSET:
            return _cached  # type: ignore[return-value]
    provider = build_provider(current_config(settings), settings)
    with _lock:
        _cached = provider
    return provider
