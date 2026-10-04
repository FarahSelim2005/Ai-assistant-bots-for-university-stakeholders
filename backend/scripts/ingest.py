"""Load documents from data/raw, split them into chunks, embed them, and store them.

Run from the backend folder:
    python -m scripts.ingest
    python -m scripts.ingest --agent labs_research --audience student,staff

Re-running is safe: chunks of a file are deleted before that file is ingested again.
"""
import argparse
from pathlib import Path

from pypdf import PdfReader

from app import config
from app.db import get_connection
from app.rag.embeddings import embed_texts

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}


def read_file(path: Path) -> str:
    """Return the plain text of a PDF, TXT or MD file."""
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8")


def split_into_chunks(text: str, size: int, overlap: int) -> list[str]:
    """Split text into chunks of `size` words; consecutive chunks share `overlap` words."""
    words = text.split()
    chunks = []
    step = size - overlap
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start:start + size]))
        if start + size >= len(words):
            break
    return chunks


def ingest_file(path: Path, agent: str, audience: list[str]) -> int:
    """Chunk, embed and store one file. Returns the number of chunks stored."""
    text = read_file(path)
    chunks = split_into_chunks(text, config.CHUNK_SIZE_WORDS, config.CHUNK_OVERLAP_WORDS)
    if not chunks:
        return 0
    embeddings = embed_texts(chunks)

    with get_connection() as conn:
        conn.execute(
            "DELETE FROM chunks WHERE agent = %s AND source = %s",
            (agent, path.name),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (agent, audience, source, content, embedding) "
                "VALUES (%s, %s, %s, %s, %s)",
                [(agent, audience, path.name, chunk, emb)
                 for chunk, emb in zip(chunks, embeddings)],
            )
    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest documents into the chunks table.")
    parser.add_argument("--agent", default="labs_research")
    parser.add_argument("--audience", default="student,staff",
                        help="comma-separated user types allowed to see these chunks")
    parser.add_argument("--folder", default=str(config.RAW_DATA_DIR))
    args = parser.parse_args()

    audience = [a.strip() for a in args.audience.split(",") if a.strip()]
    files = sorted(p for p in Path(args.folder).iterdir()
                   if p.suffix.lower() in SUPPORTED_EXTENSIONS)
    if not files:
        print(f"No .pdf/.txt/.md files found in {args.folder}")
        return

    total = 0
    for path in files:
        count = ingest_file(path, args.agent, audience)
        print(f"{path.name}: {count} chunks")
        total += count
    print(f"Done. {total} chunks stored for agent '{args.agent}' (audience: {audience}).")


if __name__ == "__main__":
    main()
