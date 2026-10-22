"""Evaluate an agent on a list of test questions.

For every row of the CSV (question, expected_keywords, agent) the question is sent
straight to the agent (no API). An answer counts as correct when it contains ALL
expected keywords (separated by ";", case-insensitive). Prints accuracy and the
average and maximum response time.

Run from the backend folder:
    python -m scripts.evaluate
    python -m scripts.evaluate --user-type staff --out data/results.csv
"""
import argparse
import csv
import sys
import time

import httpx

from app import config
from app.agents import AGENTS
from app.llm.client import LLMError

DEFAULT_CSV = config.BACKEND_DIR / "data" / "test_questions.csv"


def normalize(text: str) -> str:
    """Lowercase, straight apostrophes, plain spaces and hyphens, so "Don’t" matches
    "don't" and "north\u2011east" (a special hyphen some models write) matches "north-east"."""
    text = text.replace("\u202f", " ").replace("\u00a0", " ").replace("\u2011", "-")
    return text.lower().replace("’", "'")


def missing_keywords(answer: str, keywords: list[str]) -> list[str]:
    """Expected keywords that do not appear in the answer."""
    return [k for k in keywords if normalize(k) not in normalize(answer)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate agents on test questions.")
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--user-type", default="student", choices=["student", "staff"])
    parser.add_argument("--out", help="optional CSV file to save every answer and result")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # Arabic answers in the Windows terminal

    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    results = []
    for number, row in enumerate(rows, start=1):
        if args.user_type not in AGENTS[row["agent"]].allowed_user_types:
            print(f"{number:2}. skipped (not available for {args.user_type}): {row['question']}")
            continue
        keywords = [k.strip() for k in row["expected_keywords"].split(";") if k.strip()]
        start = time.perf_counter()
        try:
            answer = AGENTS[row["agent"]].run(row["question"], args.user_type).answer
        except (httpx.HTTPError, LLMError) as error:  # count a failed model call as wrong
            answer = f"ERROR: {error}"
        seconds = time.perf_counter() - start

        missing = missing_keywords(answer, keywords)
        results.append({
            "question": row["question"],
            "agent": row["agent"],
            "correct": not missing,
            "seconds": round(seconds, 2),
            "missing_keywords": ";".join(missing),
            "answer": answer,
        })
        status = "PASS" if not missing else f"FAIL (missing: {', '.join(missing)})"
        print(f"{number:2}. [{seconds:.2f}s] {status}  {row['question']}")
        if missing:
            print(f"      answer: {answer}")

    times = [r["seconds"] for r in results]
    correct = sum(r["correct"] for r in results)
    print(f"\nModel: {config.LABS_MODEL}  |  user type: {args.user_type}")
    print(f"Accuracy: {correct}/{len(results)} = {correct / len(results):.0%}")
    print(f"Average time: {sum(times) / len(times):.2f}s  |  Max time: {max(times):.2f}s")
    print(f"Answers over 2s: {sum(t > 2 for t in times)}")

    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        print(f"Saved results to {args.out}")


if __name__ == "__main__":
    main()
