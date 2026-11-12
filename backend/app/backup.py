"""A full pg_dump backup of the database, made before anything is deleted for good (the
console's "Delete university"). The file goes to BACKUP_DIR (default: the db-backups folder
next to the project, D:/Download/db-backups/). pg_dump is found on PATH, or in PostgreSQL's
usual Windows folder. No backup, no delete: BackupFailed stops it.
"""
import glob
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from app import config


class BackupFailed(Exception):
    """pg_dump could not make the backup."""


def pg_dump_path() -> str | None:
    found = shutil.which("pg_dump")
    if found:
        return found
    candidates = sorted(glob.glob("C:/Program Files/PostgreSQL/*/bin/pg_dump.exe"), key=lambda p: int(Path(p).parts[-3]) if Path(p).parts[-3].isdigit() else 0)
    return candidates[-1] if candidates else None


def backup(reason: str) -> Path:
    """pg_dump the whole database (custom format) to BACKUP_DIR; returns the file."""
    pg_dump = pg_dump_path()
    if not pg_dump:
        raise BackupFailed("pg_dump was not found, so no backup could be made.")
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in reason)[:60]
    out = config.BACKUP_DIR / f"{config.DB_NAME}-before-{safe}-{datetime.now():%Y%m%d-%H%M%S}.backup"
    environment = {**os.environ, "PGPASSWORD": config.DB_ADMIN_PASSWORD}
    try:
        subprocess.run([pg_dump, "-h", config.DB_HOST, "-p", str(config.DB_PORT), "-U", config.DB_ADMIN_USER, "-F", "c",
                        "-f", str(out), config.DB_NAME], env=environment, check=True, capture_output=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as error:
        out.unlink(missing_ok=True)
        raise BackupFailed(f"The backup failed ({type(error).__name__}), so nothing was deleted.") from error
    if not out.exists() or out.stat().st_size == 0:
        raise BackupFailed("The backup file is empty, so nothing was deleted.")
    return out
