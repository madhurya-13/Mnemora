# MNEMORA — An AI That Remembers, Learns and Evolves

MNEMORA is a personal assistant designed to gain useful context over time. Milestone 1 established the project scaffold, Milestone 2 added Gemini chat, and Milestone 3 added persistent guest-owned conversations. Milestone 4 adds reviewable long-term memories, relational metadata, Chroma vectors, semantic retrieval, and a memory dashboard. Milestone 5 adds retrieval intelligence, Milestone 6 adds voice mode plus image and audio input, and Milestone 7 adds adaptive memory with reviewable preference learning, memory evolution, decay, patterns, feedback and personalization.

## Objectives and planned capabilities

The planned product includes conversational AI, short and long-term memory, semantic retrieval, voice input/output, memory extraction and categorization, knowledge graph visualization, contradiction detection, personalization and multi-agent orchestration. This repository implements conversational AI, persistent short-term history, the long-term memory pipeline, semantic retrieval, voice/multimodal interaction, and adaptive preference/pattern/feedback learning. Knowledge graphs and advanced orchestration are future milestones.

## Technology and architecture

- **FastAPI, Uvicorn and Pydantic Settings** provide a typed Python API, local ASGI server and environment configuration.
- **SQLAlchemy and Alembic** provide relational persistence and schema migrations; SQLite is the default and PostgreSQL is supported through `DATABASE_URL` and the psycopg driver.
- **Google GenAI SDK** generates asynchronous Gemini chat responses and extracts memory candidates.
- **OpenAI embeddings and persistent ChromaDB** power semantic indexing and retrieval. SQLAlchemy remains authoritative for memory content, approval state, and ownership; Redis is not used by this milestone.
- **Next.js, React, TypeScript and Tailwind CSS** provide the responsive App Router dashboard. **Lucide React** supplies icons.

The browser dashboard calls `GET /api/v1/health` using `NEXT_PUBLIC_API_URL`. FastAPI allows the configured `FRONTEND_URL` origin. Backend settings remain server-side; no API key is put in frontend configuration.

## Folder structure

```text
backend/
  app/
    agents/       memory/       voice/
    api/          database/     models/
    schemas/      services/     utils/
    config.py     main.py
  requirements.txt
  .env.example
frontend/
  app/            components/   hooks/
  lib/            public/
  package.json
  .env.local.example
tests/
  test_health.py
.gitignore
README.md
```

## Prerequisites

- Python 3.11 or newer
- Node.js 20.9 or newer and npm
- VS Code (recommended)

## Environment configuration

Copy `backend/.env.example` to `backend/.env`. Add your Google AI Studio key for chat and extraction. The default embedding provider is OpenAI; you can switch `MEMORY_EMBEDDING_PROVIDER` to `google` to use the existing Google key with Gemini embeddings. Copy `frontend/.env.local.example` to `frontend/.env.local`; it contains only the public API base URL. Real environment files are ignored by Git. Never put secrets in a `NEXT_PUBLIC_` variable because those values are included in browser code.

`MEMORY_AUTO_SAVE=false` is the default: extracted candidates wait for review in the Memory dashboard. `CHROMA_DB_PATH` defaults to `./chroma_db` relative to the backend working directory. OpenAI embeddings are billed by input tokens; the Gemini Embedding free tier is currently listed as free of charge, with usage limits and free-tier data handling described in Google's [pricing documentation](https://ai.google.dev/gemini-api/docs/pricing). Gemini and OpenAI keys stay in the backend environment only. Choose the embedding provider before indexing approved memories; changing provider requires rebuilding the vector index because the embedding spaces are incompatible.

## Run on Windows in VS Code

Open two PowerShell terminals at the project root.

### Backend terminal

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

If PowerShell blocks activation, use `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` for that terminal, then activate again.

### Frontend terminal

```powershell
cd frontend
Copy-Item .env.local.example .env.local
npm install
npm run dev
```

