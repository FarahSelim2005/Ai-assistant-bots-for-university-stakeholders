"""Apply the database migrations in backend/migrations/ (000_*.sql, 001_*.sql, ...) in order.

Each file runs in its own transaction (all of it or nothing) and is recorded in the
schema_migrations table, so running this again only applies files that are new.
Back up the database first (pgAdmin: right-click the database -> Backup...).

Run from the backend folder:
    python -m scripts.migrate                            # apply the new migrations
    python -m scripts.migrate --status                   # list applied and pending files
    python -m scripts.migrate --database giu-bots-copy   # another database, e.g. a test copy
"""
import argparse
import re
from pathlib import Path

from app import config
from app.db import get_connection

MIGRATIONS_DIR = config.BACKEND_DIR / "migrations"
FILE_NAME = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")  # "001_tenants.sql"


def migration_files(folder: Path | None = None) -> list[Path]:
    """The .sql files in number order (in MIGRATIONS_DIR unless a folder is given). Refuses
    badly named files and two files with one number, because either would make the order unclear."""
    files = sorted(p for p in (folder or MIGRATIONS_DIR).iterdir() if p.suffix.lower() == ".sql")
    bad = [p.name for p in files if not FILE_NAME.match(p.name)]
    if bad:
        raise SystemExit(f"Migration files must be named like 001_tenants.sql: {', '.join(bad)}")
    numbers = [p.name[:3] for p in files]
    repeated = sorted({n for n in numbers if numbers.count(n) > 1})
    if repeated:
        raise SystemExit(f"Two migration files share the number {', '.join(repeated)}.")
    return files


def applied_migrations() -> set[str]:
    """File names already applied (creates the schema_migrations table the first time)."""
    with get_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                     "filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        return {name for (name,) in conn.execute("SELECT filename FROM schema_migrations")}


def apply(path: Path) -> None:
    """Run one file and record it, in one transaction: an error leaves the database as it was."""
    with get_connection() as conn:
        conn.execute(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the SQL files in backend/migrations/.")
    parser.add_argument("--status", action="store_true", help="only list applied and pending files")
    parser.add_argument("--database", help=f"database name (default: DB_NAME, {config.DB_NAME})")
    args = parser.parse_args()
    if args.database:
        config.DB_NAME = args.database

    files = migration_files()
    done = applied_migrations()
    pending = [p for p in files if p.name not in done]
    print(f"Database {config.DB_NAME}: {len(files) - len(pending)} applied, {len(pending)} pending.")
    if args.status:
        for path in files:
            print(f"  {'applied' if path.name in done else 'pending'}  {path.name}")
        return
    for path in pending:
        print(f"  applying {path.name} ...", end=" ", flush=True)
        apply(path)
        print("done")


if __name__ == "__main__":
    main()
