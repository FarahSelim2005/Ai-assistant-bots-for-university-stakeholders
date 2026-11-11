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
from pathlib import Path
from unittest import mock

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

import app.agents as registry
from app import config, db, main, tenants
from app.agents import directory
from app.agents.templates import GIU_AGENT_IDS, GIU_AGENTS, TEMPLATES
from tests import giu_agents
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
        with mock.patch.object(tenants, "by_host", HOSTS.get), mock.patch.object(config, "ADMIN_PASSWORD", "secret"),              giu_agents.active():  # GIU's assistants (demo, made up here, has none)
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
    tenants A and B, each with one assistant (made from the Labs & Research template) that has
    one chunk. `role`: None = the owner (DB_ADMIN_USER), "giu_app" = the app's role."""
    role = None

    def setUp(self):
        self.conn = db.get_admin_connection(dbname=test_database())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        suffix = uuid.uuid4().hex[:8]
        self.a = self.add_tenant(f"test-a-{suffix}")
        self.b = self.add_tenant(f"test-b-{suffix}")
        self.agent = {}
        for tenant, text in [(self.a, "Tenant A secret: the Zebra Lab is in Z901."),
                             (self.b, "Tenant B secret: the Owl Lab is in W123.")]:
            db.set_tenant(self.conn, tenant.id)  # the owner may be under FORCE row-level security too
            self.agent[tenant.slug] = self.insert(
                "INSERT INTO agents (tenant_id, template_key, name, description, folder) "
                "VALUES (%s, 'labs_research', %s, 'Labs and rooms', 'labs_research') RETURNING id", (tenant.id, f"{tenant.name} Labs"))
            self.conn.execute("INSERT INTO chunks (tenant_id, agent_id, audience, source, content, embedding) "
                              "VALUES (%s, %s, '{student,staff}', 'lab.md', %s, '{1.0,0.0}')",
                              (tenant.id, self.agent[tenant.slug], text))
        self.a_agent, self.b_agent = self.agent[self.a.slug], self.agent[self.b.slug]
        db.set_tenant(self.conn, self.a.id)
        self.a_conversation = self.insert("INSERT INTO conversations (tenant_id, agent_id, user_type) "
                                          "VALUES (%s, %s, 'student') RETURNING id", (self.a.id, self.a_agent))
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


    def use_app_code(self):
        """The app's code runs on this test's connection (and transaction)."""
        shared = SharedConnection(self.conn)
        for module in [tenants, retriever, chat, session, feedback, documents, admin, ingest, registry, directory]:
            patch = mock.patch.object(module, "get_connection", shared)
            patch.start()
            self.addCleanup(patch.stop)
        tenants._by_host.clear()
        self.addCleanup(tenants._by_host.clear)

    def client(self, tenant: tenants.Tenant) -> TestClient:
        return client_for(f"{tenant.slug}.test:8000")  # the real host lookup in tenant_domains


class AppIsolation(TestDatabaseCase):
    """The app code keeps tenants apart through its WHERE clauses alone: run as the owner
    (a superuser skips row-level security), so the policies cannot hide a missing filter."""

    def setUp(self):
        super().setUp()
        self.use_app_code()

    def test_each_tenant_retrieves_only_its_own_chunks(self):
        with tenants.using(self.a):
            self.assertEqual([c[0] for c in retriever.load_chunks(str(self.a_agent), "student")],
                             ["Tenant A secret: the Zebra Lab is in Z901."])
        with tenants.using(self.b), mock.patch.object(retriever, "embed_text", return_value=[1.0, 0.0]):
            found = retriever.retrieve("where is the Zebra Lab?", str(self.b_agent), "student")
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
            ingest.remove_missing_files(str(self.b_agent), [])  # B's folder is empty
            admin.delete_chunks(str(self.b_agent), "lab.md")
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
    TABLES = ["chunks", "conversations", "messages", "feedback", "agents"]

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
        inserts = [("INSERT INTO chunks (tenant_id, agent_id, source, content) VALUES (%s, %s, 'x.md', 'x')", (self.b.id, self.b_agent)),
                   ("INSERT INTO conversations (tenant_id, agent_id, user_type) VALUES (%s, %s, 'student')", (self.b.id, self.b_agent)),
                   ("INSERT INTO agents (tenant_id, name, folder) VALUES (%s, 'Sneaky', 'sneaky')", (self.b.id,)),
                   ("UPDATE chunks SET tenant_id = %s", (self.b.id,)),  # moving own rows to B
                   ("UPDATE agents SET tenant_id = %s", (self.b.id,))]
        for sql, params in inserts:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege, msg=sql), self.conn.transaction():
                self.conn.execute(sql, params)
        db.set_tenant(self.conn, None)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege), self.conn.transaction():
            self.conn.execute("INSERT INTO chunks (tenant_id, agent_id, source, content) VALUES (%s, %s, 'x.md', 'x')",
                              (self.a.id, self.a_agent))  # no tenant set: no rows can be written at all

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