Visit `http://localhost:3000`. The dashboard shows backend/database availability and restores the last open conversation after refresh. To verify separately, visit `http://localhost:8000/`, `http://localhost:8000/api/v1/health` and `http://localhost:8000/docs`. Run `alembic upgrade head` from `backend` after pulling schema changes. Back up an existing database before applying a migration.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Application name, version and running message |
| GET | `/api/v1/health` | Health status consumed by the dashboard |
| GET | `/api/v1/conversations` | List the guest's active or archived conversations (paginated) |
| POST | `/api/v1/conversations` | Create a conversation |
| GET | `/api/v1/conversations/{id}` | Get conversation details and the first message page |
| GET | `/api/v1/conversations/{id}/messages` | Retrieve chronological, paginated messages |
| PATCH | `/api/v1/conversations/{id}` | Rename, archive or restore a conversation |
| DELETE | `/api/v1/conversations/{id}` | Delete a conversation and its messages |
| POST | `/api/v1/chat` | Generate and persist a complete response |
| POST | `/api/v1/chat/stream` | Stream tokens; save assistant response only after completion |
| GET, POST | `/api/v1/memories` | List memories with filters or create a reviewable memory |
| GET, PUT, DELETE | `/api/v1/memories/{id}` | Read, edit, or delete an owned memory |
| POST | `/api/v1/memories/search` | Search approved memories semantically |
| POST | `/api/v1/memories/{id}/approve` | Approve and index a pending memory |
| POST | `/api/v1/memories/{id}/reject` | Reject a pending memory |
| GET | `/api/v1/memories/stats` | Read real memory, category, and sync statistics |
| POST | `/api/v1/memories/extractions/retry` | Retry failed extraction jobs |

The legacy `/api/v1/chat/conversations` routes remain available for compatibility. A random guest token is held in an HttpOnly cookie; the database stores only its SHA-256 hash. Conversation reads and writes are scoped to that guest. The browser stores only the active conversation ID in local storage. Failed model requests retain the user message with `failed` status; partial assistant output is never persisted. Model context is limited by `CHAT_MAX_HISTORY_MESSAGES`.

## Tests

From the repository root, after installing backend dependencies:

```powershell
python -m pip install -r backend/requirements.txt
$env:PYTHONPATH = (Join-Path (Get-Location) "backend")
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest
```

The tests cover health/CORS, guest identity, conversation persistence, memory extraction validation, approvals, CRUD, owner isolation, vector outbox retries, semantic filtering, and chat context integration. Provider calls are mocked. On systems where Windows Application Control blocks Chroma's native `grpcio` extension, the real persistent Chroma test is skipped; this runtime limitation is recorded below.

## GitHub preparation

The project is connected to its GitHub repository. Local `.env` files, SQLite files, and `chroma_db/` are ignored. Keep those data files out of commits.

## Future milestones

1. **Project setup and architecture** — complete.
2. **Conversational AI Engine** — this milestone.
3. **Short-term memory persistence** — durable, guest-owned conversation history (complete).
4. **Long-term semantic memory** — implementation and runtime verification status are documented below.
5. **Voice and knowledge views** — input/output and memory visualization (voice complete).
6. **Adaptive memory and continuous learning** — implemented in Milestone 7.
7. **Personalization and orchestration** — specialized agents and evolving user context.

## Milestone 1 checklist

- [x] Modular backend/frontend folders and environment examples
- [x] FastAPI root and versioned health endpoints with local CORS
- [x] Responsive dark dashboard with real health endpoint status
- [x] Dependency manifests and Git ignore rules
- [x] Beginner-friendly setup and API documentation
- [x] Pytest health/CORS checks (3 passed)
- [x] Production build, ESLint, and live frontend-to-backend connection verified

The frontend production dependency audit is clean. The full dependency tree retains 8 moderate advisories in ESLint's transitive TypeScript parser (`minimatch`); npm's suggested automatic fix would downgrade the Next lint config across a major version, so that was not applied.

## Milestone 2 — Conversational AI Engine

### Architecture

`api/chat.py` validates requests, manages conversation endpoints, and exposes REST and SSE routes. `agents/assistant.py` assembles the configured system prompt, recent conversation context, and current user message. `services/llm_service.py` is the only module that creates or calls the Google GenAI SDK. It uses the official Python SDK's async `generate_content` and `generate_content_stream` methods. The client is initialized lazily; health checks make no Gemini calls. The Milestone 4 worker may retry persisted extraction jobs at startup. [Google GenAI SDK documentation](https://googleapis.github.io/python-genai/)

