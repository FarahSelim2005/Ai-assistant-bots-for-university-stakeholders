"""Where documents being edited are kept: one folder per conversation in data/edits/.

Files get random server-side names (32 hex characters), never the user's file name, so
no path can be guessed or built from user input. A download needs the conversation and
that random name. Folders are deleted DOC_EDIT_KEEP_MINUTES after their last change, and
when the user starts a new chat.
"""
import json
import re
import secrets
import shutil
import time
from pathlib import Path

from app import config

TOKEN = re.compile(r"^[0-9a-f]{32}$")
MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}
KEEP_VERSIONS = 5  # older versions of the same document are deleted


def folder(conversation_id: int) -> Path:
    return config.EDITS_DIR / str(int(conversation_id))


def safe_name(filename: str) -> str:
    """The user's file name without folders or odd characters, for the download only."""
    name = Path(filename.replace("\\", "/")).name
    name = re.sub(r"[^\w.\- ()؀-ۿ]", "_", name).strip(" .") or "document"
    return name[:120]


def save_version(conversation_id: int, data: bytes, extension: str, filename: str | None = None,
                 name: str | None = None, cv: bool = False) -> dict:
    """Store a new version of the conversation's document; `filename` starts a new document
    (a new upload; `cv` marks it as a restructured CV). `name` is this version's download
    name (default: "<file>_edited.<ext>").
    Returns the version's info: filename, download_name, token, extension, version."""
    directory = folder(conversation_id)
    directory.mkdir(parents=True, exist_ok=True)
    info = current(conversation_id) if filename is None else None
    if filename is None and info is None:
        raise ValueError("There is no document to edit in this chat. Attach one first.")
    if filename is not None:  # a new upload replaces the old document and its versions
        for old in directory.glob("*"):
            old.unlink()
        info = {"filename": safe_name(filename), "versions": [], "cv": cv}
    token = secrets.token_hex(16)
    (directory / f"{token}{extension}").write_bytes(data)
    info["versions"].append({"token": token, "extension": extension, **({"name": safe_name(name)} if name else {})})
    for old in info["versions"][:-KEEP_VERSIONS]:
        (directory / f"{old['token']}{old['extension']}").unlink(missing_ok=True)
    info["versions"] = info["versions"][-KEEP_VERSIONS:]
    info["version_number"] = info.get("version_number", -1) + 1  # 0 = the upload
    (directory / "info.json").write_text(json.dumps(info), encoding="utf-8")
    return describe(info)


def current(conversation_id: int) -> dict | None:
    """The stored info of the conversation's document, or None."""
    path = folder(conversation_id) / "info.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def download_name(info: dict, version: dict, original: bool = False) -> str:
    """The name a version is downloaded as: its own name, the upload's name, or "<file>_edited.<ext>"."""
    if version.get("name"):
        return version["name"]
    stem = info["filename"].rsplit(".", 1)[0]
    return f"{stem}{'' if original else '_edited'}{version['extension']}"


def describe(info: dict) -> dict:
    latest = info["versions"][-1]
    return {"filename": info["filename"], "download_name": download_name(info, latest, info["version_number"] == 0),
            "token": latest["token"], "extension": latest["extension"], "version": info["version_number"]}


def is_latest(conversation_id: int, token: str) -> bool:
    """True if `token` is the random token of the conversation's newest version."""
    info = current(conversation_id)
    return bool(info and TOKEN.match(token) and secrets.compare_digest(info["versions"][-1]["token"], token))


def latest_file(conversation_id: int) -> tuple[bytes, str]:
    """The newest version's content and extension (for the next edit)."""
    info = current(conversation_id)
    if info is None:
        raise ValueError("There is no document to edit in this chat. Attach one first.")
    latest = info["versions"][-1]
    return (folder(conversation_id) / f"{latest['token']}{latest['extension']}").read_bytes(), latest["extension"]


def file_for_download(conversation_id: int, token: str) -> tuple[Path, str, str] | None:
    """(path, download name, media type) of one stored version, or None. Only a random
    token of this conversation's document is accepted, so other files cannot be reached."""
    info = current(conversation_id)
    if info is None or not TOKEN.match(token):
        return None
    version = next((v for v in info["versions"] if v["token"] == token), None)
    if version is None:
        return None
    path = (folder(conversation_id) / f"{token}{version['extension']}").resolve()
    if path.parent != folder(conversation_id).resolve() or not path.is_file():
        return None
    return path, download_name(info, version), MEDIA_TYPES[version["extension"]]


def remove(conversation_id: int) -> None:
    shutil.rmtree(folder(conversation_id), ignore_errors=True)


def remove_old_files() -> None:
    """Delete the folders of documents not changed for DOC_EDIT_KEEP_MINUTES."""
    if not config.EDITS_DIR.is_dir():
        return
    limit = time.time() - config.DOC_EDIT_KEEP_MINUTES * 60
    for directory in config.EDITS_DIR.iterdir():
        info = directory / "info.json"
        changed = info.stat().st_mtime if info.exists() else directory.stat().st_mtime
        if directory.is_dir() and changed < limit:
            shutil.rmtree(directory, ignore_errors=True)
