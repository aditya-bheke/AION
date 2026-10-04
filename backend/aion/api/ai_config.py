"""Choose and test the AI provider from the dashboard (admin only)."""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aion import audit
from aion.ai.providers.base import LLMError, generate_structured
from aion.ai.providers.factory import PRESETS, build_provider, current_config, invalidate_cache
from aion.api.agent import last_agent_seen
from aion.config import settings
from aion.db import get_session
from aion.models import AIProviderConfig, AITask
from aion.secrets_store import SecretsUnavailable, encrypt, hint
from aion.security import Principal, require_role

router = APIRouter(prefix="/api/ai", tags=["ai-provider"])


class ProviderIn(BaseModel):
    preset: str
    model: str = Field(default="", max_length=200)
    base_url: str = Field(default="", max_length=500)
    # None = keep the stored key, "" = remove it, anything else = new key.
    api_key: Optional[str] = Field(default=None, max_length=500)
    effort: str = Field(default="high", pattern="^(low|medium|high|xhigh|max)$")


class _Ping(BaseModel):
    ok: bool
    message: str


def _public(cfg) -> dict:
    """Never returns the key itself - only whether one is set and its last characters."""
    preset = PRESETS.get(cfg.preset, {})
    return {"source": cfg.source, "preset": cfg.preset, "label": preset.get("label", cfg.preset), "kind": cfg.kind,
            "model": cfg.model, "base_url": cfg.base_url, "api_key_set": bool(cfg.api_key),
            "api_key_hint": cfg.api_key_hint or ("(from environment)" if cfg.api_key else ""),
            "effort": cfg.effort, "updated_by": cfg.updated_by}


@router.get("/presets")
def presets(_: Principal = Depends(require_role("viewer"))):
    return [{"id": k, **v} for k, v in PRESETS.items()]


@router.get("/config")
def get_config(session: Session = Depends(get_session), _: Principal = Depends(require_role("viewer"))):
    try:
        cfg = _public(current_config(settings))
    except SecretsUnavailable as exc:
        cfg = {"source": "dashboard", "error": str(exc)}
    pending = session.scalar(select(func.count(AITask.id)).where(AITask.status.in_(["pending", "claimed"])))
    seen = last_agent_seen()
    return {**cfg, "mcp": {"pending_tasks": pending, "agent_token_configured": bool(settings.agent_token),
                           "last_agent_seen_seconds_ago": None if seen is None else int(time.time() - seen)},
            "secret_key_configured": bool(settings.secret_key)}


@router.put("/config")
def put_config(body: ProviderIn, session: Session = Depends(get_session),
               user: Principal = Depends(require_role("admin"))):
    preset = PRESETS.get(body.preset)
    if preset is None:
        raise HTTPException(422, f"Unknown preset {body.preset!r}")
    row = session.get(AIProviderConfig, 1) or AIProviderConfig(id=1, preset=body.preset, kind=preset["kind"])
    kind = preset["kind"]
    model = body.model.strip() or preset.get("default_model", "")
    base_url = (body.base_url.strip() or preset.get("base_url", "")).rstrip("/")
    if kind in ("anthropic", "openai_compat") and not model:
        raise HTTPException(422, "Enter the model id to use")
    if kind == "openai_compat" and not base_url.startswith(("http://", "https://")):
        raise HTTPException(422, "Enter the endpoint base URL (http:// or https://)")

    if body.api_key is not None:
        if body.api_key.strip():
            try:
                row.api_key_encrypted = encrypt(body.api_key.strip())
            except SecretsUnavailable as exc:
                raise HTTPException(409, str(exc))
            row.api_key_hint = hint(body.api_key.strip())
        else:
            row.api_key_encrypted, row.api_key_hint = None, ""
    if row.preset != body.preset and body.api_key is None:
        row.api_key_encrypted, row.api_key_hint = None, ""   # never reuse a key across providers
    if preset["needs_key"] and not row.api_key_encrypted:
        raise HTTPException(422, f"{preset['label']} needs an API key")

    row.preset, row.kind, row.model, row.base_url, row.effort = body.preset, kind, model, base_url, body.effort
    row.updated_by = user.name
    session.add(row)
    audit.record(session, "ai_provider_changed", user.actor, preset=body.preset, kind=kind, model=model,
                 base_url=base_url, api_key=row.api_key_hint or "none")  # the hint only, never the key
    session.commit()      # the provider factory reads the config in its own session
    invalidate_cache()
    return _public(current_config(settings))


@router.delete("/config")
def reset_config(session: Session = Depends(get_session), user: Principal = Depends(require_role("admin"))):
    """Forget the dashboard choice (and its stored key); fall back to backend/.env."""
    row = session.get(AIProviderConfig, 1)
    if row:
        session.delete(row)
    audit.record(session, "ai_provider_reset", user.actor)
    session.commit()
    invalidate_cache()
    return _public(current_config(settings))


@router.post("/test")
def test_provider(user: Principal = Depends(require_role("admin"))):
    """Send a tiny structured request to the configured provider and report the result."""
    cfg = current_config(settings)
    if cfg.kind == "none":
        return {"ok": True, "message": "No LLM configured: AION uses the deterministic analyzer."}
    if cfg.kind == "mcp":
        seen = last_agent_seen()
        if seen is None:
            return {"ok": False, "message": "No AI agent has connected through the MCP connector yet."}
        return {"ok": True, "message": f"An MCP agent was last seen {int(time.time() - seen)} s ago."}
    started = time.monotonic()
    try:
        provider = build_provider(cfg, settings)
        result = generate_structured(provider, "You are a connectivity check. Reply with JSON only.",
                                     'Return {"ok": true, "message": "<one short sentence>"}', _Ping,
                                     max_tokens=300, max_attempts=1)
    except (LLMError, SecretsUnavailable, ValueError) as exc:
        return {"ok": False, "message": str(exc)[:500]}
    return {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000),
            "message": f"{provider.name} answered: {result.output.message[:200]}"}
