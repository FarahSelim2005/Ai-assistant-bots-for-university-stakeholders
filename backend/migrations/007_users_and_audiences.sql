-- 007: the university admin. Per-user logins, audiences per university, deleting assistants
-- without losing data, and universities changing their own look.
--
-- * users: email + password (scrypt hash, never the password itself) and a role:
--   tenant_admin (everything of its university), editor (documents only), or platform_owner
--   (the platform console; no university, and invisible to the app's role giu_app).
--   Accounts are made with python -m scripts.create_user. Replaces ADMIN_PASSWORD.
-- * Audiences: any keys a university defines in tenants.audiences (not only student and
--   staff): the fixed student/staff checks become format checks.
-- * agents.deleted_at: a deleted assistant is hidden everywhere but kept, with its chats and
--   documents.
-- * tenants: readable by everyone (the tenant is found from the host), and giu_app may
--   change only its own university's name, look, intro and audiences (row-level security).
--
-- Safe to run again.

CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID REFERENCES tenants(id),        -- empty only for platform owners
    email         TEXT NOT NULL CHECK (email = lower(email) AND email LIKE '%_@_%'),
    name          TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('tenant_admin', 'editor', 'platform_owner')),
    active        BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ,
    CHECK ((role = 'platform_owner') = (tenant_id IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS users_email_key ON users (email);  -- one account per email address
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON users;
CREATE POLICY tenant_isolation ON users
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
GRANT SELECT, INSERT, UPDATE ON users TO giu_app;  -- no DELETE: accounts are deactivated

-- Audiences per university: format checks instead of the fixed student/staff lists.
ALTER TABLE conversations   DROP CONSTRAINT IF EXISTS conversations_user_type_check;
ALTER TABLE agents          DROP CONSTRAINT IF EXISTS agents_audiences_check;
ALTER TABLE agent_templates DROP CONSTRAINT IF EXISTS agent_templates_audiences_check;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'conversations_user_type_format') THEN
        ALTER TABLE conversations ADD CONSTRAINT conversations_user_type_format CHECK (user_type ~ '^[a-z0-9_]{1,30}$');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agents_audiences_format') THEN
        ALTER TABLE agents ADD CONSTRAINT agents_audiences_format CHECK (cardinality(audiences) BETWEEN 1 AND 10);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agent_templates_audiences_format') THEN
        ALTER TABLE agent_templates ADD CONSTRAINT agent_templates_audiences_format CHECK (cardinality(audiences) BETWEEN 1 AND 10);
    END IF;
END $$;

ALTER TABLE agents ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- tenants: everyone reads (finding the tenant of a request); a university changes only its own row.
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenants_read ON tenants;
CREATE POLICY tenants_read ON tenants FOR SELECT USING (true);
DROP POLICY IF EXISTS tenants_update_own ON tenants;
CREATE POLICY tenants_update_own ON tenants FOR UPDATE
    USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
GRANT UPDATE (name, short_name, logo_url, brand_primary, brand_accent, brand_dark, intro, audiences) ON tenants TO giu_app;
