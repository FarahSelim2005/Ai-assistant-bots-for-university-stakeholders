"""The multi-tenancy benchmark: questions to three made-up universities whose documents
deliberately differ on the same topics, scored for accuracy AND for keeping universities
apart.

benchmark/universities.json   the universities and their assistants
benchmark/documents/<slug>/   their documents (one folder per assistant)
benchmark/questions.csv       id, university, assistant, kind, question, expected, forbidden, handover_to

Kinds: conflict (a topic all three have, with different facts: the university's own fact is
expected, the others' are forbidden), answerable, isolation (a fact only ANOTHER university
has: "don't have" expected, that fact forbidden), not_in_docs, arabic, handover (asked of the
wrong assistant: it must point to the right one OF THE SAME university).

expected: every ";"-part must appear (case-insensitive), "|" separates accepted wordings.
forbidden: no ";"-part may appear. A leak is a forbidden fact in the answer, a source document
of another university, or a hand-over to another university's assistant: there must be none.

The universities live in their own database (default giu-bots-bench, made and migrated on the
first run), never in giu-bots, with hosts <slug>.bench. Their documents are indexed once
(again with --reindex).

Run from the backend folder:
    python -m scripts.benchmark --dry-run          # no model, no network: fake embeddings, the "answer" is the
                                                   # retrieved text (checks the pipeline and the isolation only)
    python -m scripts.benchmark                    # real models: about 50 chat calls plus embeddings
    python -m scripts.benchmark --limit 10 --university bench-rsu
    python -m scripts.benchmark --cleanup          # delete the benchmark universities from that database

Writes docs/testing/multitenancy-benchmark-report.md and ...-results.csv (with --dry-run:
...-dryrun-report.md and ...-dryrun-results.csv).
"""
import argparse
import csv
import hashlib
import json
import re
import secrets
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from unittest import mock

import httpx
import numpy as np
import psycopg

from app import auth, config, tenants, universities
from app.agents import agents_of
from app.db import get_admin_connection
from app.llm.client import LLMError
from scripts import ingest, migrate
from scripts.evaluate import normalize

BENCH_DIR = config.BACKEND_DIR / "benchmark"
DOCS_OUT = config.BACKEND_DIR.parent / "docs" / "testing"
DEFAULT_DATABASE = "giu-bots-bench"
USER_TYPE = "student"
FALLBACK = re.compile(r"don't have|do not have|لا أملك|معنديش|مش عندي", re.IGNORECASE)


# ---------------------------------------------------------------- the database and the universities

