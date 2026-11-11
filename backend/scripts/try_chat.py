"""Ask the Labs & Research agent a question from the terminal.

Run from the backend folder:
    python -m scripts.try_chat "where is the AI lab?"
    python -m scripts.try_chat "where is the clinic?" --user-type staff
    python -m scripts.try_chat "where is the Zebra Lab?" --tenant demo
"""
import argparse
import time

from app import config, tenants
from app.agents.labs_research import LabsResearchAgent


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the Labs & Research agent a question.")
    parser.add_argument("question")
    parser.add_argument("--user-type", default="student")
    parser.add_argument("--tenant", default=config.DEFAULT_TENANT, help="tenant slug (default: giu)")
    args = parser.parse_args()
    tenants.use_for_script(args.tenant)

    agent = LabsResearchAgent()
    start = time.perf_counter()
    response = agent.run(args.question, args.user_type)
    elapsed = time.perf_counter() - start

    print(f"Model: {agent.model}  |  took {elapsed:.2f}s")
    print(f"Sources: {response.sources or 'none (fallback, model not called)'}\n")
    print(response.answer)


if __name__ == "__main__":
    main()
