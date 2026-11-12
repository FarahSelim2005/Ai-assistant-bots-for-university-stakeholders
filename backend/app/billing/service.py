"""Subscriptions of the universities that signed up themselves (migration 010).

A subscription's status:
    trialing   the free trial; after trial_ends_at it is paused until a paid plan is chosen
    active     paid; renewed every month by the provider (invoice.paid)
    past_due   a renewal failed: the chat keeps working for GRACE_DAYS, then it is paused
    paused     the chat answers "paused" (nothing is deleted); paying makes it active again
    canceled   cancelled by the university; it ends at the end of the paid month

The stored status is brought up to date ("settled") when time has passed a date, by
EFFECTIVE_STATUS: the chat check reads it in SQL, so a trial ends on time even if nothing
has settled it yet. Universities without a subscription (added by hand: GIU, demo) are never
paused by billing.

Payments: open_checkout() makes a checkouts row and asks the provider for its payment page;
the provider's webhook events (receive_webhook) record the outcome. Every event is stored in
billing_events once (its id is unique), so a repeated webhook call changes nothing.
"""
import logging
import uuid

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from app import config, tenants, universities
from app.billing import providers
from app.billing.providers import Checkout, Event
from app.db import get_admin_connection

log = logging.getLogger("uvicorn.error")

# The status with the dates applied (s = the subscriptions row)
EFFECTIVE_STATUS = """CASE
    WHEN s.status = 'trialing' AND s.trial_ends_at <= now() THEN 'paused'
    WHEN s.status IN ('active', 'past_due') AND s.cancel_at_period_end AND s.current_period_end <= now() THEN 'canceled'
    WHEN s.status = 'past_due' AND s.grace_ends_at <= now() THEN 'paused'
    ELSE s.status END"""
CHAT_STOPPED = ("paused", "canceled")
GRACE = f"interval '{config.GRACE_DAYS} days'"


def provider() -> providers.PaymentProvider:
    return providers.get(config.PAYMENT_PROVIDER)


def require_review(conn) -> bool:
    row = conn.execute("SELECT value FROM platform_settings WHERE key = 'require_review'").fetchone()
    return bool(row and row[0] is True)


# ---------------------------------------------------------------- plans

PLAN_COLUMNS = "key, name, price_egp, trial_days, monthly_token_cap, max_assistants, public, description"


def plan_out(row) -> dict:
    key, name, price, trial_days, cap, most, public, description = row
    return {"key": key, "name": name, "price_egp": price, "trial_days": trial_days, "monthly_token_cap": cap,
            "max_assistants": most, "public": public, "description": description}


def plans(conn, public_only: bool = False) -> list[dict]:
    rows = conn.execute(f"SELECT {PLAN_COLUMNS} FROM plans {'WHERE public' if public_only else ''} ORDER BY position").fetchall()
    return [plan_out(r) for r in rows]


def plan(conn, key: str) -> dict | None:
    row = conn.execute(f"SELECT {PLAN_COLUMNS} FROM plans WHERE key = %s", (key,)).fetchone()
    return plan_out(row) if row else None


# ---------------------------------------------------------------- reading a subscription

def settle(conn, tenant_id: uuid.UUID | None = None) -> None:
    """Store the effective status of one subscription (or all), with an event for the history
    when a subscription is paused or ends."""
    rows = conn.execute(f"""
        UPDATE subscriptions s SET status = {EFFECTIVE_STATUS}, updated_at = now()
        WHERE s.status <> {EFFECTIVE_STATUS} {'AND s.tenant_id = %s' if tenant_id else ''}
        RETURNING s.tenant_id, s.status, s.plan_key""", (tenant_id,) if tenant_id else ()).fetchall()
    for tenant, status, plan_key in rows:
        conn.execute("INSERT INTO billing_events (id, tenant_id, kind, plan_key) VALUES (%s, %s, %s, %s)",
                     (f"local_{uuid.uuid4().hex}", tenant, f"subscription.{status}", plan_key))


