"""Select the LLM provider from configuration."""
from __future__ import annotations

import os
from typing import Optional

from aion.ai.providers.base import LLMProvider
from aion.config import Settings

_override: Optional[LLMProvider] = None
_UNSET = object()
_cached: object = _UNSET


def set_provider_override(provider: Optional[LLMProvider]) -> None:
    """Used by tests to inject a scripted provider."""
    global _override, _cached
    _override = provider
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


def get_provider(settings: Settings) -> Optional[LLMProvider]:
    """Return the configured provider, or None for the deterministic (no-LLM) analyzer."""
    global _cached
    if _override is not None:
        return _override
    if _cached is not _UNSET:
        return _cached  # type: ignore[return-value]
    kind = resolve_provider_kind(settings)
    provider: Optional[LLMProvider]
    if kind == "anthropic":
        from aion.ai.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(settings.anthropic_model, settings.anthropic_effort, settings.llm_timeout_seconds)
    elif kind == "openai_compat":
        from aion.ai.providers.openai_compat import OpenAICompatProvider

        provider = OpenAICompatProvider(settings.openai_base_url, settings.openai_model,
                                        settings.openai_api_key, settings.llm_timeout_seconds)
    elif kind == "none":
        provider = None
    else:
        raise ValueError(f"Unknown AION_LLM_PROVIDER {settings.llm_provider!r}")
    _cached = provider
    return provider