def use_database(name: str) -> None:
    """Make (if needed), migrate and use the benchmark database for every connection below."""
    if name == config.DB_NAME:
        raise SystemExit(f"The benchmark never runs in the app's database ({name}): it needs its own (default {DEFAULT_DATABASE}).")
    with psycopg.connect(host=config.DB_HOST, port=config.DB_PORT, dbname="postgres", user=config.DB_ADMIN_USER,
                         password=config.DB_ADMIN_PASSWORD, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            conn.execute(f'CREATE DATABASE "{name}"')
            print(f"Made the database {name}.")
    migrate.migrate(name, log=lambda message: None)
    config.DB_NAME = name
    tenants._by_host.clear()


def load_setup() -> list[dict]:
    return json.loads((BENCH_DIR / "universities.json").read_text(encoding="utf-8"))["universities"]


def set_up(reindex: bool) -> dict[str, tenants.Tenant]:
    """The benchmark universities (made once) with their documents indexed."""
    config.TENANTS_DATA_DIR = BENCH_DIR / "documents"
    made = {}
    for uni in load_setup():
        tenant = tenants.by_slug(uni["slug"])
        if tenant is None:
            with get_admin_connection() as conn:
                universities.create(
                    conn, name=uni["name"], short_name=uni["short_name"], slug=uni["slug"], host=f"{uni['slug']}.bench",
                    plan="unlimited", brand_primary=uni["brand_primary"],
                    assistants=[{"name": a["name"], "description": a["description"]} for a in uni["assistants"]],
                    admin_email=f"admin@{uni['slug']}.bench", admin_name="Benchmark",
                    password_hash=auth.hash_password(secrets.token_urlsafe(24)))
            tenant = tenants.by_slug(uni["slug"])
            print(f"Made {uni['name']} ({uni['slug']}.bench).")
        made[uni["slug"]] = tenant
        with tenants.using(tenant):
            for agent in agents_of(tenant.id):
                folder = tenants.data_dir(tenant) / agent.settings.folder
                with get_admin_connection(tenant.id) as conn:
                    indexed = conn.execute("SELECT count(*) FROM chunks WHERE tenant_id = %s AND agent_id = %s",
                                           (tenant.id, agent.id)).fetchone()[0]
                if folder.is_dir() and (reindex or not indexed):
                    print(f"Indexing {uni['short_name']} {agent.display_name}:")
                    ingest.ingest_agent(agent.name, folder, list(agent.allowed_user_types), agent.display_name)
    return made


def clean_up() -> None:
    with get_admin_connection() as conn:
        for uni in load_setup():
            row = conn.execute("SELECT id FROM tenants WHERE slug = %s", (uni["slug"],)).fetchone()
            if row:
                universities.delete(conn, row[0])
                print(f"Deleted {uni['name']} from {config.DB_NAME}.")


# ---------------------------------------------------------------- scoring

def parts(cell: str) -> list[list[str]]:
    """'a|b;c' -> [['a', 'b'], ['c']]"""
    return [[w.strip() for w in part.split("|") if w.strip()] for part in (cell or "").split(";") if part.strip()]


def score(row: dict, answer: str, sources: list[str], redirect, own_files: set[str], own_agents: dict[str, str]) -> dict:
    text = normalize(answer)
    expected = parts(row["expected"])
    missing = [" | ".join(alts) for alts in expected if not any(normalize(a) in text for a in alts)]
    if any(a in ("don't have", "do not have") for alts in expected for a in alts) and FALLBACK.search(answer):
        missing = [m for m in missing if "don't have" not in m]
    leaked = [w for alts in parts(row["forbidden"]) for w in alts if normalize(w) in text]
    foreign_sources = [s for s in sources if s not in own_files]
    handover_ok = True
    foreign_handover = False
    if redirect is not None:
        foreign_handover = redirect.agent not in own_agents
    if row["handover_to"]:
        handover_ok = redirect is not None and own_agents.get(redirect.agent) == row["handover_to"]
    correct = not missing and not leaked and not foreign_sources and handover_ok and not foreign_handover
    return {"correct": correct, "missing": missing, "leaked": leaked, "foreign_sources": foreign_sources,
            "foreign_handover": foreign_handover, "handover_ok": handover_ok,
            "leak": bool(leaked or foreign_sources or foreign_handover)}


# ---------------------------------------------------------------- dry run: no model, no network

def fake_vector(text: str) -> list[float]:
    """A word-hashing vector (1024 numbers): similar words, similar vectors. Not semantic."""
    vector = np.zeros(1024)
    for word in re.findall(r"\w+", text.lower()):
        vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % 1024] += 1.0
    norm = np.linalg.norm(vector)
    return list(vector / norm) if norm else list(vector)


def dry_run_patches() -> list:
    """Stand-ins: fake embeddings, and the 'answer' is the retrieved text (a perfect reader)."""
    import app.agents.base as base
    import app.agents.directory as directory
    import app.rag.embeddings as embeddings
    import app.rag.retriever as retriever
    texts = lambda items: [fake_vector(t) for t in items]
    return [
        mock.patch.object(embeddings, "embed_texts", texts), mock.patch.object(ingest, "embed_texts", texts),
        mock.patch.object(directory, "embed_texts", texts), mock.patch.object(directory, "embed_text", fake_vector),
        mock.patch.object(retriever, "embed_text", fake_vector),
        mock.patch.object(base.BaseAgent, "generate", lambda self, question, chunks, history, attachment=None:
                          "\n".join(c.content for c in chunks)),
        mock.patch.object(config, "SIMILARITY_THRESHOLD", 0.2),  # word-hashing scores are lower than bge-m3's
    ]


