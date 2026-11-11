"""Tests for tenants (app/tenants.py) and for keeping each tenant's data apart.

The first classes need no database. The database classes use a separate test database,
TEST_DB_NAME in backend/.env (never the real one): they apply the migrations to it as
DB_ADMIN_USER, then work inside one transaction per test that is rolled back, so nothing
is kept. They are skipped when TEST_DB_NAME is not set or the database cannot be reached.
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
from starlette.middleware.cors import CORSMiddleware

from app import config, db, main, tenants
from app.main import app
from app.rag import retriever
from app.routers import admin, chat, documents, feedback, session
from scripts import ingest, migrate

GIU = tenants.Tenant(uuid.UUID(int=1), "giu", "German International University")
DEMO = tenants.Tenant(uuid.UUID(int=2), "demo", "Demo University")
CLOSED = tenants.Tenant(uuid.UUID(int=3), "closed", "Closed University", status="suspended")
HOSTS = {"localhost": GIU, "127.0.0.1": GIU, "giu.localhost": GIU, "demo.localhost": DEMO, "closed.localhost": CLOSED}
SLUGS = {t.slug: t for t in HOSTS.values()}
PREFLIGHT = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}


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
        with mock.patch.object(config, "APP_ENV", "development"):
            self.assertEqual(tenants.resolve("localhost:8000", "demo"), DEMO)
        for app_env in ["production", "", "Development", "dev"]:  # anything else: the header is ignored
            with mock.patch.object(config, "APP_ENV", app_env):
                self.assertEqual(tenants.resolve("localhost:8000", "demo"), GIU, app_env)  # the host decides
                self.assertEqual(tenants.resolve("localhost:8000", "nobody"), GIU, app_env)

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
                        mock.patch.object(config, "APP_ENV", "development")]
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

    def test_x_tenant_ignored_outside_development(self):
        with mock.patch.object(config, "APP_ENV", "production"):
            self.assertEqual(self.get("localhost:8000", "/sync", **{"X-Tenant": "demo"}).json(), "giu")

    def test_unknown_and_suspended(self):
        self.assertEqual(self.get("unknown.localhost:8000", "/sync").status_code, 404)
        self.assertEqual(self.get("localhost:8000", "/sync", **{"X-Tenant": "nobody"}).status_code, 404)
        self.assertEqual(self.get("closed.localhost:8000", "/sync").status_code, 403)


class Cors(unittest.TestCase):
    def allowed(self, app_env: str, origin: str) -> bool:
        probe = FastAPI()
        probe.post("/session")(lambda: {})
        probe.add_middleware(CORSMiddleware, **main.cors_options(app_env))
        answer = TestClient(probe).options("/session", headers={"Origin": origin, **PREFLIGHT})
        return answer.headers.get("access-control-allow-origin") == origin

    def test_localhost_subdomains_only_in_development(self):
        for origin in ["http://giu.localhost:5173", "http://demo.localhost:5173", "http://127.0.0.1:5173"]:
            self.assertTrue(self.allowed("development", origin), origin)
            self.assertFalse(self.allowed("production", origin), origin)
            self.assertFalse(self.allowed("", origin), origin)
        self.assertTrue(self.allowed("production", "http://localhost:5173"))  # FRONTEND_ORIGIN, always
        for origin in ["http://evil.com:5173", "http://demo.localhost.evil.com:5173", "http://demo.localhost:9999"]:
            self.assertFalse(self.allowed("development", origin), origin)

    def test_unknown_university_404_carries_the_cors_header(self):
        if not config.is_development():
            self.skipTest("the app was started without APP_ENV=development")
        with mock.patch.object(tenants, "by_host", HOSTS.get):
            answer = client_for("unknown.localhost:8000").post(
                "/session", json={}, headers={"Origin": "http://unknown.localhost:5173"})
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


class Connections(unittest.TestCase):
    def test_tenant_is_set_in_the_transaction(self):
        sql = []
        fake = mock.MagicMock()
        fake.execute.side_effect = lambda query, params=None: sql.append((query, params))
        with mock.patch.object(db.psycopg, "connect", return_value=fake):
            db.get_connection(DEMO.id)
            db.get_connection()
        self.assertEqual(sql, [("SELECT set_config('app.tenant_id', %s, true)", (str(DEMO.id),))])  # only with a tenant


# ---------------------------------------------------------------- the test database

_migrated: set[str] = set()


def test_database() -> str:
    """The migrated test database (TEST_DB_NAME); skips the test when there is none."""
    name = config.TEST_DB_NAME
    if not name:
        raise unittest.SkipTest("TEST_DB_NAME is not set in backend/.env")
    if name == config.DB_NAME:
        raise unittest.SkipTest("TEST_DB_NAME must be a separate database, not DB_NAME")
    if name not in _migrated:
        try:
            migrate.migrate(name, log=lambda message: None)
        except psycopg.OperationalError as error:
            raise unittest.SkipTest(f"the test database {name} cannot be reached: {error}")
        _migrated.add(name)
    return name


class SharedConnection:
    """get_connection() stand-in: every `with get_connection(tenant_id) as conn:` gets the same
    connection, with that tenant set as get_connection does, and nothing is committed, so
    the test can roll everything back."""

    def __init__(self, conn):
        self.conn = conn

    def __call__(self, tenant_id=None):
        db.set_tenant(self.conn, tenant_id)
        return self

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


class TestDatabaseCase(unittest.TestCase):
    """One transaction on the test database, rolled back after the test, with two made-up
    tenants A and B. `role`: None = the owner (DB_ADMIN_USER), "giu_app" = the app's role."""
    role = None

    def setUp(self):
        self.conn = db.get_admin_connection(dbname=test_database())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        suffix = uuid.uuid4().hex[:8]
        self.a = self.add_tenant(f"test-a-{suffix}")
        self.b = self.add_tenant(f"test-b-{suffix}")
        for tenant, text in [(self.a, "Tenant A secret: the Zebra Lab is in Z901."),
                             (self.b, "Tenant B secret: the Owl Lab is in W123.")]:
            db.set_tenant(self.conn, tenant.id)  # the owner may be under FORCE row-level security too
            self.conn.execute("INSERT INTO chunks (tenant_id, agent, audience, source, content, embedding) "
                              "VALUES (%s, 'labs_research', '{student,staff}', 'lab.md', %s, '{1.0,0.0}')",
                              (tenant.id, text))
        db.set_tenant(self.conn, self.a.id)
        self.a_conversation = self.insert("INSERT INTO conversations (tenant_id, user_type, agent) "
                                          "VALUES (%s, 'student', 'labs_research') RETURNING id", (self.a.id,))
        self.a_message = self.insert("INSERT INTO messages (tenant_id, conversation_id, role, content) "
                                     "VALUES (%s, %s, 'assistant', 'A answer') RETURNING id", (self.a.id, self.a_conversation))
        db.set_tenant(self.conn, None)
        if self.role:  # for the rest of the transaction (no password needed: the owner switches role)
            try:
                with self.conn.transaction():  # a savepoint, so a failure leaves the transaction usable
                    self.conn.execute(f"SET LOCAL ROLE {self.role}")
            except psycopg.Error as error:
                self.skipTest(f"cannot act as {self.role}: {error}")

    def add_tenant(self, slug: str) -> tenants.Tenant:
        tenant_id = self.insert("INSERT INTO tenants (slug, name) VALUES (%s, %s) RETURNING id", (slug, slug.upper()))
        self.conn.execute("INSERT INTO tenant_domains (host, tenant_id, is_primary) VALUES (%s, %s, true)",
                          (f"{slug}.test", tenant_id))
        return tenants.Tenant(tenant_id, slug, slug.upper())

    def insert(self, sql, params):
        return self.conn.execute(sql, params).fetchone()[0]

    def rows(self, sql, params=None):
        return self.conn.execute(sql, params).fetchall()