class AgentTables(TestDatabaseCase):
    """Migrations 004 and 005: the templates and GIU's assistants are exactly the code's
    (app/agents/templates.py: TEMPLATES and GIU_AGENTS)."""
    FIELDS = ["name", "summary", "subtitle", "description", "audiences", "answer_mode", "prompt_mode", "instructions",
              "fallback_en", "fallback_ar", "welcome", "placeholder", "examples", "skills", "max_answer_tokens", "position"]

    def test_templates_are_the_codes_templates(self):
        for t in TEMPLATES:
            row = self.rows(f"SELECT {', '.join(self.FIELDS)} FROM agent_templates WHERE key = %s", (t["key"],))
            self.assertEqual(row, [tuple(t[f] for f in self.FIELDS)], t["key"])  # byte for byte (no carriage returns)

    def test_giu_has_the_four_assistants_with_fixed_ids(self):
        giu = self.rows("SELECT id FROM tenants WHERE slug = 'giu'")[0][0]
        db.set_tenant(self.conn, giu)
        rows = self.rows(f"SELECT id, template_key, {', '.join(self.FIELDS)}, model, backup_models, "
                         "similarity_threshold, live FROM agents WHERE tenant_id = %s ORDER BY position", (giu,))
        self.assertEqual(len(rows), 4)
        for row, t in zip(rows, GIU_AGENTS):
            self.assertEqual(row[:2], (GIU_AGENT_IDS[t["key"]], t["key"]))
            self.assertEqual(row[2:-4], tuple(t[f] for f in self.FIELDS), t["key"])
            self.assertEqual(row[-4:], (None, [], None, True))  # the platform's models and threshold; live

    def test_an_agent_of_another_tenant_cannot_be_used(self):
        db.set_tenant(self.conn, self.a.id)
        for sql in ["INSERT INTO chunks (tenant_id, agent_id, source, content) VALUES (%s, %s, 'x.md', 'x')",
                    "INSERT INTO conversations (tenant_id, agent_id, user_type) VALUES (%s, %s, 'student')"]:
            with self.assertRaises(psycopg.errors.ForeignKeyViolation, msg=sql), self.conn.transaction():
                self.conn.execute(sql, (self.a.id, self.b_agent))

    def test_a_changed_description_loses_its_embedding(self):
        db.set_tenant(self.conn, self.a.id)
        embedding = lambda: self.rows("SELECT description_embedding FROM agents WHERE id = %s", (self.a_agent,))
        self.conn.execute("UPDATE agents SET description_embedding = '{1,0}' WHERE id = %s", (self.a_agent,))
        self.conn.execute("UPDATE agents SET name = 'Renamed' WHERE id = %s", (self.a_agent,))
        self.assertEqual(embedding(), [([1.0, 0.0],)])  # another change keeps it
        self.conn.execute("UPDATE agents SET description = 'Something else' WHERE id = %s", (self.a_agent,))
        self.assertEqual(embedding(), [(None,)])

    def test_tenant_settings(self):
        self.assertEqual(self.rows("SELECT short_name, has_cv_model, campus_map, logo_url, brand_primary FROM tenants "
                                   "WHERE slug = 'giu'"), [("GIU", True, True, "/giu-logo.jpg", "#c4161c")])
        giu = self.rows("SELECT id FROM tenants WHERE slug = 'giu'")[0][0]
        db.set_tenant(self.conn, giu)
        self.assertEqual(self.rows("SELECT folder FROM agents WHERE tenant_id = %s ORDER BY position", (giu,)),
                         [("graduation_advising",), ("hr_policies",), ("internship_career",), ("labs_research",)])
        self.assertEqual(self.rows("SELECT short_name, has_cv_model, campus_map FROM tenants WHERE id = %s", (self.a.id,)),
                         [("", False, False)])  # a new university: no CV model, no map; its short name is its name
        self.assertEqual(self.a.short, self.a.name)

    def test_005_gives_old_template_copies_the_new_text(self):
        """Assistants that 004 made from a template for another university (still GIU's text) get
        the new template; changed ones and GIU's own keep theirs. Also: 005 can run twice."""
        giu = self.rows("SELECT id FROM tenants WHERE slug = 'giu'")[0][0]
        db.set_tenant(self.conn, giu)
        giu_career = self.rows("SELECT instructions FROM agents WHERE id = %s", (GIU_AGENT_IDS["internship_career"],))[0][0]
        db.set_tenant(self.conn, self.a.id)
        old_copy = self.insert("INSERT INTO agents (tenant_id, template_key, name, instructions, skills, folder) "
                               "VALUES (%s, 'internship_career', 'Careers', %s, '{files,cv}', 'careers') RETURNING id",
                               (self.a.id, giu_career))
        own = self.insert("INSERT INTO agents (tenant_id, template_key, name, instructions, folder) "
                          "VALUES (%s, 'internship_career', 'Mine', 'My own words.', 'mine') RETURNING id", (self.a.id,))
        self.conn.execute(Path("migrations/005_skills.sql").read_text(encoding="utf-8").replace("\r\n", "\n"))
        career = next(t for t in TEMPLATES if t["key"] == "internship_career")
        db.set_tenant(self.conn, self.a.id)
        self.assertEqual(self.rows("SELECT instructions, prompt_mode, skills, welcome FROM agents WHERE id = %s", (old_copy,)),
                         [(career["instructions"], "composed", [s for s in career["skills"] if s != "cv"], career["welcome"])])
        self.assertEqual(self.rows("SELECT instructions FROM agents WHERE id = %s", (own,)), [("My own words.",)])
        db.set_tenant(self.conn, giu)
        self.assertEqual(self.rows("SELECT instructions, prompt_mode FROM agents WHERE id = %s",
                                   (GIU_AGENT_IDS["internship_career"],)), [(giu_career, "complete")])


