-- 002: the app now names the tenant in every INSERT (step 1b), so:
-- 1. tenant_id loses its temporary GIU default from 001: an INSERT that forgets the
--    tenant now fails instead of silently becoming GIU.
-- 2. A message must belong to the same tenant as its conversation, and a rating to the
--    same tenant as its message (the database refuses cross-tenant links).
--
-- Apply it only after the backend runs the 1b code: the old code's INSERTs have no tenant_id.
-- Safe to run again: every step checks whether it was already done.

ALTER TABLE chunks        ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE conversations ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE messages      ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE feedback      ALTER COLUMN tenant_id DROP DEFAULT;

DO $$
BEGIN
    -- (id, tenant_id) pairs that the composite foreign keys below can point to
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'conversations_id_tenant_key') THEN
        ALTER TABLE conversations ADD CONSTRAINT conversations_id_tenant_key UNIQUE (id, tenant_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'messages_id_tenant_key') THEN
        ALTER TABLE messages ADD CONSTRAINT messages_id_tenant_key UNIQUE (id, tenant_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'messages_conversation_tenant_fkey') THEN
        ALTER TABLE messages ADD CONSTRAINT messages_conversation_tenant_fkey
            FOREIGN KEY (conversation_id, tenant_id) REFERENCES conversations (id, tenant_id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'feedback_message_tenant_fkey') THEN
        ALTER TABLE feedback ADD CONSTRAINT feedback_message_tenant_fkey
            FOREIGN KEY (message_id, tenant_id) REFERENCES messages (id, tenant_id) ON DELETE CASCADE;
    END IF;
END $$;
