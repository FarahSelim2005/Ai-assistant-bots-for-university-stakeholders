-- 006: each university's look, and readable document folders.
--
-- * tenants: logo_url (a picture's address, or empty: the short name is shown instead),
--   brand_primary / brand_accent / brand_dark (the colours of buttons, stripes and the
--   header), intro (the start screen's text) and audiences (who the assistants are for, with
--   the start screen's text for each). GIU keeps exactly its current logo, colours and texts.
-- * agents.folder: the assistant's document folder (data/raw/<folder>/ for GIU,
--   data/tenants/<slug>/<folder>/ for others), readable and unique per university. GIU's are
--   their old names again (labs_research, ...); others get their template key, or a name made
--   from the assistant's name. After applying it, run python -m scripts.move_agent_folders.
--
-- Safe to run again.

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo_url      TEXT;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS brand_primary TEXT NOT NULL DEFAULT '#1f4e79'
    CHECK (brand_primary ~ '^#[0-9a-fA-F]{6}$');
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS brand_accent  TEXT NOT NULL DEFAULT '#e8a317'
    CHECK (brand_accent ~ '^#[0-9a-fA-F]{6}$');
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS brand_dark    TEXT NOT NULL DEFAULT '#1a1a1a'
    CHECK (brand_dark ~ '^#[0-9a-fA-F]{6}$');
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS intro         TEXT NOT NULL DEFAULT '';
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS audiences     JSONB NOT NULL DEFAULT
    '[{"key": "student", "title": "Student", "text": ""}, {"key": "staff", "title": "Staff", "text": ""}]';

UPDATE tenants SET
    logo_url = '/giu-logo.jpg',
    brand_primary = '#c4161c',
    brand_accent = '#d9a21b',
    brand_dark = '#1a1a1a',
    intro = 'Four assistants for students and staff: graduation and advising, HR and policies, '
            'internships and careers, and labs and research. University facts come only from '
            'official GIU documents.',
    audiences = '[{"key": "student", "title": "Student", "text": "Advising, careers, labs and research"}, '
                '{"key": "staff", "title": "Staff", "text": "All assistants, including HR & Policies"}]'
WHERE slug = 'giu' AND logo_url IS NULL;

ALTER TABLE agents ADD COLUMN IF NOT EXISTS folder TEXT;
-- GIU: the old names (its folders in git).
UPDATE agents SET folder = template_key
WHERE folder IS NULL AND id IN ('a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000002',
                                'a0000000-0000-4000-8000-000000000003', 'a0000000-0000-4000-8000-000000000004');
-- Others: the template key when it is the university's only assistant from that template,
-- otherwise a name made from the assistant's name and the start of its id.
UPDATE agents a SET folder = CASE
    WHEN a.template_key IS NOT NULL
         AND (SELECT count(*) FROM agents b WHERE b.tenant_id = a.tenant_id AND b.template_key = a.template_key) = 1
        THEN a.template_key
    ELSE left(coalesce(nullif(trim(BOTH '_' FROM lower(regexp_replace(a.name, '[^a-zA-Z0-9]+', '_', 'g'))), ''),
                       'assistant'), 40) || '_' || left(a.id::text, 8)
    END
WHERE a.folder IS NULL;
ALTER TABLE agents ALTER COLUMN folder SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agents_folder_check') THEN
        ALTER TABLE agents ADD CONSTRAINT agents_folder_check CHECK (folder ~ '^[a-z0-9][a-z0-9_-]{0,59}$');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agents_tenant_folder_key') THEN
        ALTER TABLE agents ADD CONSTRAINT agents_tenant_folder_key UNIQUE (tenant_id, folder);
    END IF;
END $$;
