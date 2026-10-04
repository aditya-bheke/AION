"""Encryption of secrets stored in the database (API keys for AI providers).

Fernet (from the `cryptography` package) = AES-128-CBC + HMAC-SHA256 with a
random IV: it both hides the value and detects tampering. The master key comes
from AION_SECRET_KEY in backend/.env (never from the database), so a stolen
database file alone does not reveal provider API keys.

    python -m aion.cli secret-key --write     # generate the master key once
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from aion.config import settings


class SecretsUnavailable(RuntimeError):
    pass


def _fernet() -> Fernet:
    if not settings.secret_key:
        raise SecretsUnavailable("AION_SECRET_KEY is not set; run: python -m aion.cli secret-key --write")
    try:
        return Fernet(settings.secret_key.encode())
    except (ValueError, TypeError) as exc:
        raise SecretsUnavailable(f"AION_SECRET_KEY is not a valid Fernet key: {exc}") from exc


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretsUnavailable("Stored secret cannot be decrypted (AION_SECRET_KEY changed?)") from exc


def hint(value: str) -> str:
    """What the UI may show about a secret: its last four characters."""
    return f"…{value[-4:]}" if len(value) >= 8 else "…"


def new_key() -> str:
    return Fernet.generate_key().decode("ascii")