class AssistantsApi(TestDatabaseCase):
    """Universities create and change their own assistants (as giu_app, through the API)."""
    role = "giu_app"

    def setUp(self):
        super().setUp()
        self.use_app_code()
        patch = mock.patch.object(config, "ADMIN_PASSWORD", "")  # admin routes open (no login needed)
        patch.start()
        self.addCleanup(patch.stop)

    def test_create_change_and_hide(self):
        a, b = self.client(self.a), self.client(self.b)
        made = a.post("/admin/agents", json={"template_key": "hr_policies", "name": "People Office"})
        self.assertEqual(made.status_code, 200, made.text)
        new_id = made.json()["id"]
        self.assertEqual([x["name"] for x in a.get("/admin/agents").json()], [f"{self.a.name} Labs", "People Office"])
        self.assertEqual([x["name"] for x in b.get("/admin/agents").json()], [f"{self.b.name} Labs"])  # only B's own
        hr = next(x for x in a.get("/admin/agents").json() if x["id"] == new_id)
        self.assertEqual((hr["audiences"], hr["answer_mode"], hr["template_key"]), (["staff"], "docs", "hr_policies"))

        start = lambda client, user_type: client.post("/session", json={"user_type": user_type, "agent": new_id})
        self.assertEqual(start(a, "staff").status_code, 200)
        self.assertEqual(start(a, "student").status_code, 403)   # HR template: staff only
        self.assertEqual(start(b, "staff").status_code, 404)     # another university's assistant

        changed = a.put(f"/admin/agents/{new_id}", json={"name": "HR Desk", "audiences": ["student", "staff"]})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(registry.load_agent(self.a.id, new_id).display_name, "HR Desk")  # the cache reloaded
        self.assertEqual(start(a, "student").status_code, 200)
        self.assertEqual(b.put(f"/admin/agents/{new_id}", json={"name": "Stolen"}).status_code, 404)

        self.assertEqual(a.put(f"/admin/agents/{new_id}", json={"live": False}).status_code, 200)
        self.assertEqual(start(a, "staff").status_code, 404)     # hidden

    def test_folders_are_readable_and_unique(self):
        a = self.client(self.a)
        first = a.post("/admin/agents", json={"template_key": "hr_policies"}).json()["id"]
        second = a.post("/admin/agents", json={"template_key": "hr_policies", "name": "HR again"}).json()["id"]
        third = a.post("/admin/agents", json={"name": "Labs Research!"}).json()["id"]
        folders = {x["id"]: x["folder"] for x in a.get("/admin/agents").json()}
        self.assertEqual([folders[first], folders[second], folders[third]], ["hr_policies", "hr_policies_2", "labs_research_2"])

    def test_tenant_page_data(self):
        """GET /tenant: what the frontend shows for this university (its own look and assistants only)."""
        db.set_tenant(self.conn, None)
        page = self.client(self.a).get("/tenant").json()
        self.assertEqual((page["name"], page["short_name"], page["logo_url"]), (self.a.name, self.a.name, None))
        self.assertEqual([x["name"] for x in page["assistants"]], [f"{self.a.name} Labs"])
        self.assertEqual([x["key"] for x in page["audiences"]], ["student", "staff"])
        self.assertTrue(all(c.startswith("#") for c in page["colors"].values()))

    def test_refused_settings(self):
        a = self.client(self.a)
        for body in [{"description": "no name and no template"}, {"name": "X", "skills": ["teleport"]},
                     {"name": "X", "audiences": ["alumni"]}, {"name": "X", "answer_mode": "guess"},
                     {"name": "X", "prompt_mode": "magic"},
                     {"name": "X", "skills": ["cv"]},  # only universities with a trained CV model
                     {"template_key": "no_such_template"}]:
            self.assertEqual(a.post("/admin/agents", json=body).status_code, 400, body)

    def test_custom_assistant_without_template(self):
        made = self.client(self.a).post("/admin/agents", json={
            "name": "Library Helper", "description": "Books and opening hours",
            "instructions": "You help with the library.", "audiences": ["student"]})
        self.assertEqual(made.status_code, 200, made.text)
        agent = registry.load_agent(self.a.id, made.json()["id"])
        self.assertEqual((agent.display_name, agent.allowed_user_types, agent.settings.template_key, agent.settings.position,
                          agent.settings.folder), ("Library Helper", ("student",), None, 1, "library_helper"))  # after A's Labs


if __name__ == "__main__":
    unittest.main()
