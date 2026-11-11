"""Tests for the migration runner (scripts/migrate.py). No database is used: the
connection is replaced by a stand-in that records the SQL it is given.

Run from the backend folder:
    python -m unittest discover -s tests -v
"""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from scripts import migrate


class FakeConnection:
    """Records the SQL; `applied` is what SELECT FROM schema_migrations returns."""

    def __init__(self, log: list, applied: list[str]):
        self.log, self.applied = log, applied

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.log.append("commit" if exc[0] is None else "rollback")

    def execute(self, sql, params=None):
        self.log.append((sql, params))
        return [(name,) for name in self.applied] if sql.startswith("SELECT filename") else []


class MigrationFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, *names):
        for name in names:
            (self.folder / name).write_text(f"-- {name}", encoding="utf-8")

    def test_files_in_number_order(self):
        self.write("010_later.sql", "001_tenants.sql", "002_rls.sql", "notes.txt")
        self.assertEqual([p.name for p in migrate.migration_files(self.folder)],
                         ["001_tenants.sql", "002_rls.sql", "010_later.sql"])

    def test_bad_names_and_repeated_numbers_are_refused(self):
        self.write("1_tenants.sql")
        with self.assertRaises(SystemExit):
            migrate.migration_files(self.folder)
        (self.folder / "1_tenants.sql").unlink()
        self.write("002_a.sql", "002_b.sql")
        with self.assertRaises(SystemExit):
            migrate.migration_files(self.folder)

    def test_project_migrations_are_well_named(self):
        names = [p.name for p in migrate.migration_files()]
        self.assertEqual(names[:2], ["000_base.sql", "001_tenants.sql"])


class Applying(unittest.TestCase):
    def test_only_pending_files_run_each_in_its_own_transaction(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        for name in ["000_base.sql", "001_tenants.sql", "002_rls.sql"]:
            (folder / name).write_text(f"SQL OF {name}", encoding="utf-8")
        log = []
        connect = lambda: FakeConnection(log, applied=["000_base.sql"])
        with mock.patch.object(migrate, "MIGRATIONS_DIR", folder), \
             mock.patch.object(migrate, "get_connection", connect), \
             mock.patch.object(sys, "argv", ["migrate"]), redirect_stdout(io.StringIO()):
            migrate.main()
        run = [entry[0] for entry in log if isinstance(entry, tuple) and entry[0].startswith("SQL OF")]
        self.assertEqual(run, ["SQL OF 001_tenants.sql", "SQL OF 002_rls.sql"])  # 000 was applied before
        recorded = [entry[1] for entry in log if isinstance(entry, tuple) and entry[0].startswith("INSERT")]
        self.assertEqual(recorded, [("001_tenants.sql",), ("002_rls.sql",)])
        # One transaction to read schema_migrations, then one per file (its SQL and its record).
        self.assertEqual(log.count("commit"), 3)
        first_file = log.index(("SQL OF 001_tenants.sql", None))
        self.assertEqual(log[first_file + 1:first_file + 3], [(mock.ANY, ("001_tenants.sql",)), "commit"])

    def test_status_applies_nothing(self):
        log = []
        with mock.patch.object(migrate, "get_connection", lambda: FakeConnection(log, applied=[])), \
             mock.patch.object(sys, "argv", ["migrate", "--status"]), redirect_stdout(io.StringIO()) as out:
            migrate.main()
        self.assertFalse(any(isinstance(e, tuple) and e[0].startswith("INSERT") for e in log))
        self.assertIn("pending  001_tenants.sql", out.getvalue())


if __name__ == "__main__":
    unittest.main()