def subscription(conn, tenant_id) -> dict | None:
    """The university's subscription with its plan and payments, or None (added by hand)."""
    settle(conn, tenant_id)
    row = conn.execute(f"""
        SELECT s.plan_key, p.name, p.price_egp, s.status, s.trial_ends_at, s.current_period_end, s.grace_ends_at,
               s.cancel_at_period_end, s.provider, s.created_at
        FROM subscriptions s JOIN plans p ON p.key = s.plan_key WHERE s.tenant_id = %s""", (tenant_id,)).fetchone()
    if row is None:
        return None
    events = conn.execute("SELECT kind, plan_key, amount_egp, created_at FROM billing_events WHERE tenant_id = %s "
                          "ORDER BY created_at DESC LIMIT 50", (tenant_id,)).fetchall()
    when = lambda value: value.isoformat() if value else None
    return {"plan": row[0], "plan_name": row[1], "price_egp": row[2], "status": row[3], "trial_ends_at": when(row[4]),
            "current_period_end": when(row[5]), "grace_ends_at": when(row[6]), "cancel_at_period_end": row[7],
            "provider": row[8], "created_at": when(row[9]),
            "events": [{"kind": k, "plan": p, "amount_egp": a, "at": when(t)} for k, p, a, t in events]}


# ---------------------------------------------------------------- checkouts

