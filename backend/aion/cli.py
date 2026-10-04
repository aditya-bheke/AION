"""AION admin command line.

    python -m aion.cli users add <username> --role approver [--name "Full Name"]
    python -m aion.cli users list
    python -m aion.cli users disable <username>
    python -m aion.cli users reset-password <username>
    python -m aion.cli service-token [--write]

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


def service_token(args) -> None:
    token = secrets.token_urlsafe(32)
    if not args.write:
        print(token)
        return
    env = BACKEND_DIR / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    line = f"AION_SERVICE_TOKEN={token}"
    if re.search(r"^AION_SERVICE_TOKEN=.*$", text, flags=re.M):
        text = re.sub(r"^AION_SERVICE_TOKEN=.*$", line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + ("\n\n" if text else "") + "# Machine clients (log shippers, CI, demo)\n" + line + "\n"
    env.write_text(text, encoding="utf-8")
    print(f"Wrote a new AION_SERVICE_TOKEN to {env}. Restart AION (and the demo) to use it.")


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
    args = ap.parse_args(argv)
    init_engine(settings.database_url)
    args.func(args)


if __name__ == "__main__":
    main()
