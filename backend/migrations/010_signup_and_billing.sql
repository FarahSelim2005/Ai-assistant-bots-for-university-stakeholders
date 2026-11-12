-- 010: self-service sign-up and subscriptions (the design's "Sign up (public)" page).
--
-- * plans: a monthly price in EGP (changeable in the console), trial days (the free trial),
--   and whether the plan is offered on the public sign-up page. A new "campus" plan; the
--   "unlimited" plan (GIU) is not offered publicly.
-- * signups: one row per sign-up in progress: the email, a hash of the 6-digit email code
--   (never the code itself) with its expiry and tries, and the draft (university, address,
--   colour, assistants, the admin's password hash). tenant_id once the university exists.
-- * checkouts: a payment page opened with the payment provider (for a sign-up, a plan
--   change or paying a failed renewal), and its outcome.
-- * subscriptions: one per university that signed up itself: plan, status, trial end,
--   current period, grace period after a failed payment, cancel at period end. Universities
--   added by hand in the console (GIU, demo) have none: they are never paused by billing.
-- * billing_events: every webhook event (unique id, so a repeated event is applied once),
--   with the amount for payments: the payment history in the admin and the console.
-- * platform_settings: platform-wide switches, e.g. require_review (new sign-ups wait for
--   the platform owner's approval: tenants.status 'review').
-- * tenants: email_domain (the domain its sign-up proved; one university per domain) and
--   signed_up_at (made by the public sign-up, not by hand).
--
-- Nothing is deleted. Safe to run again.

ALTER TABLE plans ADD COLUMN IF NOT EXISTS price_egp   INTEGER NOT NULL DEFAULT 0 CHECK (price_egp >= 0);
ALTER TABLE plans ADD COLUMN IF NOT EXISTS trial_days  INTEGER CHECK (trial_days > 0);  -- empty: not a trial
ALTER TABLE plans ADD COLUMN IF NOT EXISTS public      BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';

INSERT INTO plans (key, name, monthly_token_cap, max_assistants, position) VALUES
    ('campus', 'Campus', 20000000, NULL, 3)
ON CONFLICT (key) DO NOTHING;
UPDATE plans SET position = 4 WHERE key = 'unlimited' AND position = 3;
-- Example prices; the platform owner changes them in the console. Only rows still at their
-- defaults are filled, so a second run keeps changed prices.
UPDATE plans SET name = 'Free trial', trial_days = 14, public = true,
                 description = 'Try it for 14 days. No card needed.'
 WHERE key = 'free' AND name = 'Free' AND NOT public;
UPDATE plans SET price_egp = 7500, public = true, description = 'For most universities.'
 WHERE key = 'standard' AND price_egp = 0 AND NOT public;
UPDATE plans SET price_egp = 22500, public = true, description = 'Unlimited assistants for a whole campus.'
 WHERE key = 'campus' AND price_egp = 0 AND NOT public;

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS email_domain TEXT CHECK (email_domain = lower(email_domain));
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS signed_up_at TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS tenants_email_domain_key ON tenants (email_domain);
-- 'review': signed up, waiting for the platform owner's approval (when require_review is on)
ALTER TABLE tenants DROP CONSTRAINT IF EXISTS tenants_status_check;
ALTER TABLE tenants ADD CONSTRAINT tenants_status_check CHECK (status IN ('active', 'suspended', 'review'));

CREATE TABLE IF NOT EXISTS platform_settings (
    key   TEXT PRIMARY KEY,
    value JSONB NOT NULL
);
INSERT INTO platform_settings (key, value) VALUES ('require_review', 'false') ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS signups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL CHECK (email = lower(email)),
    email_domain    TEXT NOT NULL,
    person          TEXT NOT NULL DEFAULT '',
    password_hash   TEXT NOT NULL,
    plan_key        TEXT NOT NULL REFERENCES plans (key),
    code_hash       TEXT,                           -- sha256 of salt + code
    code_salt       TEXT,
    code_expires_at TIMESTAMPTZ,
    code_tries      INTEGER NOT NULL DEFAULT 0,
    codes_sent      INTEGER NOT NULL DEFAULT 0,
    code_sent_at    TIMESTAMPTZ,
    verified_at     TIMESTAMPTZ,
    draft           JSONB NOT NULL DEFAULT '{}',    -- university, short name, slug, colour, assistants
    tenant_id       UUID REFERENCES tenants (id),   -- once the university exists
    client_ip       TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS signups_domain ON signups (email_domain);

CREATE TABLE IF NOT EXISTS checkouts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    purpose     TEXT NOT NULL CHECK (purpose IN ('signup', 'change_plan', 'pay_now')),
    signup_id   UUID REFERENCES signups (id),
    tenant_id   UUID REFERENCES tenants (id),
    plan_key    TEXT NOT NULL REFERENCES plans (key),
    amount_egp  INTEGER NOT NULL CHECK (amount_egp >= 0),
    provider    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'paid', 'failed')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    CHECK ((purpose = 'signup') = (signup_id IS NOT NULL) AND (purpose = 'signup' OR tenant_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS subscriptions (
    tenant_id                UUID PRIMARY KEY REFERENCES tenants (id),
    plan_key                 TEXT NOT NULL REFERENCES plans (key),
    status                   TEXT NOT NULL CHECK (status IN ('trialing', 'active', 'past_due', 'paused', 'canceled')),
    provider                 TEXT NOT NULL,
    provider_subscription_id TEXT,
    trial_ends_at            TIMESTAMPTZ,
    current_period_end       TIMESTAMPTZ,
    grace_ends_at            TIMESTAMPTZ,    -- past_due: the chat pauses after this
    cancel_at_period_end     BOOLEAN NOT NULL DEFAULT false,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS billing_events (
    id         TEXT PRIMARY KEY,                -- the provider's event id
    tenant_id  UUID REFERENCES tenants (id),
    kind       TEXT NOT NULL,                   -- checkout.paid, invoice.payment_failed, ...
    plan_key   TEXT,
    amount_egp INTEGER,                         -- payments only
    data       JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS billing_events_tenant_time ON billing_events (tenant_id, created_at);

-- The app's role reads its own university's subscription and payments (the chat checks
-- the subscription); only the billing code (the owner connection) writes them.
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON subscriptions;
CREATE POLICY tenant_isolation ON subscriptions
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
GRANT SELECT ON subscriptions TO giu_app;
ALTER TABLE billing_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON billing_events;
CREATE POLICY tenant_isolation ON billing_events
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
GRANT SELECT ON billing_events TO giu_app;
-- signups, checkouts and platform_settings: platform tables, the owner connection only.