class AppIsolation(TestDatabaseCase):
    """The app code keeps tenants apart through its WHERE clauses alone: run as the owner
    (a superuser skips row-level security), so the policies cannot hide a missing filter."""

    def setUp(self):
        super().setUp()
        shared = SharedConnection(self.conn)
        for module in [tenants, retriever, chat, session, feedback, documents, admin, ingest]:
            patch = mock.patch.object(module, "get_connection", shared)
            patch.start()
            self.addCleanup(patch.stop)
        tenants._by_host.clear()
        self.addCleanup(tenants._by_host.clear)

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
        db.set_tenant(self.conn, self.a.id)
        self.assertEqual(self.rows("SELECT tenant_id FROM feedback WHERE id = %s", (answer.json()["feedback_id"],)),
                         [(self.a.id,)])

    def test_new_conversations_belong_to_the_host_tenant(self):
        answer = self.client(self.b).post("/session", json={"user_type": "student", "agent": "labs_research"})
        db.set_tenant(self.conn, self.b.id)
        self.assertEqual(self.rows("SELECT tenant_id FROM conversations WHERE id = %s", (answer.json()["conversation_id"],)),
                         [(self.b.id,)])

    def test_deleting_touches_only_the_current_tenant(self):
        with tenants.using(self.b):
            ingest.remove_missing_files("labs_research", [])  # B's folder is empty
            admin.delete_chunks("labs_research", "lab.md")
        for tenant, expected in [(self.a, 1), (self.b, 0)]:
            db.set_tenant(self.conn, tenant.id)
            self.assertEqual(self.rows("SELECT count(*) FROM chunks WHERE tenant_id = %s", (tenant.id,)), [(expected,)])

    def test_database_refuses_cross_tenant_links(self):
        db.set_tenant(self.conn, self.b.id)
        with self.assertRaises(psycopg.errors.ForeignKeyViolation), self.conn.transaction():
            self.conn.execute("INSERT INTO messages (tenant_id, conversation_id, role, content) VALUES (%s, %s, 'user', 'x')",
                              (self.b.id, self.a_conversation))
        with self.assertRaises(psycopg.errors.ForeignKeyViolation), self.conn.transaction():
            self.conn.execute("INSERT INTO feedback (tenant_id, message_id, rating) VALUES (%s, %s, 1)",
                              (self.b.id, self.a_message))


