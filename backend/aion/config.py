"""Central configuration for AION.

All settings come from environment variables (optionally loaded from
`backend/.env`). Nothing secret is ever hard-coded in source.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass
class Settings:
    # --- storage ---
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "AION_DATABASE_URL", f"sqlite:///{(REPO_ROOT / 'workspace' / 'aion.db').as_posix()}"
        )
    )
    workspace_dir: Path = field(
        default_factory=lambda: Path(os.getenv("AION_WORKSPACE_DIR", str(REPO_ROOT / "workspace")))
    )

    # --- LLM provider ---
    # "auto" picks anthropic if ANTHROPIC_API_KEY is set, else openai_compat if
    # AION_OPENAI_BASE_URL is set, else "none" (deterministic heuristic analyzer).
    llm_provider: str = field(default_factory=lambda: os.getenv("AION_LLM_PROVIDER", "auto"))
    anthropic_model: str = field(default_factory=lambda: os.getenv("AION_ANTHROPIC_MODEL", "claude-opus-5-5"))
    anthropic_effort: str = field(default_factory=lambda: os.getenv("AION_ANTHROPIC_EFFORT", "high"))
    openai_base_url: str = field(default_factory=lambda: os.getenv("AION_OPENAI_BASE_URL", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("AION_OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.getenv("AION_OPENAI_MODEL", ""))
    openai_max_tokens: int = field(default_factory=lambda: _int("AION_OPENAI_MAX_TOKENS", 4096))
    llm_timeout_seconds: int = field(default_factory=lambda: _int("AION_LLM_TIMEOUT", 300))

    # --- incident detection ---
    detection_window_seconds: int = field(default_factory=lambda: _int("AION_DETECTION_WINDOW", 60))
    detection_min_count: int = field(default_factory=lambda: _int("AION_DETECTION_MIN_COUNT", 5))
    detection_baseline_seconds: int = field(default_factory=lambda: _int("AION_DETECTION_BASELINE", 1800))
    detection_spike_ratio: float = field(default_factory=lambda: float(os.getenv("AION_DETECTION_SPIKE_RATIO", "3.0")))

    # --- pipeline ---
    auto_pipeline: bool = field(default_factory=lambda: _bool("AION_AUTO_PIPELINE", True))
    max_patch_attempts: int = field(default_factory=lambda: _int("AION_MAX_PATCH_ATTEMPTS", 2))
    # After all AI patch attempts fail validation, try reverting the RCA's suspected commit.
    revert_fallback: bool = field(default_factory=lambda: _bool("AION_REVERT_FALLBACK", True))
    collector_interval_seconds: float = field(
        default_factory=lambda: float(os.getenv("AION_COLLECTOR_INTERVAL", "2.0"))
    )
    enable_background: bool = field(default_factory=lambda: _bool("AION_ENABLE_BACKGROUND", True))

    # --- validation ---
    test_timeout_seconds: int = field(default_factory=lambda: _int("AION_TEST_TIMEOUT", 180))
    staging_port: int = field(default_factory=lambda: _int("AION_STAGING_PORT", 8201))

    # --- security ---
    # Shared secret for machine clients (log shippers, CI, the demo driver). Required for
    # POST /api/services, /api/deployments and /api/ingest/*. Empty = machine endpoints disabled.
    service_token: str = field(default_factory=lambda: os.getenv("AION_SERVICE_TOKEN", ""))
    session_hours: int = field(default_factory=lambda: _int("AION_SESSION_HOURS", 12))
    password_iterations: int = field(default_factory=lambda: _int("AION_PASSWORD_ITERATIONS", 600_000))
    # Distinct approvers needed before a patch is approved (2 = four-eyes principle).
    required_approvals: int = field(default_factory=lambda: _int("AION_REQUIRED_APPROVALS", 1))
    # Redact secrets/PII from everything sent to an LLM.
    redact_prompts: bool = field(default_factory=lambda: _bool("AION_REDACT_PROMPTS", True))
    # Where AI-generated code is executed during validation: "local" (subprocess) or "docker".
    sandbox: str = field(default_factory=lambda: os.getenv("AION_SANDBOX", "local"))
    sandbox_image: str = field(default_factory=lambda: os.getenv("AION_SANDBOX_IMAGE", "aion-sandbox:py310"))

    @property
    def worktrees_dir(self) -> Path:
        return self.workspace_dir / "worktrees"


settings = Settings()