def open_checkout(conn, purpose: str, plan_key: str, *, signup_id=None, tenant_id=None, university: str = "") -> str:
    """A payment page for this plan's monthly price; returns its URL."""
    chosen = plan(conn, plan_key)
    checkout_id = conn.execute(
        "INSERT INTO checkouts (purpose, signup_id, tenant_id, plan_key, amount_egp, provider) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (purpose, signup_id, tenant_id, plan_key, chosen["price_egp"], provider().name)).fetchone()[0]
    return provider().create_checkout(Checkout(checkout_id, plan_key, chosen["name"], chosen["price_egp"], purpose, university))


def checkout_out(checkout_id: str) -> dict:
    """What the payment page shows: plan, price, university, and where to go afterwards."""
    with get_admin_connection() as conn:
        row = conn.execute("""
            SELECT c.id, c.purpose, c.plan_key, p.name, c.amount_egp, c.status, c.provider, c.signup_id,
                   coalesce(t.name, sg.draft->>'university'), coalesce(t.slug, sg.draft->>'slug')
            FROM checkouts c JOIN plans p ON p.key = c.plan_key
            LEFT JOIN tenants t ON t.id = c.tenant_id LEFT JOIN signups sg ON sg.id = c.signup_id
            WHERE c.id = %s""", (checkout_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "This payment page does not exist.")
    return {"id": str(row[0]), "purpose": row[1], "plan": row[2], "plan_name": row[3], "amount_egp": row[4],
            "status": row[5], "provider": row[6], "university": row[8], "slug": row[9],
            "test_mode": row[6] == "simulated",
            "return_url": f"/signup?id={row[7]}" if row[1] == "signup" else "/admin?billing=1"}


def simulate_checkout(checkout_id: str, paid: bool) -> dict:
    """The test-mode page's "Pay" or "Fail payment": the simulated provider sends the event
    to our webhook handling, exactly as a real provider's call would arrive."""
    simulated = providers.get("simulated")
    with get_admin_connection() as conn:
        row = conn.execute("SELECT provider, status FROM checkouts WHERE id = %s", (checkout_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "This payment page does not exist.")
    if row[0] != "simulated":
        raise HTTPException(400, "This is not a test-mode payment.")
    if row[1] != "open":
        raise HTTPException(409, "This payment is already finished.")
    body, headers = simulated.signed_event("checkout.paid" if paid else "checkout.failed", checkout=str(checkout_id),
                                           subscription=f"sim_sub_{uuid.UUID(str(checkout_id)).hex}" if paid else None)
    receive_webhook("simulated", body, headers)
    return checkout_out(checkout_id)


# ---------------------------------------------------------------- webhook events

def receive_webhook(provider_name: str, body: bytes, headers) -> Event:
    """A provider's webhook call: checked by the provider, then applied once."""
    event = providers.get(provider_name).verify_webhook(body, headers)
    with get_admin_connection() as conn:
        apply_event(conn, event)
    tenants._by_host.clear()  # a new or changed university is seen at once
    return event


def apply_event(conn, event: Event) -> None:
    if conn.execute("INSERT INTO billing_events (id, kind, data) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING "
                    "RETURNING id", (event.id, event.kind, Jsonb(event.data))).fetchone() is None:
        log.info("Billing: event %s was already applied", event.id)
        return
    data = event.data
    tenant_id, plan_key, amount = None, None, None
    if event.kind in ("checkout.paid", "checkout.failed"):
        checkout = conn.execute("SELECT purpose, signup_id, tenant_id, plan_key, amount_egp, status FROM checkouts "
                                "WHERE id = %s FOR UPDATE", (data.get("checkout"),)).fetchone()
        if checkout is None or checkout[5] != "open":
            log.warning("Billing: %s for an unknown or finished checkout", event.kind)
            return
        purpose, signup_id, tenant_id, plan_key, price, _ = checkout
        paid = event.kind == "checkout.paid"
        conn.execute("UPDATE checkouts SET status = %s, finished_at = now() WHERE id = %s",
                     ("paid" if paid else "failed", data["checkout"]))
        if paid:
            amount = price
            if purpose == "signup":
                tenant_id = create_from_signup(conn, signup_id, subscription_ref=data.get("subscription"))
            else:  # a new plan, or paying after a failed renewal: active from now for a month
                conn.execute("""
                    UPDATE subscriptions SET plan_key = %s, status = 'active', trial_ends_at = NULL,
                           current_period_end = now() + interval '1 month', grace_ends_at = NULL,
                           cancel_at_period_end = false, updated_at = now(),
                           provider_subscription_id = coalesce(%s, provider_subscription_id)
                    WHERE tenant_id = %s""", (plan_key, data.get("subscription"), tenant_id))
                conn.execute("UPDATE tenants SET plan = %s WHERE id = %s", (plan_key, tenant_id))
    elif event.kind in ("invoice.paid", "invoice.payment_failed"):
        row = conn.execute("SELECT s.tenant_id, s.plan_key, p.price_egp FROM subscriptions s JOIN plans p ON p.key = s.plan_key "
                           "WHERE s.provider_subscription_id = %s FOR UPDATE", (data.get("subscription"),)).fetchone()
        if row is None:
            log.warning("Billing: %s for an unknown subscription", event.kind)
            return
        tenant_id, plan_key, price = row
        if event.kind == "invoice.paid":
            amount = price
            conn.execute("""
                UPDATE subscriptions SET status = 'active', grace_ends_at = NULL, updated_at = now(),
                       current_period_end = greatest(current_period_end, now()) + interval '1 month'
                WHERE tenant_id = %s""", (tenant_id,))
        else:  # the first failure starts the grace period; a later one does not extend it
            conn.execute(f"""
                UPDATE subscriptions SET updated_at = now(),
                       grace_ends_at = CASE WHEN status = 'active' THEN now() + {GRACE} ELSE grace_ends_at END,
                       status = CASE WHEN status = 'active' THEN 'past_due' ELSE status END
                WHERE tenant_id = %s""", (tenant_id,))
    else:
        log.info("Billing: event %s ignored", event.kind)
    conn.execute("UPDATE billing_events SET tenant_id = %s, plan_key = %s, amount_egp = %s WHERE id = %s",
                 (tenant_id, plan_key, amount, event.id))


# ---------------------------------------------------------------- new universities from a sign-up

def create_from_signup(conn, signup_id, subscription_ref: str | None = None) -> uuid.UUID | None:
    """Make the signed-up university with its subscription (a trial, or paid for a month).
    Already made: its id. Refused now (say the address was taken meanwhile): None, logged."""
    row = conn.execute("SELECT email, email_domain, person, password_hash, plan_key, draft, tenant_id FROM signups "
                       "WHERE id = %s FOR UPDATE", (signup_id,)).fetchone()
    if row is None:
        return None
    email, domain, person, password_hash, plan_key, draft, tenant_id = row
    if tenant_id:
        return tenant_id
    chosen = plan(conn, plan_key)
    try:
        with conn.transaction():  # a savepoint: a refusal keeps the payment's record
            tenant_id, host = universities.create(
                conn, name=draft["university"], short_name=draft["short_name"], slug=draft["slug"], host=None,
                plan=plan_key, assistants=draft["assistants"], admin_email=email, admin_name=person,
                password_hash=password_hash, brand_primary=draft["brand_primary"], brand_accent=draft["brand_accent"],
                brand_dark=draft["brand_dark"], logo_url=draft.get("logo_url"),
                status="review" if require_review(conn) else "active", email_domain=domain, signed_up=True,
                reserved_too=True)
    except HTTPException as refused:
        log.warning("Billing: sign-up %s paid but not created: %s", signup_id, refused.detail)
        conn.execute("UPDATE signups SET draft = draft || %s WHERE id = %s",
                     (Jsonb({"error": refused.detail}), signup_id))
        return None
    if chosen["trial_days"]:
        conn.execute("INSERT INTO subscriptions (tenant_id, plan_key, status, provider, trial_ends_at) "
                     "VALUES (%s, %s, 'trialing', %s, now() + make_interval(days => %s))",
                     (tenant_id, plan_key, provider().name, chosen["trial_days"]))
    else:
        conn.execute("INSERT INTO subscriptions (tenant_id, plan_key, status, provider, provider_subscription_id, "
                     "current_period_end) VALUES (%s, %s, 'active', %s, %s, now() + interval '1 month')",
                     (tenant_id, plan_key, provider().name, subscription_ref))
    conn.execute("UPDATE signups SET tenant_id = %s WHERE id = %s", (tenant_id, signup_id))
    conn.execute("INSERT INTO billing_events (id, tenant_id, kind, plan_key) VALUES (%s, %s, 'subscription.created', %s)",
                 (f"local_{uuid.uuid4().hex}", tenant_id, plan_key))
    log.info("Sign-up: new university %s (%s) on %s", draft["university"], host, plan_key)
    return tenant_id


# ---------------------------------------------------------------- the university's choices

def checkout_for_university(tenant_id, plan_key: str) -> str:
    """The admin's "Choose this plan" / "Pay now": a payment page for the plan."""
    with get_admin_connection() as conn:
        current = subscription(conn, tenant_id)
        if current is None:
            raise HTTPException(400, "Your university's plan is managed by the platform. Please contact us to change it.")
        chosen = plan(conn, plan_key)
        if chosen is None or not chosen["public"] or chosen["trial_days"]:
            raise HTTPException(400, "Choose one of the paid plans.")
        in_use = conn.execute("SELECT count(*) FROM agents WHERE tenant_id = %s AND deleted_at IS NULL", (tenant_id,)).fetchone()[0]
        if chosen["max_assistants"] is not None and in_use > chosen["max_assistants"]:
            raise HTTPException(400, f"The {chosen['name']} plan allows {chosen['max_assistants']} assistants and you have "
                                     f"{in_use}. Delete some first, or choose a bigger plan.")
        pay_again = plan_key == current["plan"] and current["status"] in ("past_due", "paused", "canceled")
        if plan_key == current["plan"] and not pay_again:
            raise HTTPException(400, "You are already on this plan.")
        name = conn.execute("SELECT name FROM tenants WHERE id = %s", (tenant_id,)).fetchone()[0]
        return open_checkout(conn, "pay_now" if pay_again else "change_plan", plan_key, tenant_id=tenant_id, university=name)


def cancel(tenant_id) -> None:
    """Cancel: a paid month runs to its end, a trial ends now. Nothing is deleted."""
    with get_admin_connection() as conn:
        row = conn.execute("SELECT status, provider, provider_subscription_id FROM subscriptions WHERE tenant_id = %s "
                           "FOR UPDATE", (tenant_id,)).fetchone()
        if row is None:
            raise HTTPException(400, "Your university's plan is managed by the platform.")
        status, provider_name, ref = row
        if ref:
            providers.get(provider_name).cancel(ref)
        if status == "trialing":
            conn.execute("UPDATE subscriptions SET status = 'canceled', updated_at = now() WHERE tenant_id = %s", (tenant_id,))
        elif status in ("active", "past_due"):
            conn.execute("UPDATE subscriptions SET cancel_at_period_end = true, updated_at = now() WHERE tenant_id = %s", (tenant_id,))
        conn.execute("INSERT INTO billing_events (id, tenant_id, kind) VALUES (%s, %s, 'subscription.cancel_requested')",
                     (f"local_{uuid.uuid4().hex}", tenant_id))


def resume(tenant_id) -> None:
    """Undo a cancellation that has not ended yet."""
    with get_admin_connection() as conn:
        changed = conn.execute("UPDATE subscriptions SET cancel_at_period_end = false, updated_at = now() "
                               "WHERE tenant_id = %s AND cancel_at_period_end AND status IN ('active', 'past_due')",
                               (tenant_id,)).rowcount
        if not changed:
            raise HTTPException(400, "There is no cancellation to undo.")


# ---------------------------------------------------------------- the platform owner (console)

def simulate_month(tenant_id, payment_succeeds: bool) -> dict:
    """Test mode: a month passes for this subscription (its dates move a month back), then the
    provider renews it: a payment that succeeds or fails, sent through the webhook handling.
    A trial ends; a failed payment gives GRACE_DAYS; a month after that the chat is paused."""
    with get_admin_connection() as conn:
        row = conn.execute("SELECT provider FROM subscriptions WHERE tenant_id = %s FOR UPDATE", (tenant_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "This university has no subscription (it was added by hand).")
        if row[0] != "simulated":
            raise HTTPException(400, "Only test-mode subscriptions can be simulated.")
        conn.execute("""
            UPDATE subscriptions SET trial_ends_at = trial_ends_at - interval '1 month',
                   current_period_end = current_period_end - interval '1 month',
                   grace_ends_at = grace_ends_at - interval '1 month', updated_at = now()
            WHERE tenant_id = %s""", (tenant_id,))
        settle(conn, tenant_id)
        status, ref, due = conn.execute("SELECT status, provider_subscription_id, current_period_end <= now() "
                                        "FROM subscriptions WHERE tenant_id = %s", (tenant_id,)).fetchone()
    renewed = None
    if status in ("active", "past_due") and due and ref:
        kind = "invoice.paid" if payment_succeeds else "invoice.payment_failed"
        body, headers = providers.get("simulated").signed_event(kind, subscription=ref)
        receive_webhook("simulated", body, headers)
        renewed = kind
    with get_admin_connection() as conn:
        return {"renewal": renewed, "subscription": subscription(conn, tenant_id)}


def extend_trial(tenant_id, days: int) -> None:
    with get_admin_connection() as conn:
        changed = conn.execute(f"""
            UPDATE subscriptions s SET trial_ends_at = greatest(s.trial_ends_at, now()) + make_interval(days => %s),
                   status = 'trialing', updated_at = now()
            WHERE s.tenant_id = %s AND s.trial_ends_at IS NOT NULL AND s.current_period_end IS NULL
              AND ({EFFECTIVE_STATUS}) IN ('trialing', 'paused')""", (days, tenant_id)).rowcount
        if not changed:
            raise HTTPException(400, "Only a trial can be extended.")
        conn.execute("INSERT INTO billing_events (id, tenant_id, kind, data) VALUES (%s, %s, 'trial.extended', %s)",
                     (f"local_{uuid.uuid4().hex}", tenant_id, Jsonb({"days": days})))


def all_subscriptions() -> dict:
    with get_admin_connection() as conn:
        settle(conn)
        rows = conn.execute("""
            SELECT t.id, t.name, t.slug, t.status, s.plan_key, p.name, p.price_egp, s.status, s.trial_ends_at,
                   s.current_period_end, s.grace_ends_at, s.cancel_at_period_end, t.signed_up_at,
                   (SELECT max(e.created_at) FROM billing_events e WHERE e.tenant_id = t.id AND e.amount_egp IS NOT NULL),
                   (SELECT coalesce(sum(e.amount_egp), 0) FROM billing_events e WHERE e.tenant_id = t.id)
            FROM subscriptions s JOIN tenants t ON t.id = s.tenant_id JOIN plans p ON p.key = s.plan_key
            ORDER BY s.created_at DESC""").fetchall()
        events = conn.execute("""
            SELECT t.name, e.kind, e.plan_key, e.amount_egp, e.created_at FROM billing_events e
            LEFT JOIN tenants t ON t.id = e.tenant_id ORDER BY e.created_at DESC LIMIT 30""").fetchall()
    when = lambda value: value.isoformat() if value else None
    return {"subscriptions": [{
        "tenant_id": str(r[0]), "university": r[1], "slug": r[2], "university_status": r[3], "plan": r[4],
        "plan_name": r[5], "price_egp": r[6], "status": r[7], "trial_ends_at": when(r[8]),
        "current_period_end": when(r[9]), "grace_ends_at": when(r[10]), "cancel_at_period_end": r[11],
        "signed_up_at": when(r[12]), "last_payment_at": when(r[13]), "paid_total_egp": int(r[14])} for r in rows],
        "events": [{"university": u, "kind": k, "plan": p, "amount_egp": a, "at": when(t)} for u, k, p, a, t in events]}

