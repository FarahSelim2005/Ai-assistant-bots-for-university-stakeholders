"""Make a login for a university's admin page (/admin) or for the platform console (/console),
or set a new password for an existing one.

Run from the backend folder (connects as the owner, DB_ADMIN_USER):
    python -m scripts.create_user --tenant giu --email admin@giu.example --role tenant_admin
    python -m scripts.create_user --tenant demo --email editor@demo.example --role editor
    python -m scripts.create_user --email owner@platform.example --role platform_owner
    python -m scripts.create_user --email admin@giu.example --new-password    # an existing account

The password is asked for (not shown while typing), or made up with --generate and printed once.
"""
import argparse
import getpass
import secrets
import sys

import psycopg

from app import tenants
from app.auth import hash_password, password_problem
from app.db import get_admin_connection, use_admin_login

ROLES = ("tenant_admin", "editor", "platform_owner")


def main() -> None:
    parser = argparse.ArgumentParser(description="Make a login (or set a new password).")
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=ROLES, help="for a new account")
    parser.add_argument("--tenant", help="the university's slug (not for platform_owner)")
    parser.add_argument("--name", default="")
    parser.add_argument("--new-password", action="store_true", help="set a new password for an existing account")
    parser.add_argument("--generate", action="store_true", help="make up a password and print it once")
    args = parser.parse_args()
    use_admin_login()
    email = args.email.strip().lower()

    password = secrets.token_urlsafe(12) if args.generate else getpass.getpass("Password: ")
    problem = password_problem(password)
    if problem:
        raise SystemExit(problem)

    with get_admin_connection() as conn:
        if args.new_password:
            changed = conn.execute("UPDATE users SET password_hash = %s WHERE email = %s",
                                   (hash_password(password), email)).rowcount
            if not changed:
                raise SystemExit(f"No account for {email}.")
            print(f"New password set for {email}.")
        else:
            if args.role is None:
                raise SystemExit("Give --role for a new account.")
            tenant_id = None
            if args.role != "platform_owner":
                if not args.tenant:
                    raise SystemExit("Give --tenant (the university's slug) for a university login.")
                tenant_id = tenants.for_script(args.tenant).id
            try:
                conn.execute("INSERT INTO users (tenant_id, email, name, role, password_hash) VALUES (%s, %s, %s, %s, %s)",
                             (tenant_id, email, args.name, args.role, hash_password(password)))
            except psycopg.errors.UniqueViolation:
                raise SystemExit(f"{email} already has an account (use --new-password to change its password).")
            print(f"Account made: {email} ({args.role}{', ' + args.tenant if tenant_id else ''}).")
    if args.generate:
        print(f"Password: {password}", file=sys.stderr)


if __name__ == "__main__":
    main()
