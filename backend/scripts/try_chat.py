"""Ask one of a university's assistants a question from the terminal (default: its first one).

Run from the backend folder:
    python -m scripts.try_chat "where is the AI lab?"
    python -m scripts.try_chat "where is the clinic?" --user-type staff
    python -m scripts.try_chat "how long is maternity leave?" --agent hr_policies --user-type staff
    python -m scripts.try_chat "where is the Zebra Lab?" --tenant demo
"""
import argparse
import time

from app import config, tenants
from app.agents import script_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask an assistant a question.")
    parser.add_argument("question")
    parser.add_argument("--user-type", default="student")
    parser.add_argument("--agent", help="the assistant: its id, or a GIU template key (default: the first one)")
    parser.add_argument("--tenant", default=config.DEFAULT_TENANT, help="tenant slug (default: giu)")
    args = parser.parse_args()
    tenant = tenants.use_for_script(args.tenant)

    agent = script_agent(tenant.id, args.agent)
    start = time.perf_counter()
    response = agent.run(args.question, args.user_type)
    elapsed = time.perf_counter() - start

    print(f"{agent.display_name}  |  model: {agent.model}  |  took {elapsed:.2f}s")
    print(f"Sources: {response.sources or 'none (fallback, model not called)'}\n")
    print(response.answer)


if __name__ == "__main__":
    main()