# ---------------------------------------------------------------- the run

def run(rows: list[dict], made: dict[str, tenants.Tenant]) -> list[dict]:
    results = []
    own_files = {slug: {p.name for p in (BENCH_DIR / "documents" / slug).rglob("*") if p.is_file()} for slug in made}
    for row in rows:
        tenant = made[row["university"]]
        agents = agents_of(tenant.id)
        own_agents = {a.name: a.display_name for a in agents}
        agent = next((a for a in agents if a.display_name == row["assistant"]), None)
        started = time.perf_counter()
        error, answer, sources, redirect = "", "", [], None
        try:
            if agent is None:
                raise LookupError(f"no assistant '{row['assistant']}'")
            with tenants.using(tenant):
                response = agent.run(row["question"], USER_TYPE, [], None)
            answer, sources, redirect = response.answer, response.sources, response.redirect
        except (LookupError, ValueError, LLMError, httpx.HTTPError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        seconds = time.perf_counter() - started
        scored = score(row, answer, sources, redirect, own_files[row["university"]], own_agents) if not error else \
            {"correct": False, "missing": [], "leaked": [], "foreign_sources": [], "foreign_handover": False,
             "handover_ok": False, "leak": False}
        results.append({**row, **scored, "answer": answer, "sources": sources, "error": error, "seconds": seconds,
                        "handover": own_agents.get(redirect.agent, redirect.name) if redirect else ""})
        flag = "LEAK" if scored["leak"] else ("ok" if scored["correct"] else ("ERROR" if error else "wrong"))
        print(f"{row['id']} {row['university']:10} {row['kind']:11} {flag:5} {seconds:6.1f}s  {row['question']}")
    return results


def report(results: list[dict], dry: bool, total_seconds: float) -> str:
    n = len(results)
    rate = lambda rs: f"{sum(r['correct'] for r in rs)}/{len(rs)} ({100 * sum(r['correct'] for r in rs) / len(rs):.0f}%)" if rs else "-"
    times = [r["seconds"] for r in results if not r["error"]]
    leaks = [r for r in results if r["leak"]]
    lines = ["# Multi-tenancy benchmark report" + (" (dry run)" if dry else ""), "",
             f"Run on {datetime.now():%Y-%m-%d %H:%M} with `python -m scripts.benchmark{' --dry-run' if dry else ''}`: "
             f"{n} questions to {len({r['university'] for r in results})} made-up universities "
             f"(`backend/benchmark/`), database `{config.DB_NAME}`.", ""]
    if dry:
        lines += ["**Dry run: no model and no network.** Embeddings are word-hashing stand-ins and the \"answer\" is "
                  "the retrieved text, so this checks the pipeline and the isolation (which university's documents "
                  "are searched), not the answer quality. Accuracy here is not the real one.", ""]
    else:
        lines += [f"Models: answers `{config.LABS_MODEL}` (backups {', '.join(config.LABS_BACKUP_MODELS) or '-'}), "
                  f"embeddings `{config.EMBEDDING_MODEL}`.", ""]
    lines += ["| Measure | Result |", "|---|---|",
              f"| Accuracy (all) | {rate(results)} |",
              f"| Leaks (another university's fact, document or assistant) | **{len(leaks)}** |",
              f"| Errors (model or network) | {sum(1 for r in results if r['error'])} |",
              (f"| Response time, mean / median / max | {statistics.mean(times):.2f} s / {statistics.median(times):.2f} s / "
               f"{max(times):.2f} s |" if times else "| Response time | - |"),
              f"| Total run time | {total_seconds:.0f} s |", "",
              "| Kind | Accuracy | Leaks |", "|---|---|---|"]
    for kind in ("conflict", "answerable", "isolation", "not_in_docs", "arabic", "handover"):
        rs = [r for r in results if r["kind"] == kind]
        if rs:
            lines.append(f"| {kind} | {rate(rs)} | {sum(r['leak'] for r in rs)} |")
    lines += ["", "| University | Accuracy | Leaks |", "|---|---|---|"]
    for uni in dict.fromkeys(r["university"] for r in results):
        rs = [r for r in results if r["university"] == uni]
        lines.append(f"| {uni} | {rate(rs)} | {sum(r['leak'] for r in rs)} |")
    lines += ["", "## Every question", "", "| Id | University | Kind | Question | Result | Why | Time |", "|---|---|---|---|---|---|---:|"]
    for r in results:
        why = "; ".join(filter(None, [r["error"], f"missing {', '.join(r['missing'])}" if r["missing"] else "",
                                      f"forbidden {', '.join(r['leaked'])}" if r["leaked"] else "",
                                      f"foreign sources {', '.join(r['foreign_sources'])}" if r["foreign_sources"] else "",
                                      "handed over to another university" if r["foreign_handover"] else "",
                                      f"no hand-over to {r['handover_to']}" if r["handover_to"] and not r["handover_ok"] else ""]))
        result = "LEAK" if r["leak"] else ("✅" if r["correct"] else "❌")
        lines.append(f"| {r['id']} | {r['university']} | {r['kind']} | {r['question'].replace('|', '/')} | {result} | "
                     f"{why.replace('|', '/')} | {r['seconds']:.1f} s |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="The multi-tenancy benchmark.")
    parser.add_argument("--database", default=DEFAULT_DATABASE, help=f"its own database (default {DEFAULT_DATABASE})")
    parser.add_argument("--dry-run", action="store_true", help="no model, no network (checks the pipeline and isolation)")
    parser.add_argument("--reindex", action="store_true", help="index the documents again")
    parser.add_argument("--university", help="only this university, e.g. bench-rsu")
    parser.add_argument("--limit", type=int, help="only the first N questions")
    parser.add_argument("--cleanup", action="store_true", help="delete the benchmark universities and stop")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # Arabic questions in the Windows console
    patches = dry_run_patches() if args.dry_run else []
    for patch in patches:
        patch.start()
    use_database(args.database)
    if args.cleanup:
        clean_up()
        return
    with (BENCH_DIR / "questions.csv").open(encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if not args.university or r["university"] == args.university]
    rows = rows[:args.limit] if args.limit else rows
    if not args.dry_run:
        print(f"This sends {len(rows)} questions to the real models ({config.LABS_MODEL}) and uses your quota.")
    made = set_up(args.reindex)
    started = time.perf_counter()
    results = run(rows, made)
    total = time.perf_counter() - started
    name = "multitenancy-benchmark" + ("-dryrun" if args.dry_run else "")
    DOCS_OUT.mkdir(parents=True, exist_ok=True)
    (DOCS_OUT / f"{name}-report.md").write_text(report(results, args.dry_run, total), encoding="utf-8")
    with (DOCS_OUT / f"{name}-results.csv").open("w", encoding="utf-8", newline="") as f:
        fields = ["id", "university", "assistant", "kind", "question", "correct", "leak", "missing", "leaked",
                  "foreign_sources", "handover", "error", "seconds", "answer"]
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow({**r, "missing": "; ".join(r["missing"]), "leaked": "; ".join(r["leaked"]),
                             "foreign_sources": "; ".join(r["foreign_sources"]), "seconds": f"{r['seconds']:.2f}"})
    correct = sum(r["correct"] for r in results)
    leaks = sum(r["leak"] for r in results)
    print(f"\n{correct}/{len(results)} correct, {leaks} leaks. Report: {DOCS_OUT / f'{name}-report.md'}")
    sys.exit(1 if leaks else 0)


if __name__ == "__main__":
    main()
