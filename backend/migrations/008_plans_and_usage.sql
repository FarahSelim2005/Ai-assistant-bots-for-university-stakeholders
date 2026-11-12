-- 008: plans and usage, for the platform console.
--
-- * plans: what a university may use: monthly_token_cap (tokens of all model calls in a
--   calendar month; empty = no limit) and max_assistants (empty = no limit). tenants.plan
--   must be one of them. GIU is on "unlimited", so it keeps working as before.
-- * usage: one row per model call (chat, pictures, CV rewrites, document edits, embeddings):
--   university, assistant (if any), model, kind and tokens. Row-level security like the other
--   tenant tables; the app inserts and reads its own university's rows.
--
-- Safe to run again.

CREATE TABLE IF NOT EXISTS plans (
    key               TEXT PRIMARY KEY CHECK (key ~ '^[a-z0-9_]{1,30}$'),
    name              TEXT NOT NULL,
    monthly_token_cap BIGINT CHECK (monthly_token_cap > 0),
    max_assistants    INTEGER CHECK (max_assistants > 0),
    position          INTEGER NOT NULL DEFAULT 0
);
INSERT INTO plans (key, name, monthly_token_cap, max_assistants, position) VALUES
    ('free', 'Free', 300000, 2, 1),
    ('standard', 'Standard', 5000000, 8, 2),
    ('unlimited', 'Unlimited', NULL, NULL, 3)
ON CONFLICT (key) DO NOTHING;
GRANT SELECT ON plans TO giu_app;

UPDATE tenants SET plan = 'unlimited' WHERE slug = 'giu' AND plan = 'free';
UPDATE tenants SET plan = 'free' WHERE plan NOT IN (SELECT key FROM plans);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tenants_plan_fkey') THEN
        ALTER TABLE tenants ADD CONSTRAINT tenants_plan_fkey FOREIGN KEY (plan) REFERENCES plans (key);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS usage (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         UUID NOT NULL REFERENCES tenants(id),
    agent_id          UUID,                     -- the assistant, when the call was for one
    model             TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('chat', 'embedding')),
    prompt_tokens     INTEGER NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
    completion_tokens INTEGER NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
    total_tokens      INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS usage_tenant_time ON usage (tenant_id, created_at);
ALTER TABLE usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON usage;
CREATE POLICY tenant_isolation ON usage
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
GRANT SELECT, INSERT ON usage TO giu_app;
GRANT USAGE ON SEQUENCE usage_id_seq TO giu_app;
