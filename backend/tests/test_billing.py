"""Tests for the public sign-up and subscriptions (migration 010, app/billing/, the /signup,
/billing and console routes). They use the test database like test_tenants.py (one rolled-back
transaction per test). No email is sent (mail.send is replaced and the code read from it) and
no model is called. Payments use the simulated provider, through the same webhook handling a
real provider's calls would use.

Run from the backend folder:
    python -m unittest discover -s tests -v
"""
import re
import uuid
from unittest import mock

from app import auth, config, usage
from app.billing import providers, service
from app.routers import billing, console, signup
from tests.test_tenants import SharedConnection, TestDatabaseCase, client_for


class SignupAndBilling(TestDatabaseCase):
    def setUp(self):
        super().setUp()
        self.use_app_code()
        shared = SharedConnection(self.conn)
        for module in (service, signup, billing, console, auth):
            patch = mock.patch.object(module, "get_admin_connection", lambda *args, **kwargs: shared())
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(usage, "get_connection", shared)
        patch.start()
        self.addCleanup(patch.stop)
        self.mails = []
        patch = mock.patch.object(signup.mail, "send", lambda to, subject, text: self.mails.append((to, text)))
        patch.start()
        self.addCleanup(patch.stop)
        self.conn.execute("UPDATE platform_settings SET value = 'false' WHERE key = 'require_review'")
        self.web = self.client(self.a)  # the sign-up works on any host
        self.domain = f"uni-{uuid.uuid4().hex[:6]}.edu.eg"
        self.slug = f"su-{uuid.uuid4().hex[:6]}"

    # ---------------------------------------------------------------- helpers

    def code(self) -> str:
        return re.search(r"\b(\d{6})\b", self.mails[-1][1]).group(1)

    def start(self, plan="free", email=None) -> str:
        made = self.web.post("/signup", json={"plan": plan, "person": "Mona Hassan", "email": email or f"m.hassan@{self.domain}",
                                              "password": "a long password 1"})
        self.assertEqual(made.status_code, 200, made.text)
        return made.json()["id"]

    def verified(self, plan="free") -> str:
        signup_id = self.start(plan)
        self.assertEqual(self.web.post(f"/signup/{signup_id}/verify", json={"code": self.code()}).status_code, 200)
        return signup_id

    def draft(self, plan="free", **changes) -> dict:
        return {"plan": plan, "university": "Cairo Tech University", "short_name": "CTU", "slug": self.slug,
                "brand_primary": "#c2410c",
                "assistants": [{"name": "Ask Admissions", "description": "Applying, documents, deadlines and fees"},
                               {"name": "Campus Guide", "template_key": "labs_research"}], **changes}

    def tenant_id(self):
        return self.rows("SELECT id FROM tenants WHERE slug = %s", (self.slug,))[0][0]

    def subscription(self):
        return self.rows("SELECT status, plan_key, grace_ends_at IS NOT NULL, cancel_at_period_end FROM subscriptions "
                         "WHERE tenant_id = %s", (self.tenant_id(),))[0]

    def pay(self, checkout_url: str, outcome: str = "paid"):
        checkout = checkout_url.rsplit("/", 1)[1]
        return self.web.post(f"/billing/simulated/checkouts/{checkout}", json={"outcome": outcome})

    def chat_status(self) -> int:
        """The new university's chat: 429 when billing paused it (no model is called either way)."""
        host = client_for(f"{self.slug}.localhost:8000")
        agent = self.rows("SELECT id FROM agents WHERE tenant_id = %s ORDER BY position LIMIT 1", (self.tenant_id(),))[0][0]
        conversation = self.insert("INSERT INTO conversations (tenant_id, agent_id, user_type) VALUES (%s, %s, 'student') "
                                   "RETURNING id", (self.tenant_id(), agent))
        with mock.patch.object(usage, "check_allowance", side_effect=usage.AllowanceUsedUp("cap check reached")):
            answer = host.post("/chat", json={"conversation_id": conversation, "query": "hello"})
        # 429 "cap check reached": the subscription allowed it; 429 "paused": billing stopped it
        return "paused" if "paused" in answer.json().get("detail", "") else "works"

    def month(self, payment: str):
        result = self.web.post(f"/console/subscriptions/{self.tenant_id()}/simulate-month", json={"payment": payment})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def admin(self):
        """The new university's admin page, logged in with the sign-up's one-time link."""
        link = self.web.get(f"/signup/{self.signup_id}").json()["login_url"]
        ticket = link.split("#ticket=")[1]
        host = client_for(f"{self.slug}.localhost:8000")
        login = host.post("/admin/login/ticket", json={"ticket": ticket})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(host.post("/admin/login/ticket", json={"ticket": ticket}).status_code, 401)  # works once
        host.headers["Authorization"] = f"Bearer {login.json()['token']}"
        return host

    # ---------------------------------------------------------------- tests

    def test_account_rules(self):
        refused = self.web.post("/signup", json={"plan": "free", "person": "M", "email": "mona@gmail.com", "password": "a long password 1"})
        self.assertEqual(refused.status_code, 400)
        self.assertIn("university email", refused.json()["detail"])
        self.assertEqual(self.web.post("/signup", json={"plan": "unlimited", "person": "M", "email": f"m@{self.domain}",
                                                        "password": "a long password 1"}).status_code, 400)  # not public
        self.assertEqual(self.web.post("/signup", json={"plan": "free", "person": "M", "email": f"m@{self.domain}",
                                                        "password": "short"}).status_code, 400)
        signup_id = self.start()
        stored = self.rows("SELECT code_hash, password_hash FROM signups WHERE id = %s", (signup_id,))[0]
        self.assertNotIn(self.code(), stored[0])  # only a hash of the code
        self.assertTrue(stored[1].startswith("scrypt$"))
        self.assertEqual(self.mails[-1][0], f"m.hassan@{self.domain}")

    def test_code_tries_and_expiry(self):
        signup_id = self.start()
        right = self.code()
        wrong = "000000" if right != "000000" else "111111"
        first = self.web.post(f"/signup/{signup_id}/verify", json={"code": wrong})
        self.assertEqual(first.status_code, 400)
        self.assertIn("4 tries left", first.json()["detail"])
        for _ in range(4):
            self.web.post(f"/signup/{signup_id}/verify", json={"code": wrong})
        self.assertIn("Too many", self.web.post(f"/signup/{signup_id}/verify", json={"code": right}).json()["detail"])
        self.conn.execute("UPDATE signups SET code_sent_at = now() - interval '2 minutes' WHERE id = %s", (signup_id,))
        self.assertEqual(self.web.post(f"/signup/{signup_id}/code").status_code, 200)  # a new code: tries start again
        self.assertEqual(self.web.post(f"/signup/{signup_id}/code").status_code, 429)  # not again within a minute
        self.conn.execute("UPDATE signups SET code_expires_at = now() - interval '1 second' WHERE id = %s", (signup_id,))
        self.assertIn("expired", self.web.post(f"/signup/{signup_id}/verify", json={"code": self.code()}).json()["detail"])

    def test_trial_then_paused_then_paid(self):
        self.signup_id = signup_id = self.verified("free")
        self.assertEqual(self.web.post(f"/signup/{signup_id}/subscribe", json=self.draft(slug="admin")).status_code, 409)  # reserved
        too_many = self.draft(assistants=[{"name": n} for n in ("One", "Two", "Three")])
        self.assertIn("allows 2 assistants", self.web.post(f"/signup/{signup_id}/subscribe", json=too_many).json()["detail"])
        made = self.web.post(f"/signup/{signup_id}/subscribe", json=self.draft())
        self.assertEqual(made.json(), {"done": True, "checkout_url": None})
        status = self.web.get(f"/signup/{signup_id}").json()
        self.assertEqual((status["state"], status["url"]), ("done", f"http://{self.slug}.localhost:5173"))
        page = client_for(f"{self.slug}.localhost:8000").get("/tenant").json()
        self.assertEqual(([a["name"] for a in page["assistants"]], page["colors"]["primary"]),
                         (["Ask Admissions", "Campus Guide"], "#c2410c"))
        self.assertEqual(self.subscription()[:2], ("trialing", "free"))
        self.assertEqual(self.rows("SELECT email_domain FROM tenants WHERE slug = %s", (self.slug,))[0][0], self.domain)
        # One university per email domain (so one trial per domain)
        again = self.web.post("/signup", json={"plan": "free", "person": "X", "email": f"other@{self.domain}", "password": "a long password 1"})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(self.chat_status(), "works")
        # A month later the 14-day trial has ended: the chat is paused, nothing is deleted
        self.assertIsNone(self.month("succeeds")["renewal"])
        self.assertEqual(self.subscription()[0], "paused")
        self.assertEqual(self.chat_status(), "paused")
        # The admin chooses Standard and pays: active again
        admin = self.admin()
        self.assertEqual(admin.get("/admin/billing").json()["subscription"]["status"], "paused")
        url = admin.post("/admin/billing/checkout", json={"plan": "standard"}).json()["url"]
        self.assertEqual(self.pay(url).json()["status"], "paid")
        self.assertEqual(self.subscription()[:2], ("active", "standard"))
        self.assertEqual(self.rows("SELECT plan FROM tenants WHERE slug = %s", (self.slug,))[0][0], "standard")
        self.assertEqual(self.chat_status(), "works")
        self.assertEqual(admin.post("/admin/billing/checkout", json={"plan": "free"}).status_code, 400)  # no going back to the trial

    def test_paid_signup_renewals_grace_and_cancel(self):
        self.signup_id = signup_id = self.verified("standard")
        first = self.web.post(f"/signup/{signup_id}/subscribe", json=self.draft("standard")).json()
        self.assertFalse(first["done"])
        self.assertEqual(self.web.get(first["checkout_url"].replace("/checkout/", "/billing/checkouts/")).json()["amount_egp"], 7500)
        self.assertEqual(self.web.get(f"/signup/{signup_id}").json()["state"], "checkout")
        self.assertEqual(self.pay(first["checkout_url"], "failed").json()["status"], "failed")
        self.assertEqual(self.web.get(f"/signup/{signup_id}").json()["state"], "payment_failed")
        self.assertEqual(self.rows("SELECT count(*) FROM tenants WHERE slug = %s", (self.slug,))[0][0], 0)  # not made
        self.assertEqual(self.pay(first["checkout_url"]).status_code, 409)  # a finished payment page
        second = self.web.post(f"/signup/{signup_id}/subscribe", json=self.draft("standard")).json()
        self.assertEqual(self.pay(second["checkout_url"]).json()["status"], "paid")
        self.assertEqual(self.web.get(f"/signup/{signup_id}").json()["state"], "done")
        self.assertEqual(self.subscription(), ("active", "standard", False, False))
        # Renewal paid, then failed: 7 days' grace (still working), then paused
        self.assertEqual(self.month("succeeds")["renewal"], "invoice.paid")
        self.assertEqual(self.subscription()[0], "active")
        self.assertEqual(self.month("fails")["renewal"], "invoice.payment_failed")
        self.assertEqual(self.subscription()[:3], ("past_due", "standard", True))
        self.assertEqual(self.chat_status(), "works")
        self.month("fails")
        self.assertEqual(self.subscription()[0], "paused")
        self.assertEqual(self.chat_status(), "paused")
        # Pay now: active again
        admin = self.admin()
        url = admin.post("/admin/billing/checkout", json={"plan": "standard"}).json()["url"]
        self.pay(url)
        self.assertEqual(self.subscription()[:3], ("active", "standard", False))
        payments = [e for e in admin.get("/admin/billing").json()["subscription"]["events"] if e["amount_egp"]]
        self.assertEqual(len(payments), 3)  # the first month, one renewal, pay now
        # Cancel: works to the end of the paid month, then ends
        self.assertEqual(admin.post("/admin/billing/cancel").status_code, 200)
        self.assertEqual(self.subscription()[3], True)
        self.assertEqual(self.chat_status(), "works")
        self.month("succeeds")
        self.assertEqual(self.subscription()[0], "canceled")
        self.assertEqual(self.chat_status(), "paused")

    def test_webhook_signature_and_repeats(self):
        simulated = providers.get("simulated")
        body, headers = simulated.signed_event("invoice.paid", subscription="sim_sub_unknown")
        self.assertEqual(self.web.post("/billing/webhook/simulated", content=body, headers={"x-simulated-signature": "forged"}).status_code, 400)
        self.assertEqual(self.web.post("/billing/webhook/stripe", content=body, headers=headers).status_code, 404)
        self.signup_id = signup_id = self.verified("standard")
        url = self.web.post(f"/signup/{signup_id}/subscribe", json=self.draft("standard")).json()["checkout_url"]
        self.pay(url)
        ref = self.rows("SELECT provider_subscription_id FROM subscriptions WHERE tenant_id = %s", (self.tenant_id(),))[0][0]
        body, headers = simulated.signed_event("invoice.paid", subscription=ref)
        for _ in range(2):  # the provider may call twice: applied once
            self.assertEqual(self.web.post("/billing/webhook/simulated", content=body, headers=headers).status_code, 200)
        self.assertEqual(self.rows("SELECT count(*) FROM billing_events WHERE tenant_id = %s AND kind = 'invoice.paid'",
                                   (self.tenant_id(),))[0][0], 1)

    def test_review_before_going_live(self):
        self.assertEqual(self.web.put("/console/settings", json={"require_review": True}).status_code, 200)
        self.signup_id = signup_id = self.verified("free")
        self.web.post(f"/signup/{signup_id}/subscribe", json=self.draft())
        status = self.web.get(f"/signup/{signup_id}").json()
        self.assertEqual(status["state"], "review")
        self.assertNotIn("login_url", status)
        closed = client_for(f"{self.slug}.localhost:8000").get("/tenant")
        self.assertEqual(closed.status_code, 403)
        self.assertIn("approved", closed.json()["detail"])
        universities = {u["slug"]: u for u in self.web.get("/console/universities").json()}
        self.assertEqual((universities[self.slug]["status"], universities[self.slug]["subscription"]), ("review", "trialing"))
        self.assertTrue(universities[self.slug]["signed_up_at"])
        self.assertEqual(self.web.put(f"/console/universities/{self.tenant_id()}", json={"status": "active"}).status_code, 200)
        self.assertEqual(client_for(f"{self.slug}.localhost:8000").get("/tenant").status_code, 200)

    def test_console_plans_and_trial_extension(self):
        self.assertEqual(self.web.put("/console/plans/standard", json={"price_egp": 9000}).status_code, 200)
        plans = {p["key"]: p for p in self.web.get("/signup/plans").json()["plans"]}
        self.assertEqual(plans["standard"]["price_egp"], 9000)
        self.assertNotIn("unlimited", plans)  # GIU's plan is not offered publicly
        self.assertEqual(self.web.put("/console/plans/free", json={"price_egp": 100}).status_code, 400)  # a trial is free
        self.assertEqual(self.web.put("/console/plans/gold", json={"price_egp": 1}).status_code, 404)
        self.signup_id = signup_id = self.verified("free")
        self.web.post(f"/signup/{signup_id}/subscribe", json=self.draft())
        self.month("succeeds")
        self.assertEqual(self.subscription()[0], "paused")
        self.assertEqual(self.web.post(f"/console/subscriptions/{self.tenant_id()}/extend-trial", json={"days": 7}).status_code, 200)
        self.assertEqual(self.subscription()[0], "trialing")
        listed = self.web.get("/console/subscriptions").json()
        self.assertEqual(listed["subscriptions"][0]["university"], "Cairo Tech University")
        # Universities added by hand have no subscription and are never paused by billing
        self.assertEqual(self.web.post(f"/console/subscriptions/{self.a.id}/simulate-month", json={"payment": "fails"}).status_code, 404)


if __name__ == "__main__":
    import unittest
    unittest.main()