The browser never receives the API key. It calls the FastAPI service using `NEXT_PUBLIC_API_URL`; only the backend reads `GOOGLE_API_KEY`.

### Gemini configuration

Set these values in the ignored `backend/.env` file:

```dotenv
GOOGLE_API_KEY=your_google_ai_studio_key
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_TEMPERATURE=0.7
GEMINI_MAX_TOKENS=2048
GEMINI_TIMEOUT_SECONDS=60
CHAT_MAX_HISTORY_MESSAGES=20
CHAT_MAX_MESSAGE_LENGTH=8000
```

Create a key in [Google AI Studio](https://aistudio.google.com/apikey). Gemini offers a free tier with limited model access and usage quotas; availability and limits can change. [Current Gemini API pricing and free-tier details](https://ai.google.dev/gemini-api/docs/pricing). Google states that free-tier submitted content may be used to improve its products, so avoid sending sensitive personal information on that tier. The system prompt is defined in `backend/app/utils/prompts.py` and can be overridden with `MNEMORA_SYSTEM_PROMPT`. Restart the backend after changing environment values. A missing key produces a clear configuration message; the application still starts normally.

### Conversation persistence and limitations

Conversations and messages are stored in SQLAlchemy tables and migrated with Alembic. SQLite is the default; set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL to use PostgreSQL. Each browser receives an opaque guest session cookie, and all conversation operations enforce ownership in the backend. Conversations can be listed, opened, renamed, archived/restored, and deleted. The frontend fetches history from the API and restores the active conversation after refresh.

This is short-term conversational history, not long-term semantic memory. There are no user accounts or cross-device guest history, and Redis/ChromaDB are not used in this milestone. Do not delete the SQLite database if you want to keep its conversations. Before changing database schema in a later release, back up the database and apply Alembic migrations.

### Chat endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/chat/health` | Reports configured model and whether an API key is set; makes no model call |
| POST | `/api/v1/chat` | Generate one complete response |
| POST | `/api/v1/chat/stream` | Stream a response as Server-Sent Events |

Example non-streaming request:

```json
{"conversation_id":"conv_example","message":"Explain how neural networks work"}
```

The stream sends `conversation`, `token`, then `done` events. If generation fails it sends an `error` event with a safe message and retry guidance. The user message is committed before generation. The assistant message is committed only after a complete stream; if generation fails or is interrupted, the user message is marked failed and partial assistant text is not stored.

### Frontend integration

`frontend/lib/api.ts` centralizes the backend URL and HTTP errors. `frontend/lib/chat.ts` owns typed conversation requests and parses SSE frames across network chunk boundaries. The chat UI uses reusable sidebar, message, input, typing, and welcome components. Markdown is rendered with `react-markdown` and `remark-gfm`; raw HTML is not enabled. The right details panel displays the configured model and actual backend/chat health state, not simulated metrics.

### Run and test the chatbot

Follow the Windows setup commands above. Set a real API key in `backend/.env`, start the backend and frontend, open `http://localhost:3000`, and send a suggested prompt or your own message. Try “My name is Alex” followed by “What is my name?” in one conversation, then ask the same question in a new conversation to confirm their histories are independent. Use the sidebar controls to rename, archive, switch, restore, and delete conversations. Refresh the browser and restart the backend to confirm that history persists.

Automated tests mock all model calls and require no Gemini API usage. From the repository root:

```powershell
python -m pip install -r backend/requirements.txt
$env:PYTHONPATH = (Join-Path (Get-Location) "backend")
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest
```

To inspect the health state without sending a prompt, open `http://localhost:8000/api/v1/chat/health`. Tests mock Gemini calls, and health checks do not call Gemini. The Milestone 4 worker may retry persisted extraction jobs at startup.

## Milestone 3 — Short-Term Memory Persistence

- [x] SQLAlchemy user, conversation and message models with ownership and cascade constraints
- [x] Alembic initial migration and SQLite foreign-key enforcement
- [x] Opaque guest sessions with HttpOnly cookies and hashed session identifiers
- [x] Owner-scoped conversation listing, paging, rename, archive/restore and delete APIs
- [x] Persist user messages before generation and completed assistant messages after success
- [x] Mark failed turns and avoid saving partial stream output
- [x] Bounded chronological model context and browser history restoration
- [x] Automated persistence, ownership, pagination and streaming tests
- [x] Setup, migration and API documentation

## Milestone 4 — Long-Term Semantic Memory Engine

### Architecture and approval

Conversation history remains the complete source of what was said. After a successful chat turn, a durable SQL extraction job passes only the user's message to the existing Gemini service. The extractor requests validated JSON, accepts only explicit and useful facts, limits candidates, rejects sensitive information, and ignores greetings. It does not store every message. Source conversation and user-message IDs are retained for traceability.

Manual approval is the default (`MEMORY_AUTO_SAVE=false`). Candidates appear as pending memories and are never retrieved for chat. Approving a candidate generates an embedding, writes approved metadata to SQL, and places vector work in a durable outbox. Automatic saving requires the setting to be enabled plus a direct, high-confidence, sufficiently important, non-sensitive fact and an available embedding key. Duplicate candidates are compared semantically against the current user's approved vectors; likely duplicates await review, and approval merges source references into the existing record while preserving its creation time.

### Storage, embeddings and retrieval

The `memories` SQL table is the authoritative source for ownership, content, category, importance, confidence, approval state, source IDs, and timestamps. `memory_vector_outbox` records idempotent Chroma upsert/delete work, and `memory_extraction_jobs` persists post-response extraction and retries. The Chroma collection is named `mnemora_user_memories`; it stores approved vectors only, uses deterministic memory UUIDs, and applies `user_id` metadata filtering. Search also checks SQL ownership and approved/synced status before returning results.

OpenAI's `text-embedding-3-small` is the default for both indexing and queries. `MEMORY_EMBEDDING_PROVIDER=google` selects Google's `gemini-embedding-001`; document and query tasks use matched retrieval task types, and vectors are normalized to the configured size. Gemini remains the existing chat and extraction provider. Retrieved memories are inserted in a distinct, bounded system-prompt context block with explicit guidance that memories are informational and do not override system instructions. Retrieval failure falls back to the normal conversation context; memory extraction runs after the response and cannot fail the chat request. Failed extraction and vector operations remain visible in SQL for retry/reconciliation.

### Dashboard and API

Open **Memory** from the chat sidebar. The dashboard shows database-backed totals, categories, recent activity, approval status, and index sync status. It supports category/status filters, semantic search, memory creation, view/edit, approve/reject, and delete. Deleting an indexed memory removes its relational row and queues vector cleanup; the UI reports if cleanup needs retry. Embedding vectors are never returned by the API.

All memory endpoints are under `/api/v1/memories`; see the API table above or `/docs`. The `stats` response indicates whether semantic search is configured without exposing the API key. `POST /api/v1/memories/extractions/retry` retries failed extraction jobs for the current guest.

### Configuration and commands

In the ignored `backend/.env`, configure:

```dotenv
GOOGLE_API_KEY=...
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
MEMORY_EMBEDDING_PROVIDER=openai
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
GEMINI_EMBEDDING_DIMENSIONS=768
DATABASE_URL=sqlite:///./memory_agent.db
CHROMA_DB_PATH=./chroma_db
MEMORY_AUTO_SAVE=false
MEMORY_TOP_K=5
MEMORY_SIMILARITY_THRESHOLD=0.85
MEMORY_MIN_IMPORTANCE=0.5
MEMORY_MIN_RELEVANCE=0.25
MEMORY_MAX_CONTEXT_ITEMS=5
```

From the backend directory, install dependencies and apply the additive migration before starting the server:

```powershell
python -m pip install -r requirements.txt
alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The migrations add memory, background-operation, conflict, history and retrieval-audit tables; they do not replace or delete existing conversation data. Back up an existing SQLite database before schema changes. Conversation extraction uses Gemini. OpenAI embeddings may incur API usage charges; Google's Gemini Embedding free tier is available subject to its current usage limits and data handling terms. Automated tests mock both providers and do not use credits.

### Milestone 5 retrieval benchmark

Run the deterministic synthetic ranking benchmark from the repository root with `PYTHONPATH=backend python scripts/retrieval_benchmark.py` (PowerShell: `$env:PYTHONPATH="backend"; python scripts/retrieval_benchmark.py`). It fuses labeled SQL and semantic candidate orderings with the production reciprocal-rank-fusion implementation. Current results: **Recall@3 1.00, MRR 0.80 (5 cases)**. This small fixture checks fusion behavior only; it is not a production relevance evaluation and makes no provider calls.

### Manual verification

1. In chat, state a useful preference or project fact, such as “I am building a Python study planner and prefer examples.”
2. Open Memory and approve the extracted pending candidate.
3. Confirm it is marked approved and indexed, then use semantic search with a differently worded query.
4. Start a new conversation and ask a related question; only approved, relevant memories should inform the reply.
5. Restart the backend, refresh the browser, and confirm the memory and conversation remain available.
6. Delete the memory and confirm it no longer appears in list or semantic search.

To inspect the local vector count from `backend`, run `python -c "import chromadb; c=chromadb.PersistentClient(path='./chroma_db'); print(c.get_collection('mnemora_user_memories').count())"`. To inspect relational memory approval counts, run `python -c "import sqlite3; c=sqlite3.connect('./memory_agent.db'); print(c.execute('SELECT approval_status, COUNT(*) FROM memories GROUP BY approval_status').fetchall())"`.

### Runtime limitation in this workspace

On this Windows host, the OpenAI API currently returns `credit_balance_exhausted` for embedding requests. Chroma's persistent client works, and the embedding provider can be switched to Google's Gemini free tier with `MEMORY_EMBEDDING_PROVIDER=google`. The dashboard reports embedding and vector-index availability separately. A transient Chroma startup failure is retried on subsequent health checks rather than cached for the lifetime of the backend process.

## Milestone 6 - Voice and Multimodal Interaction

Milestone 6 extends the existing chat and memory pipeline without creating a separate assistant:

- Microphone recordings and uploaded audio are validated and transcribed through `POST /api/v1/voice/transcribe` or `POST /api/v1/voice/transcribe-upload`.
- Assistant messages can be converted to browser-playable audio through `POST /api/v1/voice/speak`.
- Speech uses OpenAI when `OPENAI_API_KEY` is configured and automatically falls back to Google Gemini when OpenAI is unavailable, out of credits, or not configured. The fallback uses `GEMINI_STT_MODEL` for transcription and `GEMINI_TTS_MODEL` for speech, and returns WAV audio when Gemini is the active provider.
- Images are validated in memory and analyzed through `POST /api/v1/chat/{conversation_id}/message-with-image`; the resulting visual context is sent through normal retrieval, response persistence, and memory extraction.
- Voice mode uses the same conversation endpoint and stores transcript text, never raw audio by default.
- Voice preferences and configured limits are available at `GET`/`PUT /api/v1/voice/settings`.

Configure these backend variables in the ignored `backend/.env`:

```dotenv
OPENAI_API_KEY=...
OPENAI_STT_MODEL=whisper-1
OPENAI_TTS_MODEL=tts-1
OPENAI_TTS_VOICE=alloy
OPENAI_VISION_MODEL=gpt-4o-mini
GEMINI_STT_MODEL=gemini-3.5-flash-lite
GEMINI_TTS_MODEL=gemini-3.8-flash-tts
GEMINI_TTS_VOICE=Kore
MAX_AUDIO_UPLOAD_MB=20
MAX_IMAGE_UPLOAD_MB=10
VOICE_ENABLED=true
TTS_ENABLED=true
IMAGE_INPUT_ENABLED=true
STORE_RAW_AUDIO=false
STORE_UPLOADED_IMAGES=false
```

No additional dependency is required beyond `backend/requirements.txt`; the OpenAI SDK is used server-side and credentials are never sent to the browser. Run `alembic upgrade head` only when migrations are pending; this milestone does not add a database migration.

### Using the multimodal UI

1. Start the backend and frontend using the commands above.
2. Use the microphone button in the composer, stop the recording, and edit the transcript before sending.
3. Use the audio attachment button to transcribe an existing supported audio file.
4. Use the image attachment button or drop an image into the composer, review the preview, and send it with a question.
5. Open **Voice Mode** for speak/transcribe/respond/speak turns. Disable continuous listening or mute playback when needed.
6. Use **Listen** on any assistant response for explicit text-to-speech playback; ordinary text chat does not autoplay audio.

### Troubleshooting and verification

- Microphone access requires a browser permission and a secure context (`localhost` is supported). Denied permission is shown in the composer or voice modal.
- Audio is limited to 20 MB by default and images to 10 MB. Validation checks file signatures, not just extensions.
- Voice Mode ignores recordings and in-flight replies after the modal is closed. Toggle **Mute** to skip spoken replies, and use **Replay** if the browser blocks autoplay.
- If chat works but voice or images do not, verify `OPENAI_API_KEY`, `GOOGLE_API_KEY`, feature flags, and the backend logs. Speech and vision automatically use Gemini when OpenAI is unavailable, so a working `GOOGLE_API_KEY` is enough for voice.
- Swagger is available at `http://localhost:8000/docs`. Run backend tests from the repository root with:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "backend")
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest
Set-Location frontend
npm run lint
npm run build
```

The automated suite mocks provider calls. Manual acceptance should cover text chat, microphone permission and transcription, voice mode, TTS play/pause/stop, audio upload, image understanding, memory-aware voice/image turns, ownership isolation, and invalid/oversized/corrupted uploads.

## Milestone 7 - Adaptive Memory and Continuous Learning

Milestone 7 extends the existing memory engine instead of adding a separate learner. Adaptive analysis runs after a completed chat turn through a durable job, so normal chat is never blocked by it.

### Architecture

- `backend/app/services/adaptive_memory/preference_learner.py` converts repeated, explicit style/technology signals into reviewable preference candidates. A single message can never confirm a preference, sensitive text is ignored, and context-scoped requests such as "for this project" do not overwrite global preferences.
- `memory_evolution.py` classifies content changes (`preference_modification`, `goal_modification`, `project_status_change`, `outdated_information`, `confirmed_replacement`, ...) while preserving the previous content in `memory_history`.
- `memory_decay.py` computes a documented 0..1 utility score (importance 0.25, confidence 0.20, usage 0.20, recency 0.15, feedback 0.10, explicit approval 0.10, minus a capped 0.20 outdated penalty). It only moves memories between lifecycle states; it never deletes them.
- `pattern_detector.py` requires repeated observations across at least two distinct conversations and keeps candidates reviewable.
- `feedback_processor.py` stores immutable feedback events, applies conservative confidence/importance changes, and links response feedback to the most recent retrieval event when memory IDs are omitted.
- `personalization_engine.py` selects only confirmed preferences that are relevant to the current query and returns a token-limited context block. General-knowledge questions and disabled personalization receive no preference context.
- `workflow.py` claims durable `adaptive_processing_jobs` idempotently, retries bounded failures, and is processed after chat plus by a periodic worker.

Lifecycle states are `active`, `possibly_outdated`, `superseded`, `expired`, `archived` and `pending_review`. Only `active` approved memories are retrieved. Archived memories remain visible and can be restored from the dashboard.

### Database migration and backup

Milestone 7 adds migration `0004_adaptive_memory` and the tables `adaptive_settings`, `user_preferences`, `memory_patterns`, `memory_feedback`, `adaptive_processing_jobs`. Back up the development database before upgrading:

```powershell
Set-Location backend
Copy-Item memory_agent.db "memory_agent.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss').db"
$env:PYTHONPATH = (Get-Location).Path
python -m alembic upgrade head
```

Existing memories, conversations and messages are preserved. To test a migration on a copy first:

```powershell
Copy-Item memory_agent.db memory_agent.migration-test.db
$env:DATABASE_URL = "sqlite:///./memory_agent.migration-test.db"
python -m alembic upgrade head
$env:DATABASE_URL = "sqlite:///./memory_agent.db"
Remove-Item memory_agent.migration-test.db
```

### Adaptive configuration

Optional backend variables (defaults shown) can be added to `backend/.env`:

```dotenv
ADAPTIVE_PROCESSING_ENABLED=true
ADAPTIVE_JOB_MAX_ATTEMPTS=5
ADAPTIVE_PREFERENCE_CONFIDENCE_THRESHOLD=0.6
ADAPTIVE_PREFERENCE_EVIDENCE_THRESHOLD=3
ADAPTIVE_PATTERN_EVIDENCE_THRESHOLD=2
ADAPTIVE_OUTDATED_UTILITY_THRESHOLD=0.2
ADAPTIVE_OUTDATED_AGE_MULTIPLIER=2.0
ADAPTIVE_MAX_PREFERENCES_IN_CONTEXT=3
ADAPTIVE_MAX_PATTERN_MESSAGES=120
ADAPTIVE_FEEDBACK_CONTEXT_WINDOW_MINUTES=30
ADAPTIVE_JOB_INTERVAL_SECONDS=60
```

No new Python or Node dependencies are required.

### Adaptive API

All routes require the existing guest/user identity and only return rows owned by that user:

- `GET/POST /api/v1/memories/preferences`, `POST /api/v1/memories/preferences/{id}/confirm`, `PUT/DELETE /api/v1/memories/preferences/{id}`, `POST /api/v1/memories/preferences/{id}/reject`
- `GET /api/v1/memories/evolution`
- `GET /api/v1/memories/patterns`, `POST /api/v1/memories/patterns/{id}/confirm`, `POST /api/v1/memories/patterns/{id}/dismiss`
- `POST/GET /api/v1/memories/feedback`, `GET /api/v1/memories/feedback/insights`
- `GET /api/v1/memories/health`
- `GET/PUT /api/v1/memories/adaptive-settings`
- `GET /api/v1/memories/adaptive/status`, `POST /api/v1/memories/adaptive/process`
- `POST /api/v1/memories/{id}/lifecycle`

`POST /api/v1/memories/adaptive/process` is a manual, owner-scoped "run now" action for verification and recovery. The background worker normally does this automatically.

### Using the adaptive dashboard

1. Open `http://localhost:3001/memory` after starting both servers.
2. Use **Learned preferences** to inspect evidence, confirm, edit, reject, disable or delete a preference.
3. Use **Memory health**, **Memory evolution**, **Detected patterns** and **Feedback insights** to inspect real database values.
4. Use **Adaptive settings** to disable preference learning, pattern detection, personalization or decay per user.
5. Thumbs-up/thumbs-down buttons under assistant replies record response feedback. Feedback never rewrites the response or blindly deletes a memory.

### Evaluation

Run the reproducible synthetic evaluation (no provider calls, temporary database):

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "backend")
python scripts/adaptive_evaluation.py
```

Recorded results from the current implementation:

- Preference detection: precision 1.00, recall 1.00, false preference rate 0.00 over 9 utterances.
- Outdated-memory handling: accuracy 1.00 over 5 cases; all records preserved.
- Conflict detection: accuracy 1.00 over 4 labelled pairs.
- Personalization relevance: adaptive exact-match 1.00 vs baseline 0.25 over 4 queries; 0 irrelevant preferences selected.
- Feedback processing: 5/5 checks passed.
- In-process latency (local SQLite, synthetic data): baseline keyword scan ~0.008 ms, adaptive preference selection ~0.63 ms, full per-turn adaptive processing ~16.5 ms average over 10 turns. These are local microbenchmarks, not production latency guarantees.

The dataset is small and deterministic. It demonstrates that the implemented signals behave as documented; it does not prove general-world accuracy.

### Automated tests and limitations

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "backend")
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest
Set-Location frontend
npm run lint
npm run build
```

Known limitations:

- Preference extraction is rule-based and intentionally conservative. It recognizes a documented set of style, language and workflow cues rather than arbitrary free-form preferences.
- Pattern detection uses a small transparent vocabulary plus capitalized terms; it is not a full topic model.
- Decay uses proxy signals and does not re-evaluate a flagged memory automatically. Users can restore a lifecycle state explicitly.
- Personalization is relevance-filtered but still heuristic; explicit current instructions always take precedence.
- Adaptive processing runs in-process. It avoids Redis/Kafka by design, so multiple backend workers are not coordinated beyond database claims.
