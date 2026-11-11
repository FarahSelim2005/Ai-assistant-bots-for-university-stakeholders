-- 000: the original tables, as they were before multitenancy.
-- On the existing giu-bots database this changes nothing (every table already exists);
-- on a new, empty database it creates them, so the later migrations have something to change.

CREATE TABLE IF NOT EXISTS chunks (
    id        SERIAL PRIMARY KEY,
    agent     TEXT NOT NULL,
    audience  TEXT[] NOT NULL DEFAULT '{student,staff}',
    source    TEXT,
    content   TEXT NOT NULL,
    embedding DOUBLE PRECISION[]
);

CREATE TABLE IF NOT EXISTS conversations (
    id         SERIAL PRIMARY KEY,
    user_type  TEXT NOT NULL CHECK (user_type IN ('student', 'staff')),
    agent      TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS feedback (
    id         SERIAL PRIMARY KEY,
    message_id INTEGER REFERENCES messages(id) ON DELETE CASCADE,
    rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    created_at TIMESTAMPTZ DEFAULT now()
);
