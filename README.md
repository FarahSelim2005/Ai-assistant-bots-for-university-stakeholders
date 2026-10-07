# AI Assistant Bots for University Stakeholders

A GIU university chatbot made of four agents. This branch contains the first one,
the **Labs & Research agent**, as a complete working slice: database, backend,
frontend and evaluation.

The agent answers questions about labs, research facilities, funding and thesis
support **only from ingested documents** (retrieval-augmented generation). If no
document is relevant enough, it says it doesn't have the information instead of
guessing.

## How it works

```
Question ──► Rules ──► Retrieve ──► Validate ──► Generate ──► Answer + sources
             user type  embed question,  any chunk above   LLM answers only
             allowed?   cosine similarity the threshold?    from those chunks
             question   against chunks    no → fallback
             valid?     (agent + audience message, no LLM
                        filter)           call
```

| Layer | Files | Responsibility |
|---|---|---|
| Frontend | `frontend/src/` | React chat screen; all API calls in `src/api.js` |
| API | `backend/app/main.py`, `routers/` | HTTP endpoints, saving conversations, messages and feedback |
| Agents | `backend/app/agents/` | The rules → retrieve → validate → generate flow |
| RAG | `backend/app/rag/` | Embeddings, retrieval (cosine similarity with numpy), prompts |
| LLM | `backend/app/llm/openrouter.py` | One function that calls OpenRouter chat completions |
| Database | PostgreSQL `giu-bots` | Chunks with embeddings, conversations, messages, feedback |

**Stack:** Python 3.13, FastAPI, psycopg 3 (raw SQL), httpx, numpy, pypdf ·
PostgreSQL 18 · OpenRouter (`openai/text-embedding-3-small` for embeddings, chat
model set in `.env`) · React + Vite.

## Prerequisites (Windows)

