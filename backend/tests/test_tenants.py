"""Tests for tenants (app/tenants.py) and for keeping each tenant's data apart.

The first classes need no database. DatabaseIsolation uses the real PostgreSQL database
from backend/.env, inside one transaction that is rolled back at the end, so nothing is
kept; it is skipped when the database cannot be reached or the migrations are not applied.
No chat model or embedding service is called.

Run from the backend folder:
    python -m unittest discover -s tests -v
"""
import unittest
import uuid
from unittest import mock

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config, tenants
from app.main import app
from app.rag import retriever
from app.routers import admin, chat, documents, feedback, session
from scripts import ingest

GIU = tenants.Tenant(uuid.UUID(int=1), "giu", "German International University")
DEMO = tenants.Tenant(uuid.UUID(int=2), "demo", "Demo University")
CLOSED = tenants.Tenant(uuid.UUID(int=3), "closed", "Closed University", status="suspended")
HOSTS = {"localhost": GIU, "127.0.0.1": GIU, "giu.localhost": GIU, "demo.localhost": DEMO, "closed.localhost": CLOSED}
SLUGS = {t.slug: t for t in HOSTS.values()}


def client_for(host: str) -> TestClient:
    return TestClient(app, base_url=f"http://{host}")


class Resolving(unittest.TestCase):
    def setUp(self):
        self.patches = [mock.patch.object(tenants, "by_host", HOSTS.get), mock.patch.object(tenants, "by_slug", SLUGS.get)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_host_name(self):
        self.assertEqual(tenants.host_name("GIU.localhost:8000"), "giu.localhost")
        self.assertEqual(tenants.host_name("localhost"), "localhost")
        self.assertEqual(tenants.host_name("[::1]:8000"), "::1")
        self.assertEqual(tenants.host_name("chat.example.edu."), "chat.example.edu")

    def test_plain_localhost_is_giu(self):
        self.assertEqual(tenants.resolve("localhost:8000", None), GIU)
        self.assertEqual(tenants.resolve("127.0.0.1:8000", None), GIU)
        self.assertEqual(tenants.resolve("demo.localhost:8000", None), DEMO)
        self.assertIsNone(tenants.resolve("unknown.localhost:8000", None))

    def test_tenant_header_only_in_development(self):
        with mock.patch.object(config, "TENANT_HEADER_ALLOWED", True):
            self.assertEqual(tenants.resolve("localhost:8000", "demo"), DEMO)
        with mock.patch.object(config, "TENANT_HEADER_ALLOWED", False):
            self.assertEqual(tenants.resolve("localhost:8000", "demo"), GIU)  # the host decides

    def test_no_tenant_outside_a_request(self):
        with self.assertRaises(RuntimeError):
            tenants.current()
        with tenants.using(DEMO):
            self.assertEqual(tenants.current_id(), DEMO.id)
        with self.assertRaises(RuntimeError):
            tenants.current()

    def test_data_folders(self):
        self.assertEqual(tenants.data_dir(GIU), config.RAW_DATA_DIR)  # GIU's documents stay where they are
        self.assertEqual(tenants.data_dir(DEMO), config.TENANTS_DATA_DIR / "demo")


class Middleware(unittest.TestCase):
    """The tenant reaches sync and async endpoints; unknown and suspended tenants are refused."""

    def setUp(self):
        self.patches = [mock.patch.object(tenants, "by_host", HOSTS.get), mock.patch.object(tenants, "by_slug", SLUGS.get),
                        mock.patch.object(config, "TENANT_HEADER_ALLOWED", True)]
        for p in self.patches:
            p.start()
        probe = FastAPI()
        probe.add_middleware(tenants.TenantMiddleware)
        probe.get("/sync")(lambda: tenants.current().slug)  # runs in a worker thread

        @probe.get("/async")
        async def in_event_loop():
            return tenants.current().slug

        self.probe = probe

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def get(self, host, path, **headers):
        return TestClient(self.probe, base_url=f"http://{host}").get(path, headers=headers)

    def test_tenant_reaches_the_endpoints(self):
        for path in ["/sync", "/async"]:
            self.assertEqual(self.get("localhost:8000", path).json(), "giu")
            self.assertEqual(self.get("demo.localhost:8000", path).json(), "demo")
            self.assertEqual(self.get("localhost:8000", path, **{"X-Tenant": "demo"}).json(), "demo")

    def test_unknown_and_suspended(self):
        self.assertEqual(self.get("unknown.localhost:8000", "/sync").status_code, 404)
        self.assertEqual(self.get("localhost:8000", "/sync", **{"X-Tenant": "nobody"}).status_code, 404)
        self.assertEqual(self.get("closed.localhost:8000", "/sync").status_code, 403)

    def test_cors_for_localhost_subdomains(self):
        client = client_for("demo.localhost:8000")
        preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
        for origin in ["http://localhost:5173", "http://giu.localhost:5173", "http://demo.localhost:5173"]:
            answer = client.options("/session", headers={"Origin": origin, **preflight})
            self.assertEqual(answer.headers.get("access-control-allow-origin"), origin)
        for origin in ["http://evil.com:5173", "http://demo.localhost.evil.com:5173", "http://demo.localhost:9999"]:
            answer = client.options("/session", headers={"Origin": origin, **preflight})
            self.assertIsNone(answer.headers.get("access-control-allow-origin"), origin)
        # An unknown university's 404 still carries the CORS header, so the page can show it.
        answer = client_for("unknown.localhost:8000").post("/session", json={}, headers={"Origin": "http://unknown.localhost:5173"})
        self.assertEqual((answer.status_code, answer.headers.get("access-control-allow-origin")),
                         (404, "http://unknown.localhost:5173"))


class AdminLogins(unittest.TestCase):
    def test_a_login_works_only_for_its_own_tenant(self):
        with mock.patch.object(tenants, "by_host", HOSTS.get), mock.patch.object(config, "ADMIN_PASSWORD", "secret"):
            admin._tokens.clear()
            token = client_for("localhost:8000").post("/admin/login", json={"password": "secret"}).json()["token"]
            auth = {"Authorization": f"Bearer {token}"}
            self.assertEqual(client_for("giu.localhost:8000").get("/admin/documents", headers=auth).status_code, 200)
            self.assertEqual(client_for("demo.localhost:8000").get("/admin/documents", headers=auth).status_code, 401)


class SharedConnection:
    """get_connection() stand-in: every `with get_connection() as conn:` gets the same
    connection and nothing is committed, so the test can roll everything back."""

    def __init__(self, conn):
        self.conn = conn

    def __call__(self):
        return self

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


class DatabaseIsolation(unittest.TestCase):
    """Two made-up tenants, A and B, in the real database (rolled back): neither sees the other's data."""

    def setUp(self):
        try:
            self.conn = psycopg.connect(host=config.DB_HOST, port=config.DB_PORT, dbname=config.DB_NAME,
                                        user=config.DB_USER, password=config.DB_PASSWORD, connect_timeout=3)
        except psycopg.Error:
            self.skipTest("the database is not reachable")
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        if not self.conn.execute("SELECT to_regclass('tenant_domains')").fetchone()[0]:
            self.skipTest("migration 001 is not applied")
        shared = SharedConnection(self.conn)
        for module in [tenants, retriever, chat, session, feedback, documents, admin, ingest]:
            patch = mock.patch.object(module, "get_connection", shared)
            patch.start()
            self.addCleanup(patch.stop)
        tenants._by_host.clear()
        self.addCleanup(tenants._by_host.clear)

        suffix = uuid.uuid4().hex[:8]
        self.a = self.add_tenant(f"test-a-{suffix}")
        self.b = self.add_tenant(f"test-b-{suffix}")
        for tenant, text in [(self.a, "Tenant A secret: the Zebra Lab is in Z901."),
                             (self.b, "Tenant B secret: the Owl Lab is in W123.")]:
            self.conn.execute("INSERT INTO chunks (tenant_id, agent, audience, source, content, embedding) "
                              "VALUES (%s, 'labs_research', '{student,staff}', 'lab.md', %s, '{1.0,0.0}')",
                              (tenant.id, text))
        self.a_conversation = self.insert("INSERT INTO conversations (tenant_id, user_type, agent) "
                                          "VALUES (%s, 'student', 'labs_research') RETURNING id", (self.a.id,))
        self.a_message = self.insert("INSERT INTO messages (tenant_id, conversation_id, role, content) "
                                     "VALUES (%s, %s, 'assistant', 'A answer') RETURNING id", (self.a.id, self.a_conversation))

    def add_tenant(self, slug: str) -> tenants.Tenant:
        tenant_id = self.insert("INSERT INTO tenants (slug, name) VALUES (%s, %s) RETURNING id", (slug, slug.upper()))
        self.conn.execute("INSERT INTO tenant_domains (host, tenant_id, is_primary) VALUES (%s, %s, true)",
                          (f"{slug}.test", tenant_id))
        return tenants.Tenant(tenant_id, slug, slug.upper())

    def insert(self, sql, params):
        return self.conn.execute(sql, params).fetchone()[0]

    def client(self, tenant: tenants.Tenant) -> TestClient:
        return client_for(f"{tenant.slug}.test:8000")  # the real host lookup in tenant_domains

    def test_each_tenant_retrieves_only_its_own_chunks(self):
        with tenants.using(self.a):
            self.assertEqual([c[0] for c in retriever.load_chunks("labs_research", "student")],
                             ["Tenant A secret: the Zebra Lab is in Z901."])
        with tenants.using(self.b), mock.patch.object(retriever, "embed_text", return_value=[1.0, 0.0]):
            found = retriever.retrieve("where is the Zebra Lab?", "labs_research", "student")
            self.assertEqual([c.content for c in found], ["Tenant B secret: the Owl Lab is in W123."])

    def test_host_decides_the_tenant(self):
        self.assertEqual(tenants.resolve(f"{self.a.slug}.test:8000", None).id, self.a.id)
        self.assertIsNone(tenants.resolve(f"nobody-{self.a.slug}.test", None))

    def test_conversations_of_another_tenant_are_not_found(self):
        body = {"conversation_id": self.a_conversation, "query": "hello"}
        self.assertEqual(self.client(self.b).post("/chat", json=body).status_code, 404)  # before any model call
        self.assertEqual(self.client(self.b).post("/feedback", json={"message_id": self.a_message, "rating": 5}).status_code, 404)
        self.assertEqual(self.client(self.b).get(f"/documents/{self.a_conversation}/any-token").status_code, 404)
        answer = self.client(self.a).post("/feedback", json={"message_id": self.a_message, "rating": 5})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(self.conn.execute("SELECT tenant_id FROM feedback WHERE id = %s",
                                           (answer.json()["feedback_id"],)).fetchone()[0], self.a.id)

    def test_new_conversations_belong_to_the_host_tenant(self):
        answer = self.client(self.b).post("/session", json={"user_type": "student", "agent": "labs_research"})
        tenant_id = self.conn.execute("SELECT tenant_id FROM conversations WHERE id = %s",
                                      (answer.json()["conversation_id"],)).fetchone()[0]
        self.assertEqual(tenant_id, self.b.id)

    def test_deleting_touches_only_the_current_tenant(self):
        with tenants.using(self.b):
            ingest.remove_missing_files("labs_research", [])  # B's folder is empty
            admin.delete_chunks("labs_research", "lab.md")
        counts = dict(self.conn.execute("SELECT tenant_id, count(*) FROM chunks WHERE tenant_id = ANY(%s) GROUP BY 1",
                                        ([self.a.id, self.b.id],)).fetchall())
        self.assertEqual(counts, {self.a.id: 1})

    def test_database_refuses_cross_tenant_links(self):
        if not self.conn.execute("SELECT 1 FROM pg_constraint WHERE conname = 'messages_conversation_tenant_fkey'").fetchone():
            self.skipTest("migration 002 is not applied")
        with self.assertRaises(psycopg.errors.ForeignKeyViolation), self.conn.transaction():
            self.conn.execute("INSERT INTO messages (tenant_id, conversation_id, role, content) VALUES (%s, %s, 'user', 'x')",
                              (self.b.id, self.a_conversation))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation), self.conn.transaction():
            self.conn.execute("INSERT INTO feedback (tenant_id, message_id, rating) VALUES (%s, %s, 1)",
                              (self.b.id, self.a_message))


if __name__ == "__main__":
    unittest.main()
