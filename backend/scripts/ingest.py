"""Load a tenant's documents, split them into chunks, embed them, and store them.

Each assistant has its own folder, named by its `folder` (readable, unique per university):
GIU's are data/raw/labs_research/, data/raw/internship_career/ ...; another tenant's are
data/tenants/<slug>/<folder>/. Who may see the chunks is the assistant's audiences. Every chunk
is stored with the tenant's and the assistant's id. Folders still named by an assistant's id
(from migration 004) are renamed with `python -m scripts.move_agent_folders`.

This script connects as the owner of the tables (DB_ADMIN_USER); the admin page, which
also uses ingest_file, connects as the app (DB_USER).

Run from the backend folder:
    python -m scripts.ingest                          # every GIU assistant's folder
    python -m scripts.ingest --agent internship_career   # one assistant (id, or a GIU template key)
    python -m scripts.ingest --tenant demo            # data/tenants/demo/<folder>/

Re-running is safe: chunks of a file are deleted before that file is ingested again,
and chunks of files that were removed from the folder are deleted too.
"""
import argparse
import re
from pathlib import Path

from pypdf import PdfReader

from app import config, tenants
from app.agents import agents_of, find_agent
from app.db import get_connection, use_admin_login
from app.rag.embeddings import embed_texts

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}


def read_file(path: Path) -> str:
    """Return the plain text of a PDF, TXT or MD file."""
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8")


def split_words(words: list[str], size: int, overlap: int) -> list[str]:
    """Cut a long list of words into windows of `size` words that share `overlap` words."""
    chunks = []
    for start in range(0, len(words), size - overlap):
        chunks.append(" ".join(words[start:start + size]))
        if start + size >= len(words):
            break
    return chunks


def split_into_chunks(text: str, size: int, overlap: int) -> list[str]:
    """Split text into chunks of at most `size` words without mixing sections.

    Paragraphs (separated by blank lines) are kept together, and a Markdown
    heading ("#") always starts a new chunk, so one chunk covers one topic.
    A paragraph longer than `size` (common in PDFs) is cut with `split_words`.
    """
    chunks: list[str] = []
    current: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        words = paragraph.split()
        if not words:
            continue
        if current and paragraph.lstrip().startswith("#"):
            chunks.append(" ".join(current))
            current = []
        if len(current) + len(words) <= size:
            current.extend(words)
        elif len(words) <= size:
            chunks.append(" ".join(current))
            current = words
        else:
            chunks.extend(split_words(current + words, size, overlap))
            current = []
    if current:
        chunks.append(" ".join(current))
    return chunks


def ingest_file(path: Path, agent: str, audience: list[str]) -> int:
    """Chunk, embed and store one file of an assistant (`agent`: its id) for the current tenant.
    Returns the number of chunks stored."""
    text = read_file(path)
    chunks = split_into_chunks(text, config.CHUNK_SIZE_WORDS, config.CHUNK_OVERLAP_WORDS)
    if not chunks:
        return 0
    embeddings = embed_texts(chunks)

    tenant_id = tenants.current_id()
    with get_connection(tenants.current_id()) as conn:
        conn.execute(
            "DELETE FROM chunks WHERE tenant_id = %s AND agent_id = %s AND source = %s",
            (tenant_id, agent, path.name),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (tenant_id, agent_id, audience, source, content, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [(tenant_id, agent, audience, path.name, chunk, emb)
                 for chunk, emb in zip(chunks, embeddings)],
            )
    return len(chunks)


def ingest_agent(agent: str, folder: Path, audience: list[str], label: str = "") -> None:
    """Index all documents in one assistant's folder and remove chunks of deleted files."""
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS)
    total = 0
    for path in files:
        count = ingest_file(path, agent, audience)
        print(f"  {path.name}: {count} chunks")
        total += count
    for source, count in remove_missing_files(agent, [p.name for p in files]):
        print(f"  {source}: no longer in the folder, {count} old chunks removed")
    print(f"  {total} chunks stored for '{label or agent}' (audience: {audience}).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest documents into the chunks table.")
    parser.add_argument("--agent", help="only this assistant: its id, or a GIU template key (default: all)")
    parser.add_argument("--tenant", default=config.DEFAULT_TENANT, help="tenant slug (default: giu)")
    args = parser.parse_args()

    use_admin_login()
    tenant = tenants.for_script(args.tenant)
    root = tenants.data_dir(tenant)
    with tenants.using(tenant):
        agents = {agent.settings.folder: agent for agent in agents_of(tenant.id)}
        if args.agent:
            chosen = find_agent(tenant.id, args.agent) or agents.get(args.agent)
            if chosen is None:
                raise SystemExit(f"{tenant.slug} has no assistant '{args.agent}'.")
            agents = {chosen.settings.folder: chosen}
        folders = sorted(p for p in root.iterdir() if p.is_dir() and (not args.agent or p.name in agents))             if root.is_dir() else []
        if not folders:
            print(f"No assistant folders found in {root}")
            return
        print(f"Tenant {tenant.slug} ({tenant.name}), documents in {root}")
        for folder in folders:
            agent = agents.get(folder.name)
            if agent is None:
                hint = (" (an old folder name: run python -m scripts.move_agent_folders)"
                        if find_agent(tenant.id, folder.name) else "")
                print(f"Skipping {folder.name}/: {tenant.slug} has no assistant with that folder{hint}")
                continue
            print(f"{agent.display_name} ({folder.name}):")
            ingest_agent(agent.name, folder, list(agent.allowed_user_types), agent.display_name)


def remove_missing_files(agent: str, present: list[str]) -> list[tuple[str, int]]:
    """Delete the current tenant's chunks of this assistant (`agent`: its id) whose source file was removed from
    the folder, so the agent stops answering from deleted documents. Returns (file name,
    chunks removed)."""
    with get_connection(tenants.current_id()) as conn:
        rows = conn.execute(
            "DELETE FROM chunks WHERE tenant_id = %s AND agent_id = %s AND NOT (source = ANY(%s)) RETURNING source",
            (tenants.current_id(), agent, present),
        ).fetchall()
    counts: dict[str, int] = {}
    for (source,) in rows:
        counts[source] = counts.get(source, 0) + 1
    return list(counts.items())


if __name__ == "__main__":
    main()
