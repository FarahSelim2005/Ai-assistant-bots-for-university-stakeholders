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
from app import auth, config, db, main, tenants, usage
import app.agents.base as base
from app.llm import client
from app.agents import directory
from app.agents.templates import GIU_AGENT_IDS, GIU_AGENTS, TEMPLATES
from tests import giu_agents
from app.main import app
from app.rag import retriever
from app.routers import admin, chat, console, documents, feedback, session
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
        with mock.patch.object(tenants, "by_host", HOSTS.get), giu_agents.active():  # GIU's assistants
            auth._sessions["giu-token"] = auth.Session(uuid.uuid4(), "a@giu.example", "", "tenant_admin", GIU.id, 1e12)
            login = {"Authorization": "Bearer giu-token"}
            self.assertEqual(client_for("giu.localhost:8000").get("/admin/documents", headers=login).status_code, 200)
            self.assertEqual(client_for("demo.localhost:8000").get("/admin/documents", headers=login).status_code, 401)
            auth._sessions.pop("giu-token")


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
        tenant_id = self.insert("INSERT INTO tenants (slug, name, plan) VALUES (%s, %s, 'unlimited') RETURNING id",
                                (slug, slug.upper()))
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
        for module in [tenants, retriever, chat, session, feedback, documents, admin, ingest, registry, directory, auth]:
            patch = mock.patch.object(module, "get_connection", shared)
            patch.start()
            self.addCleanup(patch.stop)
        tenants._by_host.clear()
        self.addCleanup(tenants._by_host.clear)

    def client(self, tenant: tenants.Tenant, role: str | None = None) -> TestClient:
        """A client on the tenant's host (the real host lookup in tenant_domains), logged in
        with `role` when given (a session as auth.log_in makes it)."""
        client = client_for(f"{tenant.slug}.test:8000")
        if role:
            token = f"test-{tenant.slug}-{role}"
            auth._sessions[token] = auth.Session(uuid.uuid4(), f"{role}@test.example", "", role, tenant.id, 1e12)
            self.addCleanup(auth._sessions.pop, token, None)
            client.headers["Authorization"] = f"Bearer {token}"
        return client


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

    def test_create_change_and_hide(self):
        a, b = self.client(self.a, "tenant_admin"), self.client(self.b, "tenant_admin")
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
        a = self.client(self.a, "tenant_admin")
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

    def test_new_assistants_skills_like_giu(self):
        a = self.client(self.a, "tenant_admin")
        for body, skills in [({"name": "From scratch"}, ["files", "images", "editor", "voice"]),
                             ({"template_key": "internship_career"}, ["files", "images", "cv", "editor", "voice"]),
                             ({"template_key": "labs_research"}, ["files", "images", "editor", "voice"])]:  # no campus map here
            made = a.post("/admin/agents", json=body).json()["id"]
            agent = next(x for x in a.get("/admin/agents").json() if x["id"] == made)
            self.assertEqual(agent["skills"], skills, body)
        chosen = a.post("/admin/agents", json={"name": "Only files", "skills": ["files"]}).json()["id"]
        self.assertEqual(next(x for x in a.get("/admin/agents").json() if x["id"] == chosen)["skills"], ["files"])

    def test_refused_settings(self):
        a = self.client(self.a, "tenant_admin")
        for body in [{"description": "no name and no template"}, {"name": "X", "skills": ["teleport"]},
                     {"name": "X", "audiences": ["alumni"]}, {"name": "X", "answer_mode": "guess"},
                     {"name": "X", "prompt_mode": "magic"},
                     {"template_key": "no_such_template"}]:
            self.assertEqual(a.post("/admin/agents", json=body).status_code, 400, body)

    def test_custom_assistant_without_template(self):
        made = self.client(self.a, "tenant_admin").post("/admin/agents", json={
            "name": "Library Helper", "description": "Books and opening hours",
            "instructions": "You help with the library.", "audiences": ["student"]})
        self.assertEqual(made.status_code, 200, made.text)
        agent = registry.load_agent(self.a.id, made.json()["id"])
        self.assertEqual((agent.display_name, agent.allowed_user_types, agent.settings.template_key, agent.settings.position,
                          agent.settings.folder), ("Library Helper", ("student",), None, 1, "library_helper"))  # after A's Labs


