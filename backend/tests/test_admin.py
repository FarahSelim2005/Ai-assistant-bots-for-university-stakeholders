"""Tests for the admin routes (app/routers/admin.py). No database or embedding service is
used: the documents folder is a temporary one and indexing is replaced by a stand-in.

Run from the backend folder:
    python -m unittest discover -s tests -v
"""
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import config, tenants
from app.main import app
from app.routers import admin

# Every request is GIU's (the TestClient's host "testserver" is in no tenant_domains table).
GIU = tenants.Tenant(uuid.UUID(int=1), "giu", "German International University")


class AdminRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name) / "raw"
        (self.raw / "labs_research").mkdir(parents=True)
        (self.raw / "labs_research" / "campus.md").write_text("## Library\nFourth floor of S.", encoding="utf-8")
        self.indexed, self.deleted = [], []
        fake_ingest = lambda path, agent, audience: self.indexed.append((agent, path.name, audience)) or 3
        self.patches = [
            mock.patch.object(config, "RAW_DATA_DIR", self.raw),
            mock.patch.object(tenants, "resolve", lambda host, tenant_header: GIU),
            mock.patch.object(config, "ADMIN_PASSWORD", "secret"),
            mock.patch.object(admin, "ingest_file", fake_ingest),
            mock.patch.object(admin, "delete_chunks", lambda agent, name: self.deleted.append((agent, name))),
            mock.patch.object(admin.time, "sleep", lambda seconds: None),  # no 1 s wait for wrong passwords
        ]
        for p in self.patches:
            p.start()
        admin._tokens.clear()
        self.client = TestClient(app)
        self.auth = {"Authorization": "Bearer " + self.client.post("/admin/login", json={"password": "secret"}).json()["token"]}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_login(self):
        self.assertEqual(self.client.post("/admin/login", json={"password": "wrong"}).status_code, 401)
        self.assertEqual(self.client.get("/admin/documents").status_code, 401)
        self.assertEqual(self.client.get("/admin/documents", headers={"Authorization": "Bearer made-up"}).status_code, 401)
        self.assertEqual(self.client.get("/admin/documents", headers=self.auth).status_code, 200)

    def test_expired_token(self):
        token = self.auth["Authorization"].split()[1]
        admin._tokens[token] = 0
        self.assertEqual(self.client.get("/admin/documents", headers=self.auth).status_code, 401)

    def test_open_without_password(self):
        with mock.patch.object(config, "ADMIN_PASSWORD", ""):
            self.assertEqual(self.client.get("/admin/documents").status_code, 200)
            self.assertEqual(self.client.post("/admin/login", json={"password": "x"}).status_code, 503)

    def test_list_and_get(self):
        documents = self.client.get("/admin/documents", headers=self.auth).json()
        self.assertEqual([(d["agent"], d["filename"]) for d in documents], [("labs_research", "campus.md")])
        self.assertTrue(documents[0]["updated_at"])
        document = self.client.get(f"/admin/documents/{documents[0]['id']}", headers=self.auth).json()
        self.assertEqual(document["content"], "## Library\nFourth floor of S.")

    def test_create_indexes_and_refuses_duplicates(self):
        body = {"agent": "hr_policies", "filename": "leave rules", "content": "## Annual leave\n21 days."}
        answer = self.client.post("/admin/documents", headers=self.auth, json=body).json()
        self.assertEqual(answer["chunks"], 3)
        self.assertEqual((self.raw / "hr_policies" / "leave rules.md").read_text(encoding="utf-8"), body["content"])
        self.assertEqual(self.indexed, [("hr_policies", "leave rules.md", ["staff"])])  # HR: staff only
        self.assertEqual(self.client.post("/admin/documents", headers=self.auth, json=body).status_code, 409)

    def test_update_moves_to_another_agent(self):
        doc_id = self.client.get("/admin/documents", headers=self.auth).json()[0]["id"]
        body = {"agent": "graduation_advising", "filename": "campus.md", "content": "## Library\nFifth floor of S."}
        answer = self.client.put(f"/admin/documents/{doc_id}", headers=self.auth, json=body).json()
        self.assertFalse((self.raw / "labs_research" / "campus.md").exists())
        self.assertEqual((self.raw / "graduation_advising" / "campus.md").read_text(encoding="utf-8"), body["content"])
        self.assertIn(("labs_research", "campus.md"), self.deleted)  # the old chunks are removed
        self.assertNotEqual(answer["id"], doc_id)

    def test_delete(self):
        doc_id = self.client.get("/admin/documents", headers=self.auth).json()[0]["id"]
        self.assertEqual(self.client.delete(f"/admin/documents/{doc_id}", headers=self.auth).status_code, 200)
        self.assertFalse((self.raw / "labs_research" / "campus.md").exists())
        self.assertEqual(self.client.get(f"/admin/documents/{doc_id}", headers=self.auth).status_code, 404)

    def test_bad_input_is_refused(self):
        for filename in ["../../.env", "sub/x.md", "..\\x.md", ".hidden"]:
            body = {"agent": "labs_research", "filename": filename, "content": "x"}
            self.assertEqual(self.client.post("/admin/documents", headers=self.auth, json=body).status_code, 400, filename)
        body = {"agent": "orientation", "filename": "a.md", "content": "x"}
        self.assertEqual(self.client.post("/admin/documents", headers=self.auth, json=body).status_code, 400)
        body = {"agent": "labs_research", "filename": "a.md", "content": ""}
        self.assertEqual(self.client.post("/admin/documents", headers=self.auth, json=body).status_code, 422)
        bad_id = admin.document_id("labs_research", "../../.env")
        for doc_id in [bad_id, "not-base64!", admin.document_id("labs_research", "missing.md")]:
            self.assertEqual(self.client.get(f"/admin/documents/{doc_id}", headers=self.auth).status_code, 404)


if __name__ == "__main__":
    unittest.main()
