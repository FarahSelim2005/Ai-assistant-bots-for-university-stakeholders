-- 001: tenants (universities) and the hosts that open them. Every existing chunk,
-- conversation, message and rating becomes tenant "giu".
--
-- Safe to run again: every step checks whether it was already done.
-- No behaviour change yet: tenant_id gets a temporary default of GIU's id, so the app's
-- current INSERTs (which don't name a tenant) keep working. Step 1b removes that default.

CREATE TABLE IF NOT EXISTS tenants (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug       TEXT NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,39}$'),  -- the subdomain, e.g. "giu"
    name       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    plan       TEXT NOT NULL DEFAULT 'free',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Host names without the port ("giu.localhost", later "chat.giu-uni.de"), in lower case.
CREATE TABLE IF NOT EXISTS tenant_domains (
    host       TEXT PRIMARY KEY CHECK (host = lower(host) AND host !~ ':'),
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    is_primary BOOLEAN NOT NULL DEFAULT false
);
-- At most one primary host per tenant (the one used in links).
CREATE UNIQUE INDEX IF NOT EXISTS tenant_domains_one_primary ON tenant_domains (tenant_id) WHERE is_primary;

INSERT INTO tenants (slug, name)
VALUES ('giu', 'German International University')
ON CONFLICT (slug) DO NOTHING;

-- Plain localhost and 127.0.0.1 keep opening GIU, so the current setup keeps working.
INSERT INTO tenant_domains (host, tenant_id, is_primary)
SELECT host, tenants.id, host = 'giu.localhost'
FROM tenants, unnest(ARRAY['localhost', '127.0.0.1', 'giu.localhost']) AS host
WHERE tenants.slug = 'giu'
ON CONFLICT (host) DO NOTHING;

-- tenant_id on every table with tenant data: added, filled with GIU, then required.
DO $$
DECLARE
    giu   UUID := (SELECT id FROM tenants WHERE slug = 'giu');
    tname TEXT;
BEGIN
    FOREACH tname IN ARRAY ARRAY['chunks', 'conversations', 'messages', 'feedback'] LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = tname AND column_name = 'tenant_id') THEN
            EXECUTE format('ALTER TABLE %I ADD COLUMN tenant_id UUID', tname);
            -- Temporary (only when the column is new, so a second run after 1b doesn't bring it back).
            EXECUTE format('ALTER TABLE %I ALTER COLUMN tenant_id SET DEFAULT %L', tname, giu);
        END IF;
        EXECUTE format('UPDATE %I SET tenant_id = %L WHERE tenant_id IS NULL', tname, giu);
        EXECUTE format('ALTER TABLE %I ALTER COLUMN tenant_id SET NOT NULL', tname);
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = tname || '_tenant_id_fkey') THEN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (tenant_id) REFERENCES tenants(id)',
                           tname, tname || '_tenant_id_fkey');
        END IF;
    END LOOP;
END $$;

-- Retrieval loads one tenant's chunks of one agent.
CREATE INDEX IF NOT EXISTS chunks_tenant_agent ON chunks (tenant_id, agent);
