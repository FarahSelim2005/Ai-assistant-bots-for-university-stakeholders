-- 009: the cost of each model call, for the console's "Model cost".
-- OpenRouter reports the cost of every call (in US dollars) when asked to; Groq's free tier
-- and local Ollama models cost nothing, so their calls are logged with 0.
-- Safe to run again.

ALTER TABLE usage ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(12, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0);
