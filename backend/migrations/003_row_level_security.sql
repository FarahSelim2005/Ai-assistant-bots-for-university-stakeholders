-- 003: row-level security. The app logs in as giu_app, a role that only sees and changes the
-- rows of the tenant set in app.tenant_id, even if a query forgets "WHERE tenant_id = ...".
--
-- giu_app: LOGIN, not a superuser, not the owner of the tables (owners and superusers could
-- skip the policies), only SELECT/INSERT/UPDATE/DELETE on the app's tables and USAGE on their
-- sequences; tenants and tenant_domains are read-only for it. The password is NOT in this
-- file: set it once with ALTER ROLE giu_app PASSWORD '...'; (see README). Roles belong to the
-- whole PostgreSQL server, so a test database migrated on the same server shares this role.
--
-- Safe to run again: the role and the policies are created or replaced.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'giu_app') THEN
        CREATE ROLE giu_app LOGIN;
    END IF;
    -- Also when the role already existed: make sure it has no powers beyond logging in.
    ALTER ROLE giu_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO giu_app', current_database());
END $$;

GRANT USAGE ON SCHEMA public TO giu_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON chunks, conversations, messages, feedback TO giu_app;
GRANT SELECT ON tenants, tenant_domains TO giu_app;  -- needed to find the tenant of a request
GRANT USAGE ON SEQUENCE chunks_id_seq, conversations_id_seq, messages_id_seq, feedback_id_seq TO giu_app;

-- The policy: a row is visible, and may be written, only when its tenant_id is the current
-- tenant. NULLIF: once a transaction that set app.tenant_id ends, the setting reads as ''
-- (not NULL) in that session, and ''::uuid would be an error instead of "no rows".
-- FORCE: the policy also applies to the owner of the table (but never to superusers).
DO $$
DECLARE
    tname TEXT;
BEGIN
    FOREACH tname IN ARRAY ARRAY['chunks', 'conversations', 'messages', 'feedback'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tname);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tname);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', tname);
        EXECUTE format('CREATE POLICY tenant_isolation ON %I '
                       'USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid) '
                       'WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)',
                       tname);
    END LOOP;
END $$;
