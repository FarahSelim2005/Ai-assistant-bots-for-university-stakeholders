"""Try the retriever from the terminal.

Run from the backend folder:
    python -m scripts.try_retrieve "where is the AI lab?"
    python -m scripts.try_retrieve "where is the AI lab?" --user-type staff
"""
import argparse
import time

from app import config
from app.rag.retriever import retrieve


def main() -> None:
    parser = argparse.ArgumentParser(description="Show the chunks retrieved for a question.")
    parser.add_argument("question")
    parser.add_argument("--agent", default="labs_research")
    parser.add_argument("--user-type", default="student", choices=["student", "staff"])
    args = parser.parse_args()

    start = time.perf_counter()
    results = retrieve(args.question, args.agent, args.user_type)
    elapsed = time.perf_counter() - start

    print(f"Threshold: {config.SIMILARITY_THRESHOLD}  |  took {elapsed:.2f}s")
    if not results:
        print("No chunks found for this agent and user type.")
    for r in results:
        mark = "PASS" if r.score >= config.SIMILARITY_THRESHOLD else "below"
        preview = r.content[:80].replace("\n", " ")
        print(f"{r.score:.3f} [{mark}]  {r.source}  |  {preview}")


if __name__ == "__main__":
    main()