class AppIsolationAsAppRole(AppIsolation):
    """The same tests as the app's role, with row-level security on top of the WHERE clauses."""
    role = "giu_app"


class RowLevelSecurity(TestDatabaseCase):
    """As giu_app, the database itself keeps tenants apart, even when a query forgets its WHERE."""
    role = "giu_app"
    TABLES = ["chunks", "conversations", "messages", "feedback"]

    def count(self, table: str) -> int:
        return self.rows(f"SELECT count(*) FROM {table}")[0][0]  # no WHERE on purpose

    def test_no_tenant_set_sees_no_rows(self):
        db.set_tenant(self.conn, None)
        for table in self.TABLES:
            self.assertEqual(self.count(table), 0, table)
        self.assertEqual(self.rows("SELECT current_setting('app.tenant_id', true)"), [("",)])

    def test_forgotten_where_sees_only_the_current_tenant(self):
        db.set_tenant(self.conn, self.a.id)
        self.assertEqual(self.rows("SELECT content FROM chunks"), [("Tenant A secret: the Zebra Lab is in Z901.",)])
        self.assertEqual({tenant for (tenant,) in self.rows("SELECT tenant_id FROM conversations")}, {self.a.id})
        db.set_tenant(self.conn, self.b.id)
        self.assertEqual(self.rows("SELECT content FROM chunks"), [("Tenant B secret: the Owl Lab is in W123.",)])
        self.assertEqual(self.count("conversations"), 0)
        self.assertEqual(self.count("messages"), 0)

    def test_rows_for_another_tenant_are_refused(self):
        db.set_tenant(self.conn, self.a.id)
        inserts = [("INSERT INTO chunks (tenant_id, agent, source, content) VALUES (%s, 'labs_research', 'x.md', 'x')", (self.b.id,)),
                   ("INSERT INTO conversations (tenant_id, user_type, agent) VALUES (%s, 'student', 'labs_research')", (self.b.id,)),
                   ("UPDATE chunks SET tenant_id = %s", (self.b.id,))]  # moving own rows to B
        for sql, params in inserts:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege, msg=sql), self.conn.transaction():
                self.conn.execute(sql, params)
        db.set_tenant(self.conn, None)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege), self.conn.transaction():
            self.conn.execute("INSERT INTO chunks (tenant_id, agent, source, content) VALUES (%s, 'labs_research', 'x.md', 'x')",
                              (self.a.id,))  # no tenant set: no rows can be written at all

    def test_update_and_delete_without_where_touch_only_the_current_tenant(self):
        db.set_tenant(self.conn, self.a.id)
        self.assertEqual(self.conn.execute("UPDATE chunks SET content = 'changed'").rowcount, 1)
        self.assertEqual(self.conn.execute("DELETE FROM chunks").rowcount, 1)
        db.set_tenant(self.conn, self.b.id)
        self.assertEqual(self.rows("SELECT content FROM chunks"), [("Tenant B secret: the Owl Lab is in W123.",)])

    def test_the_role_has_no_other_powers(self):
        self.assertEqual(self.rows("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"),
                         [(False, False)])
        for sql in ["SELECT * FROM schema_migrations",
                    "INSERT INTO tenants (slug, name) VALUES ('evil', 'Evil')",
                    "DELETE FROM tenant_domains",
                    "ALTER TABLE chunks DISABLE ROW LEVEL SECURITY"]:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege, msg=sql), self.conn.transaction():
                self.conn.execute(sql)

    def test_the_tenant_setting_ends_with_its_transaction(self):
        """get_connection's set_config(..., true) cannot leak into the next transaction."""
        conn = db.get_admin_connection(dbname=test_database())
        self.addCleanup(conn.close)
        conn.execute("SET ROLE giu_app")
        db.set_tenant(conn, self.a.id)
        conn.commit()
        self.assertEqual(conn.execute("SELECT current_setting('app.tenant_id', true)").fetchone(), ("",))
        self.assertEqual(conn.execute("SELECT count(*) FROM chunks").fetchone(), (0,))  # '' means no tenant, not an error


if __name__ == "__main__":
    unittest.main()