- [Python 3.13](https://www.python.org/downloads/)
- [PostgreSQL 18](https://www.postgresql.org/download/windows/)
- [Node.js 20.19+ or 22.12+](https://nodejs.org/)
- [Git for Windows](https://git-scm.com/download/win) (all commands below are for **Git Bash**)
- An [OpenRouter](https://openrouter.ai/keys) API key with a few dollars of credit

## 1. Database

Create a database called `giu-bots` (for example in pgAdmin) and run this SQL in it.
Skip this if your database already has these tables.

```sql
CREATE TABLE chunks (
    id        SERIAL PRIMARY KEY,
    agent     TEXT NOT NULL,
    audience  TEXT[] NOT NULL DEFAULT '{student,staff}',
    source    TEXT,
    content   TEXT NOT NULL,
    embedding DOUBLE PRECISION[]
);

CREATE TABLE conversations (
    id         SERIAL PRIMARY KEY,
    user_type  TEXT NOT NULL CHECK (user_type IN ('student', 'staff')),
    agent      TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE feedback (
    id         SERIAL PRIMARY KEY,
    message_id INTEGER REFERENCES messages(id) ON DELETE CASCADE,
    rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    created_at TIMESTAMPTZ DEFAULT now()
);
```

pgvector is not used: embeddings are stored as `DOUBLE PRECISION[]` and the cosine
similarity is computed in Python (`cosine_similarity` in `backend/app/rag/retriever.py`).

## 2. Backend setup

```bash
cd backend
py -3.13 -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `backend/.env` and fill in:

| Variable | Value |
|---|---|
| `DB_PASSWORD` | your PostgreSQL password (the other `DB_` values usually stay as they are) |
| `OPENROUTER_API_KEY` | your key from https://openrouter.ai/keys |
| `LABS_MODEL` | a chat model ID from https://openrouter.ai/models, e.g. `google/gemini-2.5-flash-lite` |
| `VISION_MODEL` | a model that accepts **image** input, used only when a user attaches a picture, e.g. `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` (free, tested: reads English and Arabic text in images) or `google/gemini-2.5-flash-lite` (paid). Leave empty to allow documents only. |

`.env` is ignored by git. Never commit it.

**Choosing `LABS_MODEL`:** lab questions are simple lookups, so pick a fast,
cheap, *non-reasoning* model ("flash-lite", "nano", "mini"). Reasoning/"thinking"
models add several seconds. Copy the exact ID shown under the model's name on its
OpenRouter page and avoid IDs starting with `~` (they change over time).

**Free option:** `nvidia/nemotron-3-super-120b-a12b:free` scored 18/18 on the test set
(average 1.5 s). Avoid the `openrouter/free` router: it picks a random free model per
request, including a safety classifier that replies "User Safety: safe", and scored
13/18 with answers up to 16 s. Free models have daily rate limits (`429 Too Many
Requests`) and may log prompts, so use a paid model for the final evaluation if
possible, and always report which model ID you used.

> Every new Git Bash terminal needs `cd backend` and `source .venv/Scripts/activate`
> before the Python commands below.

## 3. Ingest documents

Put `.pdf`, `.txt` or `.md` files in `backend/data/raw/`, then:

```bash
python -m scripts.ingest
```

Each file is split into chunks (paragraphs kept together, a new chunk at every
Markdown heading, at most 200 words), embedded, and stored with
`agent = labs_research` and `audience = {student, staff}`. Re-running is safe:
a file's old chunks are replaced.

Options: `--agent <name>`, `--audience student` (staff-only or student-only
documents), `--folder <path>`.

The two files in `data/raw/` are **fictional placeholder data** for testing. Replace
them with official GIU documents:

- `sample_labs_and_research.md`: labs, research funding and thesis support
- `campus_buildings.md`: Buildings A, M and S, room numbering (ground floor 001–030,
  then 101–120, 201–220, 301–320, 401–420) and offices such as Admission, Academic
  Coordinator, German Office, Clinic, Library, Finance and Student Affairs

Quick checks from the terminal:

```bash
python -m scripts.try_retrieve "where is the AI lab?"   # retrieved chunks and their scores
python -m scripts.try_chat "where is the AI lab?"       # full agent answer and timing
```

## 4. Run the backend

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs to try the API:

| Endpoint | Body | Returns |
|---|---|---|
| `POST /session` | `{"user_type": "student"}` | `{"conversation_id": 1}` |
| `POST /chat` | `{"conversation_id": 1, "query": "where is the AI lab?"}` | `{"answer", "sources", "message_id"}` |
| `POST /feedback` | `{"message_id": 2, "rating": 5}` | `{"feedback_id"}` |

`/chat` sends the last 4 messages of the conversation along, so follow-up
questions like "and when is it open?" work.

## 5. Run the frontend

In a second Git Bash terminal, with the backend still running:

```bash
cd frontend
npm install      # first time only
npm run dev
```

Open http://localhost:5173, choose **Student** or **Staff**, and start asking.
Each answer shows its source files and a 1–5 rating.

**Campus map:** when an answer mentions a room such as `M005` or `A312`, a map card
appears under it: a drawing of the GIU campus (traced from an aerial map: A top-left,
S below A next to the road, M on the right) with the building highlighted, the floor
marked, step-by-step directions from the car park, and a Google Maps link to the
campus. The rooms are found by code (`backend/app/campus.py`), not by the language
model, and only codes that follow the numbering rules are shown. The layout in
`frontend/src/components/CampusMap.jsx` matches the "Campus Layout and Directions"
section of `campus_buildings.md`; keep the two in sync.

**Voice call:** the 📞 Call button (Edge and Chrome) opens a hands-free call: the
assistant greets you, listens, sends what you said as a normal chat question, reads
the answer aloud and listens again, until you hang up. Speech recognition and the
voice are the browser's own (Web Speech API), so no extra service or dependency is
needed; the browser sends the audio to its speech service (Microsoft or Google) to
turn it into text. Each spoken question is one normal chat request, and the whole
call appears in the chat afterwards (including maps). Tap the circle to interrupt
the assistant. A switch at the top chooses the spoken language: **English** or
**عربي + English** (Egyptian Arabic, which also understands English words mixed into
Arabic sentences). Answers are read with an Arabic or English voice depending on
their text, and Arabic questions get Arabic answers (room codes stay in Latin letters
so the map still works). Code: `frontend/src/components/CallScreen.jsx`.

**Attachments:** the 📎 button lets students and staff attach one file to a question
(PDF, TXT, MD, PNG, JPG or WEBP, up to 5 MB) and ask about it. Documents are converted
to text (first 12,000 characters) and sent to `LABS_MODEL`; images are sent to
`VISION_MODEL`. The agent answers from the attachment plus the retrieved GIU documents,
says "According to your file..." when it uses the attachment, and ignores instructions
written inside the file. Files are not stored: the saved message only records the file
name, so a follow-up question about the same file needs the file attached again.
Scanned PDFs have no text; upload them as images instead.

The backend URL is set in `frontend/src/api.js`. The backend only accepts requests
from `http://localhost:5173` (CORS, set in `backend/app/config.py`).

## 6. Evaluate

```bash
cd backend
source .venv/Scripts/activate
python -m scripts.evaluate
```

Every row of `backend/data/test_questions.csv` (`question, expected_keywords, agent`)
is sent directly to the agent. An answer is correct when it contains **all** expected
keywords (separated by `;`, case-insensitive). The script prints accuracy, average
and maximum response time, and how many answers took over 2 seconds.

```bash
python -m scripts.evaluate --user-type staff --out data/results.csv   # save every answer
```

The 18 included questions are placeholders based on the two sample documents. The
last two ask for information that is not in the documents and expect `don't have`,
to check the agent does not invent answers.

## Settings

All settings are in `backend/app/config.py`:

| Setting | Default | Meaning |
|---|---|---|
| `TOP_K` | 4 | chunks returned by the retriever |
| `SIMILARITY_THRESHOLD` | 0.35 | chunks below this score are ignored; if none pass, the fallback message is returned |
| `CHUNK_SIZE_WORDS` / `CHUNK_OVERLAP_WORDS` | 200 / 40 | chunking during ingestion |

Re-check `SIMILARITY_THRESHOLD` after adding real documents: run `try_retrieve` with
questions that should and should not be answerable, and pick a value between their
best scores.

## Project structure

```
backend/
  app/
    main.py              FastAPI app, CORS, routers
    config.py            all settings (reads .env)
    attachments.py       reads files attached to a chat message
    campus.py            finds room codes in answers for the campus map
    db.py                PostgreSQL connection
    schemas.py           request/response models
    routers/             session.py, chat.py, feedback.py
    agents/              base.py (shared flow), labs_research.py
    rag/                 embeddings.py, retriever.py, prompts.py
    llm/openrouter.py    chat completions call
  scripts/
    ingest.py            load documents into the chunks table
    evaluate.py          accuracy and response time on test questions
    try_retrieve.py      show retrieved chunks for a question
    try_chat.py          ask the agent from the terminal
  data/
    raw/                 documents to ingest
    test_questions.csv   evaluation questions
frontend/
  src/
    api.js               all backend calls (API URL)
    App.jsx              chat state and flow
    components/          StartScreen.jsx, Message.jsx, CampusMap.jsx, CallScreen.jsx
    App.css              styles
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `401 Unauthorized` from OpenRouter | The key in `backend/.env` is wrong or revoked. Create a new one at https://openrouter.ai/keys. |
| `No chat model given` / model errors | Set `LABS_MODEL` in `backend/.env` to an exact ID from https://openrouter.ai/models. |
| `connection failed` / password errors | Check PostgreSQL is running and the `DB_` values in `backend/.env`. |
| Every answer is the fallback message | Run `python -m scripts.ingest`, then check scores with `try_retrieve`. |
| `Port 5173 is in use` | Close the other Vite server. The port is fixed because CORS only allows 5173. |
| Frontend shows "Failed to fetch" | The backend is not running on port 8000. |
| `ModuleNotFoundError: No module named 'app'` | Run the commands from the `backend` folder with `python -m scripts.<name>`. |
