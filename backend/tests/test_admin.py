"""Tests for the admin routes (app/routers/admin.py). No database or embedding service is
used: the documents folder is a temporary one, indexing is replaced by a stand-in, and GIU's
four assistants come from tests/giu_agents.py. Documents are in folders by assistant id;
requests may still name GIU's assistants by their old key ("labs_research").

Run from the backend folder:
    python -m unittest discover -s tests -v
"""
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import auth, config, tenants
from app.main import app
from app.routers import admin
from tests import giu_agents

# Every request is GIU's (the TestClient's host "testserver" is in no tenant_domains table).
GIU = giu_agents.GIU
LABS, HR, ADVISING = giu_agents.ID["labs_research"], giu_agents.ID["hr_policies"], giu_agents.ID["graduation_advising"]
# Their document folders (readable, since migration 006)
LABS_DIR, HR_DIR, ADVISING_DIR = "labs_research", "hr_policies", "graduation_advising"


class AdminRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name) / "raw"
        (self.raw / LABS_DIR).mkdir(parents=True)
        (self.raw / LABS_DIR / "campus.md").write_text("## Library\nFourth floor of S.", encoding="utf-8")
        self.indexed, self.deleted = [], []
        fake_ingest = lambda path, agent, audience: self.indexed.append((agent, path.name, audience)) or 3
        self.patches = [
            mock.patch.object(config, "RAW_DATA_DIR", self.raw),
            mock.patch.object(tenants, "resolve", lambda host, tenant_header: GIU),
            mock.patch.object(admin, "ingest_file", fake_ingest),
            mock.patch.object(admin, "delete_chunks", lambda agent, name: self.deleted.append((agent, name))),
            mock.patch.object(admin.time, "sleep", lambda seconds: None),  # no 1 s wait for wrong passwords
        ]
        for p in self.patches:
            p.start()
        giu_agents.activate(self)
        auth._sessions.clear()
        self.client = TestClient(app)
        self.auth = self.login("tenant_admin")

    def login(self, role: str, tenant_id=None, expiry: float | None = None) -> dict:
        """A session as auth.log_in makes it (the users table is tested in test_tenants.py)."""
        token = f"token-{role}-{len(auth._sessions)}"
        auth._sessions[token] = auth.Session(uuid.uuid4(), f"{role}@giu.example", "", role, tenant_id or GIU.id,
                                             expiry or time.time() + 3600)
        return {"Authorization": f"Bearer {token}"}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_login(self):
        with mock.patch.object(auth, "log_in", return_value=None):
            self.assertEqual(self.client.post("/admin/login", json={"email": "a@b.c", "password": "wrong"}).status_code, 401)
        self.assertEqual(self.client.get("/admin/documents").status_code, 401)  # no login, no access (no open mode)
        self.assertEqual(self.client.get("/admin/documents", headers={"Authorization": "Bearer made-up"}).status_code, 401)
        self.assertEqual(self.client.get("/admin/documents", headers=self.auth).status_code, 200)

    def test_expired_token(self):
        self.assertEqual(self.client.get("/admin/documents", headers=self.login("tenant_admin", expiry=1)).status_code, 401)

    def test_another_universitys_login_is_refused(self):
        self.assertEqual(self.client.get("/admin/documents", headers=self.login("tenant_admin", uuid.uuid4())).status_code, 401)
        self.assertEqual(self.client.get("/admin/documents", headers=self.login("platform_owner")).status_code, 401)

    def test_editors_manage_documents_only(self):
        editor = self.login("editor")
        self.assertEqual(self.client.get("/admin/documents", headers=editor).status_code, 200)
        self.assertEqual(self.client.get("/admin/agents", headers=editor).status_code, 200)
        body = {"agent": "hr_policies", "filename": "x.md", "content": "## X\ny"}
        self.assertEqual(self.client.post("/admin/documents", headers=editor, json=body).status_code, 200)
        for method, path in [("post", "/admin/agents"), ("put", f"/admin/agents/{LABS}"), ("delete", f"/admin/agents/{LABS}"),
                             ("get", "/admin/branding"), ("put", "/admin/branding"), ("get", "/admin/users"),
                             ("post", "/admin/users")]:
            answer = getattr(self.client, method)(path, headers=editor, **({"json": {}} if method in ("post", "put") else {}))
            self.assertEqual(answer.status_code, 403, (method, path))

    def test_list_and_get(self):
        documents = self.client.get("/admin/documents", headers=self.auth).json()
        self.assertEqual([(d["agent"], d["folder"], d["filename"]) for d in documents], [(LABS, LABS_DIR, "campus.md")])
        self.assertTrue(documents[0]["updated_at"])
        document = self.client.get(f"/admin/documents/{documents[0]['id']}", headers=self.auth).json()
        self.assertEqual(document["content"], "## Library\nFourth floor of S.")

    def test_create_indexes_and_refuses_duplicates(self):
        body = {"agent": "hr_policies", "filename": "leave rules", "content": "## Annual leave\n21 days."}
        answer = self.client.post("/admin/documents", headers=self.auth, json=body).json()
        self.assertEqual(answer["chunks"], 3)
        self.assertEqual((self.raw / HR_DIR / "leave rules.md").read_text(encoding="utf-8"), body["content"])
        self.assertEqual(self.indexed, [(HR, "leave rules.md", ["staff"])])  # HR: staff only
        self.assertEqual(self.client.post("/admin/documents", headers=self.auth, json=body).status_code, 409)

    def test_update_moves_to_another_agent(self):
        doc_id = self.client.get("/admin/documents", headers=self.auth).json()[0]["id"]
        body = {"agent": "graduation_advising", "filename": "campus.md", "content": "## Library\nFifth floor of S."}
        answer = self.client.put(f"/admin/documents/{doc_id}", headers=self.auth, json=body).json()
        self.assertFalse((self.raw / LABS_DIR / "campus.md").exists())
        self.assertEqual((self.raw / ADVISING_DIR / "campus.md").read_text(encoding="utf-8"), body["content"])
        self.assertIn((LABS, "campus.md"), self.deleted)  # the old chunks are removed
        self.assertNotEqual(answer["id"], doc_id)

    def test_delete(self):
        doc_id = self.client.get("/admin/documents", headers=self.auth).json()[0]["id"]
        self.assertEqual(self.client.delete(f"/admin/documents/{doc_id}", headers=self.auth).status_code, 200)
        self.assertFalse((self.raw / LABS_DIR / "campus.md").exists())
        self.assertEqual(self.client.get(f"/admin/documents/{doc_id}", headers=self.auth).status_code, 404)

    def test_bad_input_is_refused(self):
        for filename in ["../../.env", "sub/x.md", "..\\x.md", ".hidden"]:
            body = {"agent": "labs_research", "filename": filename, "content": "x"}
            self.assertEqual(self.client.post("/admin/documents", headers=self.auth, json=body).status_code, 400, filename)
        body = {"agent": "orientation", "filename": "a.md", "content": "x"}
        self.assertEqual(self.client.post("/admin/documents", headers=self.auth, json=body).status_code, 400)
        body = {"agent": "labs_research", "filename": "a.md", "content": ""}
        self.assertEqual(self.client.post("/admin/documents", headers=self.auth, json=body).status_code, 422)
        bad_id = admin.document_id(LABS, "../../.env")
        for doc_id in [bad_id, "not-base64!", admin.document_id(LABS, "missing.md"),
                       admin.document_id("labs_research", "campus.md")]:  # documents are found by assistant id
            self.assertEqual(self.client.get(f"/admin/documents/{doc_id}", headers=self.auth).status_code, 404)


if __name__ == "__main__":
    unittest.main()
