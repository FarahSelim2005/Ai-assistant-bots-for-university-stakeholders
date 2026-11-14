"""Run the multi-tenancy test catalogue (tests/multitenancy_catalogue.csv) and write a report.

Every row is one test case: an id (MT-T01, MT-I01, ...), its area, the feature, the scenario,
the expected result and the automated test that checks it. This runs each test once and
prints, per area and in total, how many passed, failed or were skipped (the database cases
need TEST_DB_NAME in .env), then writes the whole table with each result as Markdown.
No model is called: the tests stub the models and use the separate test database.

Run from the backend folder:
    python -m scripts.test_catalogue                      # report: ../docs/testing/multitenancy-test-report.md
    python -m scripts.test_catalogue --out report.md
    python -m scripts.test_catalogue --area "Data isolation"
"""
import argparse
import csv
import sys
import time
import unittest
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from app import config

CATALOGUE = config.BACKEND_DIR / "tests" / "multitenancy_catalogue.csv"
REPORT = config.BACKEND_DIR.parent / "docs" / "testing" / "multitenancy-test-report.md"


def load(path: Path = CATALOGUE) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    ids = [r["id"] for r in rows]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise SystemExit(f"Repeated ids in the catalogue: {', '.join(repeated)}")
    return rows


def run_case(test_name: str) -> tuple[str, str, float]:
    """(status, detail, seconds) of one test: passed, failed, error, skipped or missing."""
    try:
        suite = unittest.defaultTestLoader.loadTestsFromName(test_name)
    except (AttributeError, ImportError) as error:
        return "missing", f"test not found: {error}", 0.0
    if suite.countTestCases() == 0:
        return "missing", "test not found", 0.0
    result = unittest.TestResult()
    started = time.perf_counter()
    suite.run(result)
    seconds = time.perf_counter() - started
    if result.failures:
        return "failed", result.failures[0][1].strip().splitlines()[-1], seconds
    if result.errors:
        return "error", result.errors[0][1].strip().splitlines()[-1], seconds
    if result.skipped:
        return "skipped", result.skipped[0][1], seconds
    return "passed", "", seconds


def markdown(rows: list[dict], results: dict, total_seconds: float) -> str:
    counts = Counter(results[r["id"]][0] for r in rows)
    by_area = defaultdict(Counter)
    for r in rows:
        by_area[r["area"]][results[r["id"]][0]] += 1
    mark = {"passed": "✅ passed", "failed": "❌ failed", "error": "❌ error", "skipped": "⚠️ skipped", "missing": "❌ missing"}
    lines = [
        "# Multi-tenancy test report", "",
        f"Run on {datetime.now():%Y-%m-%d %H:%M} with `python -m scripts.test_catalogue` "
        f"({len(rows)} cases from `backend/tests/multitenancy_catalogue.csv`, {total_seconds:.1f} s). "
        "No model was called: the tests stub the models and use the separate test database.", "",
        f"**{counts['passed']} passed**, {counts['failed'] + counts['error'] + counts['missing']} failed, "
        f"{counts['skipped']} skipped.", "",
        "| Area | Cases | Passed | Failed | Skipped |", "|---|---:|---:|---:|---:|",
    ]
    for area, c in by_area.items():
        lines.append(f"| {area} | {sum(c.values())} | {c['passed']} | {c['failed'] + c['error'] + c['missing']} | {c['skipped']} |")
    lines += ["", "| Id | Area | Feature | Scenario | Expected | Result | Test |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        status, detail, _ = results[r["id"]]
        cell = mark[status] + (f": {detail}" if detail and status != "passed" else "")
        esc = lambda text: text.replace("|", "\\|")
        lines.append(f"| {r['id']} | {r['area']} | {esc(r['feature'])} | {esc(r['scenario'])} | {esc(r['expected'])} | "
                     f"{esc(cell)} | `{r['test'].removeprefix('tests.')}` |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the multi-tenancy test catalogue.")
    parser.add_argument("--out", type=Path, default=REPORT, help="Markdown report to write")
    parser.add_argument("--area", help="only this area, e.g. \"Data isolation\"")
    args = parser.parse_args()
    rows = [r for r in load() if not args.area or r["area"].lower() == args.area.lower()]
    if not rows:
        raise SystemExit(f"No cases in the area '{args.area}'.")
    results = {}
    started = time.perf_counter()
    for r in rows:
        results[r["id"]] = run_case(r["test"])
        status, detail, seconds = results[r["id"]]
        print(f"{r['id']:8} {status:8} {seconds:5.2f}s  {r['feature']}" + (f"  ({detail})" if status != "passed" and detail else ""))
    total = time.perf_counter() - started
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown(rows, results, total), encoding="utf-8")
    counts = Counter(s for s, _, _ in results.values())
    bad = counts["failed"] + counts["error"] + counts["missing"]
    print(f"\n{len(rows)} cases: {counts['passed']} passed, {bad} failed, {counts['skipped']} skipped ({total:.1f} s)")
    print(f"Report: {args.out}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