class UniversityAdmin(TestDatabaseCase):
    """Step 3: logins, users, branding, audiences, deleting and ordering assistants (as giu_app)."""
    role = "giu_app"

    def setUp(self):
        super().setUp()
        self.use_app_code()
        patch = mock.patch.object(admin.time, "sleep", lambda seconds: None)  # no 1 s wait for wrong passwords
        patch.start()
        self.addCleanup(patch.stop)

    def add_user(self, tenant, email, role="tenant_admin", password="a long password 1"):
        db.set_tenant(self.conn, tenant.id)
        self.conn.execute("INSERT INTO users (tenant_id, email, role, password_hash) VALUES (%s, %s, %s, %s)",
                          (tenant.id, email, role, auth.hash_password(password)))

    def test_login_with_email_and_password(self):
        self.add_user(self.a, f"boss@{self.a.slug}.example")
        login = lambda tenant, password: self.client(tenant).post(
            "/admin/login", json={"email": f"Boss@{self.a.slug}.example", "password": password})
        answer = login(self.a, "a long password 1")
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json()["user"]["role"], "tenant_admin")
        token = {"Authorization": f"Bearer {answer.json()['token']}"}
        self.assertEqual(self.client(self.a).get("/admin/me", headers=token).json()["university"]["slug"], self.a.slug)
        self.assertEqual(login(self.a, "wrong password").status_code, 401)
        self.assertEqual(login(self.b, "a long password 1").status_code, 401)   # A's user, on B's host
        self.assertEqual(self.client(self.b).get("/admin/agents", headers=token).status_code, 401)
        self.client(self.a).post("/admin/logout", headers=token)
        self.assertEqual(self.client(self.a).get("/admin/me", headers=token).status_code, 401)

    def test_users_of_a_university(self):
        a = self.client(self.a, "tenant_admin")
        made = a.post("/admin/users", json={"email": f"ed@{self.a.slug}.example", "name": "Ed", "role": "editor",
                                            "password": "another long one"})
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual([u["email"] for u in a.get("/admin/users").json()], [f"ed@{self.a.slug}.example"])
        self.assertEqual(self.client(self.b, "tenant_admin").get("/admin/users").json(), [])  # B sees none of A's
        self.assertEqual(a.post("/admin/users", json={"email": "x@y.z", "role": "editor", "password": "short"}).status_code, 400)
        self.assertEqual(a.post("/admin/users", json={"email": f"ed@{self.a.slug}.example", "role": "editor",
                                                     "password": "another long one"}).status_code, 409)
        # The last active admin cannot be removed or demoted
        self.add_user(self.a, f"only@{self.a.slug}.example")
        only = next(u for u in a.get("/admin/users").json() if u["role"] == "tenant_admin")
        self.assertEqual(a.put(f"/admin/users/{only['id']}", json={"active": False}).status_code, 400)
        self.assertEqual(a.put(f"/admin/users/{only['id']}", json={"role": "editor"}).status_code, 400)
        self.assertEqual(a.put(f"/admin/users/{made.json()['id']}", json={"role": "tenant_admin"}).status_code, 200)
        self.assertEqual(a.put(f"/admin/users/{only['id']}", json={"role": "editor"}).status_code, 200)  # now there is another

    def test_branding_changes_only_the_own_university(self):
        a = self.client(self.a, "tenant_admin")
        body = {"name": "Alpha University", "short_name": "AU", "brand_primary": "#0b6e4f",
                "logo_url": "data:image/png;base64,iVBORw0KGgo=", "intro": "Ask {university} anything.",
                "audiences": [{"key": "student", "title": "Student"}, {"key": "alumni", "title": "Alumni", "text": "Graduates"}]}
        self.assertEqual(a.put("/admin/branding", json=body).status_code, 200)
        page = self.client(self.a).get("/tenant").json()
        self.assertEqual((page["name"], page["short_name"], page["colors"]["primary"], page["intro"]),
                         ("Alpha University", "AU", "#0b6e4f", "Ask AU anything."))
        self.assertEqual([x["key"] for x in page["audiences"]], ["student", "alumni"])
        self.assertEqual(self.client(self.b).get("/tenant").json()["name"], self.b.name)  # B unchanged
        for bad in [{"brand_primary": "red"}, {"logo_url": "javascript:alert(1)"},
                    {"audiences": [{"key": "Bad Key", "title": "X"}]}, {"audiences": [{"key": "a", "title": "A"}] * 2}]:
            self.assertEqual(a.put("/admin/branding", json=bad).status_code, 400, bad)
        # giu_app itself cannot change another university's row, even without a WHERE on the tenant
        db.set_tenant(self.conn, self.a.id)
        self.assertEqual(self.conn.execute("UPDATE tenants SET intro = 'hacked' WHERE id = %s", (self.b.id,)).rowcount, 0)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege), self.conn.transaction():
            self.conn.execute("UPDATE tenants SET status = 'suspended' WHERE id = %s", (self.a.id,))  # not its column

    def test_audiences_are_the_universitys_own(self):
        a = self.client(self.a, "tenant_admin")
        a.put("/admin/branding", json={"audiences": [{"key": "alumni", "title": "Alumni"}, {"key": "student", "title": "Student"}]})
        made = a.post("/admin/agents", json={"name": "Alumni Desk", "audiences": ["alumni"]})
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(a.post("/admin/agents", json={"name": "X", "audiences": ["staff"]}).status_code, 400)  # not A's
        start = lambda user_type: self.client(self.a).post("/session", json={"user_type": user_type, "agent": made.json()["id"]})
        self.assertEqual(start("alumni").status_code, 200)
        self.assertEqual(start("student").status_code, 403)
        self.assertEqual(start("staff").status_code, 400)  # not one of A's audiences
        # New audiences also apply to the assistant's documents
        a.put(f"/admin/agents/{self.a_agent}", json={"audiences": ["alumni"]})
        db.set_tenant(self.conn, self.a.id)
        self.assertEqual(self.rows("SELECT DISTINCT audience FROM chunks WHERE agent_id = %s", (self.a_agent,)), [(["alumni"],)])

    def test_delete_keeps_the_data_and_order(self):
        a = self.client(self.a, "tenant_admin")
        second = a.post("/admin/agents", json={"name": "Second"}).json()["id"]
        self.assertEqual(a.post("/admin/agents/order", json={"ids": [second, str(self.a_agent)]}).status_code, 200)
        self.assertEqual([x["name"] for x in a.get("/admin/agents").json()], ["Second", f"{self.a.name} Labs"])
        self.assertEqual(a.post("/admin/agents/order", json={"ids": [second]}).status_code, 400)  # every id once
        self.assertEqual(a.delete(f"/admin/agents/{self.a_agent}").status_code, 200)
        self.assertEqual([x["name"] for x in a.get("/admin/agents").json()], ["Second"])
        self.assertEqual(self.client(self.a).post("/session", json={"user_type": "student", "agent": str(self.a_agent)}).status_code, 404)
        self.assertEqual(self.client(self.a).post("/chat", json={"conversation_id": self.a_conversation, "query": "hi"}).status_code, 410)
        db.set_tenant(self.conn, self.a.id)  # nothing is lost: the row, its chunks and its chats are kept
        self.assertEqual(self.rows("SELECT deleted_at IS NOT NULL FROM agents WHERE id = %s", (self.a_agent,)), [(True,)])
        self.assertEqual(self.rows("SELECT count(*) FROM chunks WHERE agent_id = %s", (self.a_agent,)), [(1,)])
        self.assertEqual(self.rows("SELECT count(*) FROM conversations WHERE agent_id = %s", (self.a_agent,)), [(1,)])


