# AI Assistant Bots for University Stakeholders

A GIU university chatbot made of five agents. Two are built here as complete working
slices (database, backend, frontend and evaluation):

- **Labs & Research** (students and staff): labs, campus buildings, rooms, offices and
  places, answered **only from ingested documents** (retrieval-augmented generation). If
  no document is relevant enough, it says it doesn't have the information instead of
  guessing.
- **Internship & Career** (students and staff): the GIU Career Fair, the GIU Internship
  Semester, how to apply, CVs, interviews, skills and career paths. **GIU facts come only
  from its documents**; general career advice may also come from the model's own
  knowledge and is marked "General advice:". It can **analyse an uploaded CV**
  ("📄 Analyze my CV").
- **Graduation & Advising** (students and staff): the advising process, the advising
  list, probation, adding hours, schedule rules, electives, B.Sc./internship eligibility,
  memos and graduation plans, answered **only from its documents** (the Academic
  Performance Department's advising guidelines), like Labs & Research.

- **HR & Policies** (staff only): leave, public holidays, contracts, the annual raise,
  resignation and notice, answered **only from its document** (Egyptian Labour Law No. 14 of 2025
  and GIU facts; GIU's own HR policies are listed as "ask GIU HR" until they are added).

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
| LLM | `backend/app/llm/client.py` | Chat completions through OpenRouter, or a local Ollama model (`ollama/<name>`) |
| Database | PostgreSQL `giu-bots` | Chunks with embeddings, conversations, messages, feedback |

**Stack:** Python 3.13, FastAPI, psycopg 3 (raw SQL), httpx, numpy, PyMuPDF (PDF text in reading order, link URLs) with pypdf as fallback, python-docx /
openpyxl / python-pptx (document editor) ·
PostgreSQL 18 · OpenRouter (`baai/bge-m3` multilingual embeddings, chat
model set in `.env`) · React + Vite.

## Prerequisites (Windows)

- [Python 3.13](https://www.python.org/downloads/)
- [PostgreSQL 18](https://www.postgresql.org/download/windows/)
- [Node.js 20.19+ or 22.12+](https://nodejs.org/)
- [Git for Windows](https://git-scm.com/download/win) (all commands below are for **Git Bash**)
- An [OpenRouter](https://openrouter.ai/keys) API key with a few dollars of credit

## 1. Database

Create a database called `giu-bots` (for example in pgAdmin). The tables are created and
changed by the numbered SQL files in `backend/migrations/`, applied in order by
`scripts/migrate.py` once the backend is set up (step 2):

```bash
cd backend
source .venv/Scripts/activate
python -m scripts.migrate --status   # which files are applied / pending
python -m scripts.migrate            # apply the pending ones
```

**Back up the database first** (pgAdmin: right-click `giu-bots` → *Backup...*, format
*Custom*). Each file runs in its own transaction, so a failing file changes nothing, and
applied files are recorded in the `schema_migrations` table, so running the command again
only applies new files. Every file is also safe to run twice by hand.

| File | What it does |
|---|---|
| `000_base.sql` | The original tables (`chunks`, `conversations`, `messages`, `feedback`). Changes nothing on an existing database. |
| `001_tenants.sql` | Multitenancy: a `tenants` table (one row per university; `giu` is created) and `tenant_domains` (which host opens which university: `localhost`, `127.0.0.1` and `giu.localhost` open GIU). Adds `tenant_id` to `chunks`, `conversations`, `messages` and `feedback`, fills it with GIU's id for all existing rows and makes it required. Until the app sends the tenant itself, `tenant_id` defaults to GIU, so nothing changes for the app. |

To try the migrations on a copy first: in pgAdmin create a database `giu-bots-copy` with
*Template* `giu-bots` (no other connection to `giu-bots` may be open), then run
`python -m scripts.migrate --database giu-bots-copy`.

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

**Groq models:** writing `groq/<name>` in a model list (e.g.
`LABS_BACKUP_MODEL=...,groq/openai/gpt-oss-120b`) sends that request to
[Groq](https://console.groq.com) with `GROQ_API_KEY` (the key also used for voice). Groq's
free tier is separate from OpenRouter's daily limit, and GPT-OSS 120B answers in about
1-3 s (Groq retired Llama 3.3 70B). The free tier allows 8,000 tokens per minute, about
6 questions a minute; above that the next model in the list answers. It reads text only, so it is not used for pictures.

**Local model (Ollama):** writing `ollama` in a model list (e.g.
`LABS_BACKUP_MODEL=...,ollama`) runs `OLLAMA_MODEL` on your own computer through
[Ollama](https://ollama.com): free, unlimited and offline. It is the last backup, used
when the online models fail. Default `OLLAMA_MODEL=gemma3:1b` (switch back with
`OLLAMA_MODEL=gemma4:e4b`, better in Arabic but ~30-50 s per answer on a laptop). Local
requests in `backend/app/llm/client.py` use Ollama's own `/api/chat` with thinking off
(`think: false`), the model kept loaded (`keep_alive: -1`), short answers
(`num_predict: 100`, `num_ctx: 2048`, "1-3 short sentences"), at most 1,200 characters of
documents and the last 2 history messages, and a warm-up when the backend starts.
Measured on a laptop with a GeForce 940MX: gemma3:1b answers in ~3-5 s. Each request's
time is logged ("Ollama gemma3:1b answered in 3.4 s"). Ollama must be running
(`ollama serve`, or the Ollama app).

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

Each agent has its own folder: put `.pdf`, `.txt` or `.md` files in
`backend/data/raw/<agent>/` (`labs_research`, `internship_career`, `graduation_advising`), then:

```bash
python -m scripts.ingest                            # every agent's folder
python -m scripts.ingest --agent internship_career  # only one agent
```

Each file is split into chunks (paragraphs kept together, a new chunk at every
Markdown heading, at most 200 words), embedded, and stored with the folder's agent
and that agent's audience from `backend/app/agents/directory.py` (HR: staff
only). Re-running is safe: a file's old chunks are replaced, and chunks of files you
deleted are removed.

The documents:

- `graduation_advising/advising_guidelines.md`: the slides "Advising Process – General
  Guidelines" (Heba El Mougy, Academic Performance Department) written out as text: what
  advising means, reasons for the advising list, probation (GPA > 3.7), the process steps,
  order of courses, adding hours (minimum load 60%), schedule constraints, electives,
  B.Sc./internship eligibility, ticketing and memos, graduation plans. Topics the slides
  only name (e.g. consequences of probation, timeline dates) are listed as not covered.
  Every section also has an Egyptian Arabic version.
- `graduation_advising/computer_science_curriculum.md`: the four Computer Science
  programs (Data Science, Software Engineering, IT Security, Media Informatics): courses
  and ECTS per semester (semesters 1-4 and 7-8 shared, 5-6 per program, 240 ECTS each),
  program descriptions, and one short section per course (its Arabic name, semester, ECTS
  and programs), all with Arabic.
- `graduation_advising/business_informatics_curriculum.md`: the Business Informatics
  program: description, courses and ECTS per semester (240 ECTS), and one section per
  course, all with Arabic.
- `graduation_advising/business_administration_curriculum.md`: the seven Business
  Administration majors (International Business; Finance, Banking & Accounting; Digital
  Marketing; Entrepreneurship & SMEs; Supply Chain Management; Real Estate Management;
  Tourism & Hospitality Management): shared and major-specific semesters (240 ECTS),
  descriptions, core competencies and job profiles, and one section per course, with Arabic.
- `graduation_advising/design_curriculum.md`: the three Design majors (Digital Media and
  Communication Design, Fashion Design, Industrial Design): semesters (1, 7 and 8 shared,
  30 ECTS each, 240 in total), descriptions and one section per course, with Arabic.
- `graduation_advising/engineering_curriculum.md`: the five Engineering majors (Automotive
  Mechatronics, Manufacturing, Robotics and Automation, Automation and Control, Electrical
  Power Systems): semesters (1, 2, 7, 8 shared by all; 3-4 shared within the mechatronics and
  the electrical groups), six electives, descriptions and one section per course, with Arabic.
- `graduation_advising/biotechnology_curriculum.md`: the Biotechnology program: courses and
  ECTS per semester (240 ECTS), four electives and one section per course, with Arabic.
- `graduation_advising/physical_therapy_curriculum.md`: the Physical Therapy program: 10
  semesters of 30 ECTS (300 ECTS), Bachelor thesis in semester 8, four electives in semesters
  9-10, and one section per course, with Arabic.
- `graduation_advising/architecture_curriculum.md`: Architectural Engineering with its two
  majors (Architectural Design, Interior Architecture; semesters 5-6 differ), 240 ECTS, four
  electives, and one section per course, with Arabic.
- `graduation_advising/pharmaceutical_engineering_curriculum.md`: Pharmaceutical Engineering
  and Technology: semesters (240 ECTS), four electives, job profiles, and one section per
  course, with Arabic.
- `internship_career/career_guide.md`: GIU facts from GIU's official news pages (Career
  Fair 2025 on November 14 with 95 exhibitors and its employers, the five-month GIU
  Internship Semester, the first fair in 2022 and the GIU Career Center, with sources),
  plus general advice: fair preparation, CVs, interviews, applying, and skills and
  career paths per faculty. Check the GIU website before relying on dates.
- `labs_research/campus_buildings.md` (**fictional placeholder data**, replace it with
  official GIU documents): Buildings A, M and S, room numbering (ground floor 001–030,
  then 101–120, 201–220, 301–320, 401–420), offices such as Admission, Academic
  Coordinator, German Office, Clinic, Library, Finance and Student Affairs, and places
  such as the supermarket, gym and sports courts

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

Open http://localhost:5173, choose **Student** or **Staff**, then choose an assistant:
students see 3 (Graduation & Advising, Internship & Career, Labs & Research), staff see all 4. The list is in
`frontend/src/agents.js`; all four assistants are built.
Each answer shows its source files and a 1–5 rating.

**Campus map:** when an answer mentions a room such as `M005` or `A312`, a map card
appears under it: a drawing of the GIU campus (traced from an aerial map: A top-left,
S below A next to the road, M on the right) with the building highlighted, the floor
marked, step-by-step directions from the car park, and a Google Maps link to the
campus. The rooms are found by code (`backend/app/campus.py`), not by the language
model, and only codes that follow the numbering rules are shown. The layout in
`frontend/src/components/CampusMap.jsx` matches the "Campus Layout and Directions"
section of `campus_buildings.md`; keep the two in sync.

**Rooms and places:** a room code in a question (e.g. "Which floor is A107 on?",
"a 305", "فين أوضة S214؟") adds its building and floor, worked out from the numbering
rules in `backend/app/campus.py`, so any valid room can be answered, also rooms that
are not listed in the documents. Places outside the buildings (supermarket, gym, padel,
food court, football, tennis and basketball courts) are described in
`campus_buildings.md`; when an answer names one, it gets a "🚶 Walk me to …" Google
Maps button (positions in `frontend/src/campusGeo.js`).

**English words in Arabic letters:** questions like "فين بسكت بال؟" (basketball),
"فين بدل؟" (padel) or "فين الكلينيك؟" (clinic) are understood through a small glossary
in `backend/app/rag/transliteration.py`. Words are compared by their consonants
(vowel letters ا و ي and "ال" ignored), so spellings like بادل / بدل / باديل all match.
Words that are also everyday Arabic ("بدل" = instead of, "تنسى" = forget) only count
when the question is about a place ("فين بدل؟", "ملعب بدل"). Egyptian question words are
translated too, so "فين بسكت بال" is also searched as "where is basketball", and the
best match of both searches is kept. Add new words to `GLOSSARY` when needed.

**Walking directions:** the map card has a "🚶 Walk me to Building …" button that opens
Google Maps walking navigation from the user's location to the building's entrance.
The real GPS positions of the entrances (M: 2, A: 3, S: 1) are in
`frontend/src/campusGeo.js`; no API key is needed.

**Links to the other agents:** the GIU chatbot has four agents (Graduation & Advising,
HR & Policies, Internship & Career, Labs & Research). When an agent has no answer, the
question is compared with each agent's description (`backend/app/agents/directory.py`,
embeddings only, no chat model call) and the fallback message gets a button to the
best-matching agent. Students can be sent to Graduation & Advising, Internship & Career and Labs &
Research; staff to all four. An agent the user may not use (HR, for a student) is named without a button. Nothing is suggested when no agent matches
(`AGENT_LINK_MIN_GAP` in `config.py`: the best agent must clearly beat the second best). Agents that are not built yet open a
"coming soon" page (`/?agent=<key>`, `frontend/src/components/ComingSoon.jsx`); built
ones open directly. A question that only weakly matches an agent's documents (best score
below `HANDOVER_MAX_SCORE`) but clearly belongs to another built agent
(`HANDOVER_MIN_GAP`) is handed over: e.g. "How do I apply for an internship?" asked to
Labs & Research gets a button to the Internship & Career agent.

**Voice call:** the 📞 Call button (Edge and Chrome) opens a hands-free call: the
assistant greets you, records you until you pause, turns the recording into text,
sends it as a normal chat question, reads the answer aloud and listens again, until
you hang up. **Arabic, English or a mix are detected automatically**: the recording
goes to `POST /transcribe` (`backend/app/speech.py`), which uses **Groq's hosted
Whisper large-v3-turbo** when `GROQ_API_KEY` is set in `.env` (free key at
https://console.groq.com; under a second, best Arabic; free tier of about 2,000
requests a day, the recording is sent to Groq). Without a key, or when Groq is
unreachable or over its limit, it falls back to **local Whisper** (faster-whisper,
free, offline; `WHISPER_MODEL` in `config.py`: `base` ~3 s per question on a 4-thread
CPU, `small` better Arabic but ~12 s there; downloaded once on the first start).
Answers are read with an Arabic or English browser voice depending on their
text. Tap the circle to interrupt. Code: `frontend/src/components/CallScreen.jsx`.

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

## Admin page

**http://localhost:5173/admin** lists the documents the agents answer from (`backend/data/raw/<agent>/`,
`.md` and `.txt`), with a filter per agent. An admin can **add** a document (pick a file or paste
Markdown; start each topic with a `## Heading`), **edit** it, **move** it to another agent and
**delete** it. Every change is re-indexed at once (`app/routers/admin.py` uses `ingest_file` from
`scripts/ingest.py`), so the agents answer from the new text right away; the message shows the
number of chunks.

Login: put `ADMIN_PASSWORD=...` in `backend/.env` and set `LOGIN_REQUIRED = true` in
`frontend/src/admin/AdminPage.jsx`; a login then lasts 8 hours (`ADMIN_TOKEN_HOURS`), and a wrong
password waits 1 second. Without a password the admin routes are open (the backend logs a
warning at start-up): fine on your own computer, never on a server. File names are cleaned (no
folders, only `.md` / `.txt`), and document ids cannot point outside `data/raw/<agent>/`.

## Document editor

Users attach a **.docx, .xlsx, .pptx, .pdf, .txt or .md** file (up to 10 MB) and say what to
change: *"correct the grammar"*, *"make it more professional"*, *"translate it to Arabic"*,
*"shorten section 2"*, *"add my new internship at Valeo"*, *"fill in the form with: name Sara,
ID 123"*, *"convert this PDF to Word"*. **`/chat` decides automatically** (no switch): a request
to change something (`is_edit_request` in `editor.py`: rewrite, fix, translate, restructure,
make..., also Egyptian Arabic) is edited; a question about the file (*"what does it say about
...?"*, *"Analyze my CV"*, *"review it"*) is answered as before. The answer says what changed
(with a "Show changes" list) and has **View** (opens it in the browser; Word, PowerPoint and Excel
as a simple HTML page) and **Download** buttons. A bar above the message box shows the open
document: later edit requests (*"now make it shorter"*) change it without uploading it again,
questions are still answered normally; **Close** forgets it.

**CVs in the Internship & Career agent:** *"restructure my CV"* / *"send me this cv restructured"*
with a CV attached still goes to the fine-tuned CV model (`giu-cv`, v6). It answers with the CV,
then a **CV ANALYSIS** (rating, what it changed, what to improve; "تحليل الـ CV" in Arabic). The
CV becomes a **PDF** (View / Download) and an editable **Word** file (`app/documents/cv_file.py`);
the analysis is the chat message. The checks against the original CV (invented links, dates and
numbers, GIU written into another university's CV) run on the CV part only. The analysis is then
checked against that CV (`app/documents/cv_analysis.py`): strengths it does not support (profile
links, skill levels, measurable results) are removed, advice it does not need is removed ("Add
2-3 bullets ..." when no role lacks details, "Add more skills ..." with 6 or more skills, "Say in
your summary which role ..." when the summary says it, "Keep personal details and hobbies out ..."
unless "What I changed" says some were removed), the Summary, Skills and Experience lines
of "Section by section" are corrected to match the CV ("no internship or job yet"), a
missing LinkedIn link and, with no job yet, a first internship or part-time job are added to "Most
important to improve", and the rating is computed in code from a fixed rubric (phone, links,
summary, target role, education dates, experience, numbers, projects, skills, languages, extra
sections). For a 1-page target the PDF may use slightly tighter spacing (text stays at least
10pt); a section heading always stays with its content. The PDF is
ATS-friendly (selectable text, one column, standard headings, no tables or pictures; body 10.5pt,
headings 13pt, as many pages as the content needs). Arabic CVs come back in Arabic and are laid out
right to left, in Tahoma when the system has it (its text reads back correctly), otherwise in
MuPDF's built-in Arabic font. Later
edit requests change the Word version and come back as a new PDF and Word file. A file whose name
contains cv / resume counts as a CV ("fix this" + cv1.docx). Only CV rewrites use the CV model
(CAREER_MODEL); other Career questions use the normal models, since the CV model was trained only
to restructure attached CVs.

**PDF versions:** "send it as pdf", "convert it to pdf", "حوله بي دي اف" return a PDF of the attached or
open document without asking a model: a restructured CV in its CV layout, other files as a simple
PDF (text, headings, lists, tables; the original Word / PowerPoint / Excel layout is not kept).
"Translate it and send it as pdf" edits the file and adds a PDF of the result.

How it works (`backend/app/documents/`, `app/routers/chat.py`, `app/routers/documents.py`):

1. The file is checked: extension **and** content (a real Word/Excel/PowerPoint zip, a real PDF,
   UTF-8 text), size, password protection, damage.
2. It is split into numbered parts: paragraphs (also in tables, headers and footers), slide texts,
   spreadsheet cells, PDF lines or text blocks.
3. The model (`DOC_EDIT_MODEL`, default: the Labs models) gets the instruction and the parts, in
   batches of about 6,000 characters for long documents, and answers **only with JSON edits**
   (replace / insert after / delete a part). It never runs code or touches files. Unknown ids
   are ignored; it is asked again once if its answer is not usable.
4. The edits are applied to exactly those parts in the original file, so styles, fonts, tables,
   pictures, headers, numbering, layout, formulas and slide layouts stay as they were. The new
   file is opened once more to make sure it is valid, then offered for download.

Per format:

| Format | What is edited | Limits |
|---|---|---|
| .docx | paragraphs, table cells, headers, footers | a changed paragraph takes the font of its first run |
| .xlsx | text and number cells, empty cells | formulas are never changed; no new rows/columns; charts and pictures are not kept (openpyxl) |
| .pptx | all text in placeholders, text boxes, groups, tables | speaker notes are not edited |
| .pdf | lines are replaced in place (same position, size, colour; Helvetica) | no new lines and no Arabic inside a PDF: ask to **convert it to Word** |
| scanned .pdf | read page by page by the vision model (no OCR program needed), saved as .docx | first 5 pages |
| .txt / .md | blocks between blank lines; Markdown is kept | |

Files are stored under random names in `backend/data/edits/<conversation>/` (not in git),
at most 5 versions, and deleted after 60 minutes (`DOC_EDIT_KEEP_MINUTES`) or on **Close**.
View and Download need the random 32-character token from the answer; follow-up edits and Close
need the token of the latest version, so nobody can open or change another chat's document by
guessing a conversation number. The View page is sent with a strict Content-Security-Policy and
all text is escaped. Document contents are never logged.

Tests (no model, network or database needed; the model is replaced by a stand-in):

```bash
cd backend
python -m unittest discover -s tests -v
```

To try each format by hand: start a chat with any assistant, attach a file and write e.g.
*Word*: "correct the spelling", *Excel*: "translate the item names to
Arabic and set B3 to 30", *PowerPoint*: "fix the typos and add a step: Evaluate the model",
*PDF*: "fix the spelling" (stays a PDF) or "convert to Word and translate to Arabic",
*Markdown*: "add a Next steps section", *CV* (Internship & Career): "restructure my CV".

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

The 61 included questions (17 Labs & Research, 8 Internship & Career, 36 Graduation &
Advising) are placeholders based on the documents. Three of them (the AI lab's phone number, renewing a
passport, a paid internship semester) ask for information that is not in the documents
and expect `don't have`, to check the agents do not invent answers. Questions for an
agent the chosen user type may not use (Career for staff) are skipped.

## Settings

All settings are in `backend/app/config.py`:

| Setting | Default | Meaning |
|---|---|---|
| `TOP_K` | 4 | chunks returned by the retriever |
| `SIMILARITY_THRESHOLD` | 0.48 | chunks below this score are ignored; if none pass, the fallback message is returned |
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
    speech.py            speech-to-text for the voice call (Groq Whisper, local fallback)
    db.py                PostgreSQL connection
    schemas.py           request/response models
    routers/             session.py, chat.py, feedback.py, speech.py, documents.py (document editor), admin.py (admin page)
    documents/           document editor: formats.py (read/edit/save each format), editor.py (model -> JSON edits), storage.py
    agents/              base.py (shared flow), labs_research.py, internship_career.py, graduation_advising.py, directory.py
    rag/                 embeddings.py, retriever.py, prompts.py, transliteration.py
    llm/client.py        chat completions (OpenRouter or local Ollama)
  tests/
    test_documents.py    document editor tests (python -m unittest discover -s tests)
    test_admin.py        admin route tests
    test_migrate.py      migration runner tests
  migrations/            numbered SQL files (000_base.sql, 001_tenants.sql, ...)
  scripts/
    migrate.py           apply the pending migrations
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
    components/          StartScreen.jsx, Message.jsx, CampusMap.jsx, CallScreen.jsx, ComingSoon.jsx
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
