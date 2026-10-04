"""Try retrieval + prompt + LLM from the terminal (no agent logic yet).

Run from the backend folder:
    python -m scripts.try_chat "where is the AI lab?"
"""
import argparse
import time

from app import config
from app.llm.openrouter import chat
from app.rag.prompts import LABS_SYSTEM_PROMPT, build_messages
from app.rag.retriever import retrieve


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the LLM a question using retrieved context.")
    parser.add_argument("question")
    parser.add_argument("--user-type", default="student", choices=["student", "staff"])
    args = parser.parse_args()

    start = time.perf_counter()
    chunks = retrieve(args.question, "labs_research", args.user_type)
    retrieved = time.perf_counter()
    messages = build_messages(LABS_SYSTEM_PROMPT, args.question, chunks)
    answer = chat(messages, model=config.LABS_MODEL)
    done = time.perf_counter()

    print(f"Model: {config.LABS_MODEL}")
    print(f"Retrieval {retrieved - start:.2f}s + LLM {done - retrieved:.2f}s "
          f"= {done - start:.2f}s\n")
    print(answer)


if __name__ == "__main__":
    main()