class PlansAndUsage(TestDatabaseCase):
    """Step 4: every model call is logged per university; plans cap tokens and assistants (as giu_app)."""
    role = "giu_app"

    def setUp(self):
        super().setUp()
        self.use_app_code()
        patch = mock.patch.object(usage, "get_connection", SharedConnection(self.conn))
        patch.start()
        self.addCleanup(patch.stop)

    def set_plan(self, tenant, plan):
        self.conn.execute("RESET ROLE")  # the owner changes plans (giu_app may not)
        self.conn.execute("UPDATE tenants SET plan = %s WHERE id = %s", (plan, tenant.id))
        self.conn.execute("SET LOCAL ROLE giu_app")

    def test_model_calls_are_logged_per_university(self):
        answer = mock.Mock(**{"json.return_value": {"choices": [{"message": {"content": "Hello"}}],
                                                    "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100,
                                                              "cost": 0.0012}}})
        with tenants.using(self.a), mock.patch.object(client._openrouter, "post", return_value=answer), \
             mock.patch.object(config, "OPENROUTER_API_KEY", "test-key"):
            usage.for_agent(self.a_agent)
            self.assertEqual(client.chat([{"role": "user", "content": "hi"}], "provider/model"), "Hello")
            usage.for_agent(None)
        db.set_tenant(self.conn, self.a.id)
        self.assertEqual(self.rows("SELECT agent_id, model, kind, prompt_tokens, completion_tokens, total_tokens, "
                                   "cost_usd::float FROM usage"), [(self.a_agent, "provider/model", "chat", 90, 10, 100, 0.0012)])
        db.set_tenant(self.conn, self.b.id)
        self.assertEqual(self.rows("SELECT count(*) FROM usage"), [(0,)])  # B sees none of A's usage

    def test_monthly_cap(self):
        self.set_plan(self.a, "free")  # 300,000 tokens a month
        db.set_tenant(self.conn, self.a.id)
        self.conn.execute("INSERT INTO usage (tenant_id, model, kind, total_tokens) VALUES (%s, 'm', 'chat', 299999)", (self.a.id,))
        a = tenants.Tenant(self.a.id, self.a.slug, self.a.name)
        with tenants.using(a):
            usage.check_allowance()  # 1 token left: still allowed
            usage.record("m", "chat", total_tokens=1)
            with self.assertRaises(usage.AllowanceUsedUp):
                usage.check_allowance()
        # The chat route says so (429), before any model call
        db.set_tenant(self.conn, None)
        with mock.patch.object(base, "retrieve_best", side_effect=AssertionError("no search after the cap")):
            answer = self.client(self.a).post("/chat", json={"conversation_id": self.a_conversation, "query": "hello"})
        self.assertEqual(answer.status_code, 429)
        self.assertIn("allowance", answer.json()["detail"])
        with tenants.using(self.b):
            usage.check_allowance()  # B (unlimited) is not affected

    def test_plan_limits_assistants(self):
        self.set_plan(self.a, "free")  # 2 assistants; A has 1
        a = self.client(self.a, "tenant_admin")
        self.assertEqual(a.post("/admin/agents", json={"name": "Second"}).status_code, 200)
        third = a.post("/admin/agents", json={"name": "Third"})
        self.assertEqual(third.status_code, 403)
        self.assertIn("allows 2 assistants", third.json()["detail"])
        a.delete(f"/admin/agents/{self.a_agent}")  # deleted ones do not count
        self.assertEqual(a.post("/admin/agents", json={"name": "Third"}).status_code, 200)


