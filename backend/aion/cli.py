"""AION admin command line.

    python -m aion.cli users add <username> --role approver [--name "Full Name"]
    python -m aion.cli users list
    python -m aion.cli users disable <username>
    python -m aion.cli users reset-password <username>
    python -m aion.cli service-token [--write]
    python -m aion.cli agent-token [--write]      # MCP connector
    python -m aion.cli secret-key [--write]       # encrypts API keys saved in the dashboard

Passwords are read interactively (not echoed, never on the command line where
they would land in shell history). For scripts, use --password-stdin.
"""
from __future__ import annotations

import argparse
import getpass
import re
import secrets
import sys

from sqlalchemy import select

from aion import audit, security
from aion.config import BACKEND_DIR, settings
from aion.db import init_engine, session_scope
from aion.models import User


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Password (min 10 characters): ")
    if first != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match")
    return first


def users_add(args) -> None:
    password = _read_password(args.password_stdin)
    with session_scope() as s:
        try:
            user = security.create_user(s, args.username, password, args.role, args.name or "")
        except ValueError as exc:
            sys.exit(str(exc))
        audit.record(s, "user_created", "system:cli", username=user.username, role=user.role)
    print(f"Created user {args.username!r} with role {args.role!r}")


def users_list(_args) -> None:
    with session_scope() as s:
        rows = s.scalars(select(User).order_by(User.username)).all()
        if not rows:
            print("No users yet. Create one: python -m aion.cli users add <name> --role admin")
        for u in rows:
            print(f"{u.username:20} {u.role:10} {'active' if u.active else 'DISABLED':9} {u.display_name}")


def users_disable(args) -> None:
    with session_scope() as s:
        user = s.scalar(select(User).where(User.username == args.username))
        if not user:
            sys.exit(f"No user {args.username!r}")
        user.active = False
        audit.record(s, "user_disabled", "system:cli", username=user.username)
    print(f"Disabled {args.username!r} (existing sessions stop working immediately)")


def users_reset_password(args) -> None:
    password = _read_password(args.password_stdin)
    try:
        security.validate_new_password(password)
    except ValueError as exc:
        sys.exit(str(exc))
    with session_scope() as s:
        user = s.scalar(select(User).where(User.username == args.username))
        if not user:
            sys.exit(f"No user {args.username!r}")
        user.password_hash = security.hash_password(password)
        audit.record(s, "user_password_reset", "system:cli", username=user.username)
    print(f"Password updated for {args.username!r}")


def _write_env(name: str, value: str, comment: str) -> None:
    env = BACKEND_DIR / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    line = f"{name}={value}"
    if re.search(rf"^{name}=.*$", text, flags=re.M):
        text = re.sub(rf"^{name}=.*$", line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + ("\n\n" if text else "") + f"# {comment}\n" + line + "\n"
    env.write_text(text, encoding="utf-8")
    print(f"Wrote {name} to {env}. Restart AION to use it.")


def service_token(args) -> None:
    token = secrets.token_urlsafe(32)
    if args.write:
        _write_env("AION_SERVICE_TOKEN", token, "Machine clients (log shippers, CI, demo)")
    else:
        print(token)


def agent_token(args) -> None:
    token = secrets.token_urlsafe(32)
    if args.write:
        _write_env("AION_AGENT_TOKEN", token, "AI agents connected through the MCP connector (aion.mcp_server)")
    else:
        print(token)


def secret_key(args) -> None:
    from aion.secrets_store import new_key

    if settings.secret_key and not args.force:
        sys.exit("AION_SECRET_KEY already exists. Replacing it makes stored API keys unreadable; use --force.")
    key = new_key()
    if args.write:
        _write_env("AION_SECRET_KEY", key, "Master key that encrypts API keys saved in the dashboard - keep secret")
    else:
        print(key)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m aion.cli", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    users = sub.add_parser("users").add_subparsers(dest="action", required=True)
    add = users.add_parser("add")
    add.add_argument("username")
    add.add_argument("--role", required=True, choices=security.ROLES)
    add.add_argument("--name", help="display name")
    add.add_argument("--password-stdin", action="store_true")
    add.set_defaults(func=users_add)
    users.add_parser("list").set_defaults(func=users_list)
    dis = users.add_parser("disable")
    dis.add_argument("username")
    dis.set_defaults(func=users_disable)
    rp = users.add_parser("reset-password")
    rp.add_argument("username")
    rp.add_argument("--password-stdin", action="store_true")
    rp.set_defaults(func=users_reset_password)
    st = sub.add_parser("service-token", help="generate a service token for machine clients")
    st.add_argument("--write", action="store_true", help="store it in backend/.env")
    st.set_defaults(func=service_token)
    at = sub.add_parser("agent-token", help="generate the token used by the MCP connector")
    at.add_argument("--write", action="store_true", help="store it in backend/.env")
    at.set_defaults(func=agent_token)
    sk = sub.add_parser("secret-key", help="generate the master key that encrypts stored API keys")
    sk.add_argument("--write", action="store_true", help="store it in backend/.env")
    sk.add_argument("--force", action="store_true", help="replace an existing key (stored API keys become unreadable)")
    sk.set_defaults(func=secret_key)
    args = ap.parse_args(argv)
    init_engine(settings.database_url)
    args.func(args)


if __name__ == "__main__":
    main()