class PlatformConsole(TestDatabaseCase):
    """Step 4: the console, as the platform owner (owner connection, like the real routes)."""

    def setUp(self):
        super().setUp()
        self.use_app_code()
        shared = SharedConnection(self.conn)
        for module in (console, auth):
            patch = mock.patch.object(module, "get_admin_connection", lambda *args, **kwargs: shared())
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(console.time, "sleep", lambda seconds: None)
        patch.start()
        self.addCleanup(patch.stop)
        self.owner_email = f"owner-{uuid.uuid4().hex[:6]}@platform.example"
        self.conn.execute("INSERT INTO users (tenant_id, email, role, password_hash) VALUES (NULL, %s, 'platform_owner', %s)",
                          (self.owner_email, auth.hash_password("the owner's password")))

    def console(self) -> TestClient:
        token = self.client(self.a).post("/console/login", json={"email": self.owner_email,
                                                                 "password": "the owner's password"}).json()["token"]
        client = self.client(self.a)
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    def test_login_and_universities(self):
        self.assertEqual(self.client(self.a).post("/console/login", json={"email": self.owner_email, "password": "wrong"}).status_code, 401)
        with mock.patch.object(config, "APP_ENV", "production"):  # on a server: a platform owner's login only
            self.assertEqual(self.client(self.a, "tenant_admin").get("/console/universities").status_code, 401)
            self.assertEqual(self.client(self.a).get("/console/universities").status_code, 401)
        with mock.patch.object(config, "APP_ENV", "development"):  # on your own computer: no login needed
            self.assertEqual(self.client(self.a).get("/console/universities").status_code, 200)
        universities = {u["slug"]: u for u in self.console().get("/console/universities").json()}
        self.assertEqual((universities[self.a.slug]["assistants"], universities[self.a.slug]["conversations"],
                          universities[self.a.slug]["hosts"], universities[self.a.slug]["plan"]),
                         (1, 1, [f"{self.a.slug}.test"], "unlimited"))
        self.assertIn("giu", universities)
        # A platform owner cannot log in to a university's admin page
        self.assertEqual(self.client(self.a).post("/admin/login", json={"email": self.owner_email,
                                                                       "password": "the owner's password"}).status_code, 401)

    def test_new_university_wizard(self):
        slug = f"new-{uuid.uuid4().hex[:6]}"
        body = {"name": "New University", "short_name": "NU", "slug": slug, "host": f"{slug}.test",
                "brand_primary": "#123456", "plan": "standard",
                "assistants": [{"name": "Ask Admissions", "description": "Applying, deadlines and fees"},
                               {"name": "Campus Guide", "template_key": "labs_research"},
                               {"name": "Ask Admissions", "description": "A second one with the same name"}],
                "templates": ["internship_career"],
                "admin": {"email": f"admin@{slug}.example", "name": "First Admin", "password": "first admin password"}}
        console_client = self.console()
        made = console_client.post("/console/universities", json=body)
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(made.json()["url"], f"http://{slug}.test:5173")
        page = client_for(f"{slug}.test:8000").get("/tenant").json()
        self.assertEqual((page["name"], page["short_name"], page["colors"]["primary"]), ("New University", "NU", "#123456"))
        self.assertEqual([a["name"] for a in page["assistants"]],
                         ["Ask Admissions", "Campus Guide", "Ask Admissions", "Internship & Career Assistant"])
        self.assertEqual(page["assistants"][0]["summary"], "Applying, deadlines and fees")
        self.assertEqual(page["assistants"][1]["summary"], next(t for t in TEMPLATES if t["key"] == "labs_research")["summary"])
        # Ready-made ones do what they do at GIU (CV rewrites for Internship & Career; no campus map
        # here), new ones the usual skills
        self.assertEqual([a["skills"] for a in page["assistants"]],
                         [["files", "images", "editor", "voice"]] * 3 + [["files", "images", "cv", "editor", "voice"]])
        self.assertNotIn("GIU", str(page))
        login = client_for(f"{slug}.test:8000").post("/admin/login", json={"email": f"admin@{slug}.example",
                                                                            "password": "first admin password"})
        self.assertEqual(login.json()["user"]["role"], "tenant_admin")
        admin_client = client_for(f"{slug}.test:8000")
        admin_client.headers["Authorization"] = f"Bearer {login.json()['token']}"
        folders = [a["folder"] for a in admin_client.get("/admin/agents").json()]
        self.assertEqual(folders, ["ask_admissions", "labs_research", "ask_admissions_2", "internship_career"])
        # Refused: taken subdomain, too many assistants for the plan, a bad colour
        self.assertEqual(console_client.post("/console/universities", json={**body, "host": None}).status_code, 409)
        self.assertEqual(console_client.post("/console/universities", json={
            **body, "slug": slug + "x", "host": None, "plan": "free",
            "assistants": [{"name": "One"}, {"name": "Two"}, {"name": "Three"}], "templates": [],
            "admin": {**body["admin"], "email": f"other@{slug}.example"}}).status_code, 400)
        self.assertEqual(console_client.post("/console/universities", json={**body, "slug": slug + "y", "host": None,
                                                                          "brand_primary": "red"}).status_code, 400)

    def test_suspend_and_reactivate(self):
        console_client = self.console()
        self.assertEqual(console_client.put(f"/console/universities/{self.b.id}", json={"status": "suspended"}).status_code, 200)
        self.assertEqual(self.client(self.b).get("/tenant").status_code, 403)
        self.assertEqual(self.client(self.a).get("/tenant").status_code, 200)  # the others are not affected
        self.assertEqual(console_client.put(f"/console/universities/{self.b.id}", json={"status": "active", "plan": "free"}).status_code, 200)
        self.assertEqual(self.client(self.b).get("/tenant").status_code, 200)
        self.assertEqual(console_client.put(f"/console/universities/{self.b.id}", json={"plan": "gold"}).status_code, 400)


class AdminAnalytics(TestDatabaseCase):
    """The admin's numbers (30 days) and changing one's own password (as giu_app)."""
    role = "giu_app"

    def setUp(self):
        super().setUp()
        self.use_app_code()

    def test_questions_unanswered_and_ratings(self):
        a = self.client(self.a, "tenant_admin")
        fallback = "Sorry, I don't have information about that."
        db.set_tenant(self.conn, self.a.id)
        self.conn.execute("UPDATE agents SET fallback_en = %s WHERE id = %s", (fallback, self.a_agent))
        for question, answer, rating in [("Where is the lab?", "In room Z901.", 5), ("What is the meaning of life?", fallback, None),
                                         ("Opening hours?", "9 to 5.", 3)]:
            self.insert("INSERT INTO messages (tenant_id, conversation_id, role, content) VALUES (%s, %s, 'user', %s) RETURNING id",
                        (self.a.id, self.a_conversation, question))
            answer_id = self.insert("INSERT INTO messages (tenant_id, conversation_id, role, content) "
                                    "VALUES (%s, %s, 'assistant', %s) RETURNING id", (self.a.id, self.a_conversation, answer))
            if rating:
                self.conn.execute("INSERT INTO feedback (tenant_id, message_id, rating) VALUES (%s, %s, %s)",
                                  (self.a.id, answer_id, rating))
        numbers = a.get("/admin/analytics").json()
        self.assertEqual((numbers["questions_30d"], numbers["unanswered_30d"], numbers["unanswered_pct"],
                          numbers["average_rating"], numbers["chats_30d"]), (3, 1, 33.3, 4.0, 1))
        self.assertEqual(numbers["recent_unanswered"][0]["question"], "What is the meaning of life?")
        self.assertEqual(numbers["per_assistant"][0]["questions"], 3)
        self.assertEqual(self.client(self.b, "tenant_admin").get("/admin/analytics").json()["questions_30d"], 0)  # only A's

    def test_change_own_password(self):
        db.set_tenant(self.conn, self.a.id)
        user_id = self.insert("INSERT INTO users (tenant_id, email, role, password_hash) VALUES (%s, %s, 'editor', %s) RETURNING id",
                              (self.a.id, f"ed@{self.a.slug}.example", auth.hash_password("old password 123")))
        token = "editor-own-password"
        auth._sessions[token] = auth.Session(user_id, f"ed@{self.a.slug}.example", "", "editor", self.a.id, 1e12)
        self.addCleanup(auth._sessions.pop, token, None)
        editor = self.client(self.a)
        editor.headers["Authorization"] = f"Bearer {token}"
        self.assertEqual(editor.post("/admin/me/password", json={"current_password": "wrong", "new_password": "new password 456"}).status_code, 400)
        self.assertEqual(editor.post("/admin/me/password", json={"current_password": "old password 123", "new_password": "short"}).status_code, 400)
        self.assertEqual(editor.post("/admin/me/password", json={"current_password": "old password 123",
                                                                  "new_password": "new password 456"}).status_code, 200)
        login = self.client(self.a).post("/admin/login", json={"email": f"ed@{self.a.slug}.example", "password": "new password 456"})
        self.assertEqual(login.status_code, 200)


if __name__ == "__main__":
    unittest.main()
