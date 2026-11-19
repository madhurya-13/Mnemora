# MNEMORA — An AI That Remembers, Learns and Evolves

MNEMORA is a personal assistant designed to gain useful context over time. Milestone 1 established the project scaffold, Milestone 2 added Gemini chat, and Milestone 3 added persistent guest-owned conversations. Milestone 4 adds reviewable long-term memories, relational metadata, Chroma vectors, semantic retrieval, and a memory dashboard. Milestone 5 adds retrieval intelligence, Milestone 6 adds voice mode plus image and audio input, Milestone 7 adds adaptive memory with reviewable preference learning, memory evolution, decay, patterns, feedback and personalization, Milestone 8 adds a persistent, user-scoped knowledge graph with multi-hop reasoning, temporal facts, visualization and full user control, and Milestone 9 adds bounded agentic automation: deterministic planning, allowlisted tools, single-use approvals, verified outcomes, monitoring, recovery, reusable workflows and an Agent Control Center.

## Objectives and planned capabilities

The planned product includes conversational AI, short and long-term memory, semantic retrieval, voice input/output, memory extraction and categorization, knowledge graph visualization, contradiction detection, personalization and multi-agent orchestration. This repository implements conversational AI, persistent short-term history, the long-term memory pipeline, semantic retrieval, voice/multimodal interaction, adaptive preference/pattern/feedback learning, and a persistent knowledge graph, plus bounded agentic automation. Milestone 9 does not run arbitrary code, shell commands or unrestricted database queries; every agent step is mapped to one allowlisted tool with validated arguments.

## Technology and architecture

- **FastAPI, Uvicorn and Pydantic Settings** provide a typed Python API, local ASGI server and environment configuration.
- **SQLAlchemy and Alembic** provide relational persistence and schema migrations; SQLite is the default and PostgreSQL is supported through `DATABASE_URL` and the psycopg driver.
- **Google GenAI SDK** generates asynchronous Gemini chat responses and extracts memory candidates.
- **OpenAI embeddings and persistent ChromaDB** power semantic indexing and retrieval. SQLAlchemy remains authoritative for memory content, approval state, and ownership; Redis is not used by this milestone.
- **Next.js, React, TypeScript and Tailwind CSS** provide the responsive App Router dashboard. **Lucide React** supplies icons, and **React Flow (`@xyflow/react`)** renders the interactive knowledge graph.
- **Deterministic agent runtime** in `backend/app/agents/` provides planning, tool selection, approvals, verification, recovery, workflows and learning without calling a model. Every tool is registered with a Pydantic input schema, permission level, timeout and retry policy.

The browser dashboard calls `GET /api/v1/health` using `NEXT_PUBLIC_API_URL`. FastAPI allows the configured `FRONTEND_URL` origin. Backend settings remain server-side; no API key is put in frontend configuration.

## Folder structure

```text
backend/
  app/
    agents/       agents/monitoring/   agents/tools/
    knowledge_graph/   memory/
    api/          database/          models/
    retrieval/    schemas/           services/
    voice/        config.py          main.py
  alembic/versions/
  requirements.txt
  .env.example
frontend/
  app/            app/graph/        app/memory/       app/agents/
  components/     components/graph/ components/agents/
  hooks/          lib/              public/
  package.json
  .env.local.example
tests/
  test_agents.py                test_knowledge_graph.py
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
| GET | `/api/v1/graph/health` | Graph feature flag, row counts and sync status |
| GET, POST | `/api/v1/graph/entities` | List or create owned entities |
| GET, PATCH, DELETE | `/api/v1/graph/entities/{id}` | Read details, edit or archive an entity |
| POST | `/api/v1/graph/entities/merge` | Merge a confirmed duplicate (undoable) |
| POST | `/api/v1/graph/entities/merge/{id}/undo` | Restore a merged entity and its relationships |
| GET | `/api/v1/graph/entities/{id}/connections` | Bounded neighbour expansion for the visualizer |
| GET | `/api/v1/graph/entities/{id}/history` | Entity and relationship audit history |
| GET, POST | `/api/v1/graph/relationships` | List or create owned relationships |
| GET, PATCH, DELETE | `/api/v1/graph/relationships/{id}` | Read, correct or archive a relationship |
| GET | `/api/v1/graph/visualization` | Filtered nodes/edges for the graph canvas |
| POST | `/api/v1/graph/search` | Natural-language graph question with paths |
| POST | `/api/v1/graph/traverse` | Bounded multi-hop traversal from one entity |
| GET | `/api/v1/graph/insights` | Statistics computed from stored rows |
| GET | `/api/v1/graph/activity` | Construction and correction history |
| POST | `/api/v1/graph/rebuild` | Idempotent rebuild from stored memories |
| POST | `/api/v1/agents/plan` | Create a deterministic, reviewable plan for an objective |
| GET | `/api/v1/agents/plans` | List owned plans with status filters and pagination |
| GET, PATCH, DELETE | `/api/v1/agents/plans/{id}` | Read, edit or archive an owned plan |
| POST | `/api/v1/agents/plans/{id}/approve` | Approve a plan, optionally answering clarifications |
| POST | `/api/v1/agents/execute` | Create an execution for an approved plan |
| GET | `/api/v1/agents/executions` | List owned executions with persisted progress |
| GET | `/api/v1/agents/executions/{id}` | Read an execution, its tasks and current state |
| POST | `/api/v1/agents/executions/{id}/pause` | Request a pause at the next task boundary |
| POST | `/api/v1/agents/executions/{id}/resume` | Resume a paused or approval-blocked execution |
| POST | `/api/v1/agents/executions/{id}/cancel` | Cancel without deleting completed results |
| GET | `/api/v1/agents/executions/{id}/events` | Read the ordered execution event log |
| GET | `/api/v1/agents/executions/{id}/verification` | Read persisted verification outcomes |
| GET | `/api/v1/agents/executions/{id}/invocations` | Read redacted tool invocations |
| GET | `/api/v1/agents/approvals` | List owned approvals, optionally filtered by status |
| POST | `/api/v1/agents/approvals/{id}/approve` | Approve one action for one exact task |
| POST | `/api/v1/agents/approvals/{id}/reject` | Reject an action; the task is not executed |
| GET | `/api/v1/agents/tools` | List allowlisted tools, schemas and availability |
| GET, POST | `/api/v1/agents/workflows` | List or create owned workflow templates |
| PATCH, DELETE | `/api/v1/agents/workflows/{id}` | Update, archive or delete a user workflow |
| POST | `/api/v1/agents/workflows/{id}/duplicate` | Copy a workflow into an editable template |
| POST | `/api/v1/agents/workflows/{id}/execute` | Create a plan and execution from a workflow |
| GET | `/api/v1/agents/analytics` | Compute activity and verification metrics from stored rows |

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
5. **Voice and knowledge views** — voice/multimodal input complete; knowledge graph view complete in Milestone 8.
6. **Adaptive memory and continuous learning** — implemented in Milestone 7.
7. **Personalization and orchestration** — adaptive personalization complete (Milestone 7); bounded agentic orchestration implemented in Milestone 9.
8. **Persistent knowledge graph and relationship intelligence** — implemented in Milestone 8.

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

## Milestone 8 - Persistent Knowledge Graph and Relationship Intelligence

Milestone 8 adds a relational, user-scoped knowledge graph as an enrichment layer on top of the Milestone 4-7 memory engine. It does not replace memories, retrieval, voice or adaptive learning, and it does not introduce a graph database. SQLite/PostgreSQL rows remain authoritative for every entity, relationship and piece of evidence.

### Architecture

| Layer | Implementation |
| --- | --- |
| Extraction | `backend/app/knowledge_graph/entity_extractor.py` recognises explicit people, projects, technologies, languages, institutions, goals, interests and concepts, including a bounded set of aliases. `relationship_extractor.py` only emits an edge when an explicit verb or connective supports it. |
| Construction | `graph_builder.py` normalises names, resolves identities, validates source/target type pairs and persists entities, relationships, evidence and `GraphSyncRecord` jobs idempotently. `graph_workflow.py` claims durable jobs and retries bounded failures. |
| Identity | `graph_merger.py` merges exact, normalised and alias matches automatically. Fuzzy name similarity (>= 0.80) is only a suggestion; a user-confirmed merge records a snapshot that can be undone. |
| Temporal | `graph_updater.py` supersedes earlier facts only when the language explicitly changes or replaces them. The previous edge becomes `historical` with `valid_until` and `superseded_by`; no history is deleted. |
| Retrieval | `graph_traversal.py` performs bounded breadth-first traversal with node/edge/depth caps. `graph_ranker.py` scores confidence, depth, recency and evidence. `graph_retriever.py` returns a compact, labelled `CONNECTED KNOWLEDGE` block with DIRECT and INFERRED (n-hop) paths. |
| Visualization | `graph_visualizer.py` produces filtered node/edge payloads. `backend/app/api/graph.py` exposes all graph endpoints; the React Flow dashboard lives at `/graph`. |
| Analytics | `graph_insights.py` computes counts, growth, most-connected entities, isolated entities, evidence coverage and sync health from stored rows only. |

Chat never depends on the graph. After a completed turn, `chat_service` queues a `GraphSyncRecord`; `api/chat.py` processes pending graph work after the response. A periodic worker starts with the app and retries failures. Any graph exception is logged and skipped by `memory/retriever.py`, so chat and Milestones 1-7 keep working.

### Extraction and approval lifecycle

The graph has two evidence stages:

1. A chat turn creates `pending_review` entities and relationships. Pending facts are excluded from retrieval and the default visualization.
2. Approving a memory re-syncs its source user message with `approved=True`, attaches the memory ID as evidence and activates matching facts. Manual facts created in the dashboard are user-confirmed and active immediately.

If no explicit verb or connective supports an edge, no edge is stored. The extractor never invents entities, merges uncertain duplicates automatically, or promotes pending facts. `POST /api/v1/graph/rebuild` is idempotent and only re-reads stored memories.

### Storage and migration

Migration `0005_knowledge_graph` adds five tables and does not modify existing rows:

- `graph_entities` - identity, type, aliases, confidence, source memory IDs, status, merge pointer and observation timestamps.
- `graph_relationships` - directed source/target, type, confidence, evidence memory IDs and excerpts, validity window, status and supersession pointer.
- `graph_history` - immutable audit entries for construction, correction, merge and archive actions.
- `graph_merge_records` - merge snapshots and undo state.
- `graph_sync_records` - durable, idempotent construction work with attempt and error tracking.

Indexes and constraints enforce ownership, valid status values, 0..1 confidence and distinct endpoints. Foreign keys cascade only when an entire user is removed.

Back up the database before upgrading, then apply the migration from `backend`:

```powershell
Copy-Item memory_agent.db "memory_agent.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss').db"
$env:PYTHONPATH = (Get-Location).Path
python -m alembic upgrade head
```

### Retrieval and multi-hop reasoning

Graph retrieval is query-focused and additive. It seeds from entities named in the question plus the user hub, traverses only active relationships supported by approved-memory or user-confirmed evidence, and ranks paths before rendering context. Example:

```text
CONNECTED KNOWLEDGE (user-scoped knowledge graph; only approved-memory or user-confirmed facts):
- DIRECT: MNEMORA -BUILT_WITH-> FastAPI (technology) [confidence 0.81; evidence: approved memory]
- INFERRED (2 hops): User -DEVELOPS-> MNEMORA -BUILT_WITH-> Next.js [confidence 0.72]
```

INFERRED means "composed from explicitly stored edges", not a logical or probabilistic invention. `graph_context_max_facts` and `graph_context_max_tokens` bound the block. Milestone 5 ranking and existing memory context are unchanged.

### Visualization and user control

Open **Knowledge Graph** from the chat sidebar or the Memory page, or visit `/graph`.

- Filter by entity type, relationship type, name, depth and isolated entities.
- Toggle historical facts; historical and pending edges are dashed and visually distinct.
- Select a node to inspect type, confidence, aliases, source memories, connections, evidence and change history.
- Select an edge to inspect endpoints, confidence, evidence, validity window and supersession.
- Ask the graph a question to highlight matched entities and ranked paths.
- Highlight a path between any two displayed entities.
- Expand a node one hop, edit entity/relationship metadata, archive entities or relationships, and create manual facts.
- Review possible duplicates, merge explicitly, and undo any merge from **Merge history**.
- **Rebuild** re-derives the graph from stored memories and never deletes memories.

### Graph API

All routes are under `/api/v1/graph`, require the existing guest/user cookie and return only that owner's rows. Pagination is bounded, traversal depth is capped by `GRAPH_MAX_DEPTH`, and node/edge limits are enforced server-side.

- `GET /health`
- `GET|POST /entities`, `GET|PATCH|DELETE /entities/{id}`
- `GET /entities/{id}/connections`, `GET /entities/{id}/history`
- `POST /entities/merge`, `GET /merges`, `POST /entities/merge/{id}/undo`
- `GET|POST /relationships`, `GET|PATCH|DELETE /relationships/{id}`
- `GET /visualization`, `POST /search`, `POST /traverse`
- `GET /insights`, `GET /activity`, `POST /rebuild`

### Configuration

Optional backend variables (defaults shown):

```dotenv
KNOWLEDGE_GRAPH_ENABLED=true
GRAPH_MAX_DEPTH=3
GRAPH_DEFAULT_DEPTH=2
GRAPH_MAX_NODES=150
GRAPH_MAX_EDGES=300
GRAPH_CONTEXT_MAX_FACTS=8
GRAPH_CONTEXT_MAX_TOKENS=400
GRAPH_MIN_CONFIDENCE=0.3
GRAPH_MAX_ALIASES=12
GRAPH_JOB_MAX_ATTEMPTS=5
GRAPH_JOB_INTERVAL_SECONDS=60
GRAPH_MAX_REBUILD_MEMORIES=500
GRAPH_AUTO_ACTIVATE_ON_APPROVAL=true
```

No new backend dependency is required. The graph uses the existing SQLAlchemy, FastAPI and Pydantic stack. The frontend adds `@xyflow/react` (React Flow) to `package.json`; run `npm install` after pulling.

### Phase A-F manual verification in VS Code

**Phase A - setup.** Back up and migrate the database as shown above; start the backend and frontend in separate terminals. Open `/graph` and confirm the health/feature state, empty state or existing nodes, and no console errors.

**Phase B - construction.** In chat, send: "I am developing MNEMORA using FastAPI and Next.js. MNEMORA is an AI assistant with persistent memory." Wait for the response, then open **Memory** and approve the pending memory candidates. Return to `/graph` and confirm entities `User`, `MNEMORA`, `FastAPI`, `Next.js` and `Persistent Memory` with active `DEVELOPS`, `BUILT_WITH` and `HAS_FEATURE` edges.

**Phase C - inspect and filter.** Select each node and edge; verify type, confidence, evidence IDs, temporal fields and audit entries. Filter to `technology`, toggle isolated entities, raise/lower depth, and refresh the page to confirm persistence.

**Phase D - multi-hop retrieval.** Ask the graph "What technologies am I using in MNEMORA?" and confirm matched entities plus direct and inferred paths. In a new chat conversation, ask the same question and confirm only approved facts appear (no pending facts). Toggle `KNOWLEDGE_GRAPH_ENABLED=false`, restart, and confirm normal chat still works without graph context.

**Phase E - control and history.** Create a near-duplicate entity, open the original entity, and confirm the duplicate suggestion requires confirmation. Merge it, verify relationships moved, then undo from **Merge history** and confirm the entity returns. Edit and archive a relationship; toggle historical facts to see archived/historical rows. Delete a throwaway entity and confirm source memories remain.

**Phase F - regression.** Run the backend suite, frontend lint and production build. Confirm `/`, `/memory`, `/graph` build and that Milestones 1-7 flows (chat, approval, retrieval, voice settings, adaptive panels) still work.

Automated tests from the repository root:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "backend")
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest
Set-Location frontend
npm run lint
npm run build
```

The suite currently reports **164 passed**, including 43 agentic-automation tests and 25 knowledge-graph tests. Agent tests cover planning, tool allowlisting, argument validation, sensitive-action approval and rejection, single-use/expiry semantics, bounded retries, timeouts, verification failures, recovery, pause/resume/cancel, restart recovery, workflow CRUD, learning restrictions, owner isolation and prior milestones.

### Troubleshooting

- **`/graph` is empty after a chat turn.** Conversation facts start as pending. Approve the memory candidates on the Memory page; approval activates matching facts. Pending facts are intentionally hidden from retrieval and the default canvas.
- **Expected entities are missing.** Extraction only stores explicit mentions and explicit relationship cues. Rephrase with a clear verb ("I am developing X using Y"), then approve the resulting memory. Use **Rebuild** to re-read existing memories.
- **A relationship disappeared.** It may be archived, historical, pending, or filtered out. Enable **Historical facts**, clear type filters, and inspect the entity history.
- **Traversal returns 422.** `max_depth` is capped by `GRAPH_MAX_DEPTH` (default 3). Lower the request or change the backend setting and restart.
- **Dashboard shows a request error.** Confirm the backend is running at `NEXT_PUBLIC_API_URL`, the migration `0005_knowledge_graph` is applied, and the browser session has not changed (graph rows are owner-scoped).
- **Graph sync is failing.** Check `GET /api/v1/graph/health` and `GET /api/v1/graph/activity`, then use **Rebuild**. Failures never block chat or memory operations.

### Milestone 8 checklist

- [x] Relational, owner-scoped entities and relationships with evidence and confidence
- [x] Additive migration `0005_knowledge_graph` preserving Milestones 1-7 data
- [x] Deterministic extraction with explicit-cue requirement and no invented edges
- [x] Pending-fact isolation and approval-driven activation
- [x] Idempotent, retryable construction with bounded failures
- [x] Temporal history, supersession and immutable audit records
- [x] Conservative deduplication, confirmed merges and undo
- [x] Bounded multi-hop traversal, ranking and labelled reasoning context
- [x] Additive chat integration that cannot break existing retrieval
- [x] Interactive React Flow dashboard with filters, search, paths and controls
- [x] All graph endpoints authenticated, owner-scoped, validated and paginated
- [x] Insights and activity computed from stored rows
- [x] Automated tests for extraction, persistence, dedupe, temporal, retrieval, security and prior milestones

### Known limitations

- Extraction is deterministic and intentionally narrow. It recognises the documented entity and relationship vocabulary plus explicit aliases; unusual phrasings may yield fewer edges rather than guessed ones.
- The graph is single-user scoped. There is no shared/global entity graph or cross-user merge.
- INFERRED paths are compositions of stored edges, not a general logical reasoner. Traversal is bounded by configured depth, nodes and edges.
- SQLite and PostgreSQL are supported through existing SQLAlchemy configuration. No Neo4j or external graph service is used, by design.
- Automatic construction depends on a successful chat turn. Graph retries are in-process and database-claimed, so multiple backend workers are not coordinated beyond that.
- The canvas uses a deterministic radial layout, not a force-directed simulation. Large graphs are truncated by the configured limits and should be narrowed with filters.
- Live chat verification requires a working Gemini key. Graph tests and rebuilds do not call a model.

## Milestone 9 - Agentic Capabilities and Intelligent Automation

Milestone 9 turns MNEMORA into a bounded, memory-aware agent. A user objective becomes a reviewable plan, each task maps to exactly one allowlisted tool, sensitive actions stop for a single-use approval, every outcome is re-checked against persisted data, failures are classified and recovered within limits, and completed verified runs can suggest reusable workflows.

The agent runtime is deterministic and provider-free. It does not need Gemini, LangChain or LangGraph, it never executes shell commands, Python, SQL or free-form tool calls, and it never invents entities, sources, tool output or completed tasks.

### Architecture

| Layer | Implementation |
| --- | --- |
| Orchestration | `backend/app/agents/agent_orchestrator.py` owns the lifecycle: context assembly, plan creation, edit/approve, execution, pause/resume/cancel, analytics and startup recovery. |
| Planning | `task_planner.py` maps an objective to an intent and a bounded sequence of known task types. `tool_selector.py` maps each task type to exactly one registered tool and validates arguments. |
| Execution | `task_executor.py` checks dependencies, timeouts, retries and approvals, then calls the tool in an isolated session. Side-effecting tools are never retried blindly. |
| State | `execution_state.py` defines persisted task/execution statuses and computes progress only from stored rows. `monitoring/` adds events, progress snapshots and invocation logs. |
| Safety | `agent_safety.py` sanitises untrusted text, limits sizes and rejects instruction-like content from documents and retrieved data. `approval_manager.py` binds approvals to a parameter hash, expiry and single use. |
| Verification | `result_verifier.py` re-reads the database or result payload and records `verified`, `partially_verified`, `failed` or `not_verifiable`. |
| Recovery | `failure_recovery.py` classifies errors, decides whether a retry is safe, applies bounded backoff and preserves partial results. |
| Memory | `agent_memory.py` assembles approved memories, preferences, projects, graph facts and prior executions, then proposes only verified learning outcomes. |
| Workflows | `workflow_library.py` stores editable templates built from registered task types and seeds four builtin templates per user. |

The request path is: objective -> intent -> approved memory/preference/graph context -> plan -> plan approval -> task selection -> permission check -> execution -> verification -> final persisted result -> conservative learning. Execution runs synchronously inside the request's threadpool while checking the database pause/cancel flags between tasks. No background job silently resumes a side effect.

### Plans, tasks and states

A plan stores `plan_id`, owner, title, objective, description, tasks, dependencies, priority, complexity, intent, status and timestamps. Each task stores `task_id`, title, description, task type, assigned tool, dependencies, input, expected output, status, approval flag, attempts, result, error and timestamps.

Task statuses: `pending`, `ready`, `awaiting_approval`, `running`, `completed`, `failed`, `skipped`, `cancelled`.

Execution statuses: `created`, `planning`, `awaiting_approval`, `executing`, `paused`, `completed`, `partially_completed`, `failed`, `cancelled`.

Dependencies are enforced before a task starts; dependent tasks never run before prerequisites complete. A plan fails closed when it is invalid, cyclic, over the task limit, or references an unknown/disabled task type.

Progress is defined as **completed tasks ÷ total tasks in the plan, computed from persisted task states**. It is never incremented by the UI, a timer or an estimate.

### Registered tools and permissions

All eleven tools live in `backend/app/agents/tools/` and are registered in `registry.py`. There is no dynamic registration and no free-form invocation.

| Tool | Category | Permission | Default | Behaviour |
| --- | --- | --- | --- | --- |
| `memory_search` | memory | read-only | enabled | Search only this user's approved memories; returns IDs, excerpts and scores. |
| `preference_lookup` | memory | read-only | enabled | Read approved preferences and adaptation settings. |
| `memory_audit` | memory | read-only | enabled | Find possible duplicates and outdated lifecycle states without changing them. |
| `memory_proposal` | memory | sensitive | enabled | Create one `pending` memory candidate; it cannot approve itself. |
| `knowledge_graph_search` | knowledge graph | read-only | enabled | Search owned entities and evidence-backed relationships. |
| `calculator` | utility | read-only | enabled | Bounded arithmetic and date offsets using an AST evaluator, not `eval`. |
| `document_analysis` | document | read-only | enabled | Summarise and compare user-supplied document text treated as untrusted data. |
| `report_generation` | planning | reversible | enabled | Build a structured report from already verified task results. |
| `progress_summary` | planning | read-only | enabled | Summarise persisted plan progress. Registered for explicit planning use; the default planner does not map a task type to it. |
| `project_analysis` | project | read-only | disabled | Read allowlisted repository files. Requires `AGENT_PROJECT_ROOT`; never reads `.env`. |
| `web_research` | research | read-only | disabled | Search a configured provider. Requires `AGENT_WEB_SEARCH_PROVIDER` and an API key. |

Task-type mapping is fixed:

| Task type | Tool |
| --- | --- |
| `retrieve_memory` | `memory_search` |
| `retrieve_preferences` | `preference_lookup` |
| `retrieve_graph` | `knowledge_graph_search` |
| `analyze_memories` | `memory_audit` |
| `analyze_document` | `document_analysis` |
| `analyze_project` | `project_analysis` |
| `research` | `web_research` |
| `calculate` | `calculator` |
| `generate_report` | `report_generation` |
| `propose_memory` | `memory_proposal` |

The planner asks for clarification when an essential detail is missing, for example an objective that mentions a project but no project memory or configured project root can be found. It does not guess.

### Human-in-the-loop approval

- Read-only tools execute when the action is already authorized by ownership and configuration.
- Reversible tools follow `AGENT_AUTO_APPROVE_REVERSIBLE` (default `true`). Set it to `false` to require approval for reports.
- Sensitive tools always require approval, regardless of configuration.
- An approval is bound to one task's exact parameters through a hash, expires after `AGENT_APPROVAL_TTL_MINUTES` (default 30), and can be consumed exactly once. Replaying a consumed approval returns HTTP 409.
- Rejecting an approval records the decision, sets the task to `cancelled`, and prevents execution. The execution finishes as `partially_completed` and preserves earlier results.
- Expired approvals cannot be approved. The execution remains resumable so the user can request a fresh action.
- Approval never auto-resumes at the API level. The UI chains approve -> resume, which keeps the decision explicit and observable.
- Every decision is stored in `agent_approvals` and logged as an execution event. Rejection and expiry do not delete completed work.

### Verification and recovery

Verification depends on the action:

| Action | Verification |
| --- | --- |
| Memory search / preference / graph read | Re-count returned rows and confirm they belong to the owner. |
| Calculator | Recompute the expression and compare the numeric result. |
| Document analysis | Confirm the summary is non-empty and cites the supplied document. |
| Memory proposal | Re-read the `Memory` row and confirm it exists with `pending` status for this user. |
| Report generation | Confirm the report references only tasks that reached verified completion. |
| Project analysis | Confirm findings cite real allowlisted files; recommendations stay labelled. |
| Web research | Confirm every cited URL came from the provider response. |

Recovery classifies each failure, retries only safe read-only operations within `AGENT_MAX_TOOL_RETRIES` plus one attempt, applies `AGENT_RETRY_BACKOFF_SECONDS`, and never retries a side-effecting tool. Timeouts, invalid arguments, disabled tools and unknown task types fail closed. Partial results stay in the database and the final status reports exactly what happened.

On startup, `recover_interrupted_executions()` marks executions left in `created`, `planning` or `executing` as `paused` with an explanatory error and an `execution.recovered` event. It does not re-run any task. The user can inspect the state and resume deliberately.

### Monitoring and learning

- `execution_events` records the ordered lifecycle, including plan creation, task transitions, approvals, verification, pause, resume, cancel and recovery.
- `tool_invocations` records tool name, attempt, success, duration, redacted arguments and a truncated output summary. Secrets are never logged.
- `task_verifications` stores expected result, observed result, status, evidence and timestamp.
- `GET /api/v1/agents/analytics` computes totals, active runs, success rate, verified tasks, pending approvals, tool usage and recent activity from stored rows.
- Learning only considers completed tasks whose verification succeeded. It can suggest one reusable workflow template (`suggested`, awaiting user action) and at most one pending memory candidate. If the run already performed an explicit `memory_proposal`, the learning memory candidate is skipped (`already_captured`). Failed or unverified runs never teach the agent.

### Reusable workflows

Four builtin templates are lazily seeded per user as database rows: **Project Audit Workflow**, **Learning Plan Workflow**, **Research Workflow** and **Memory Review Workflow**. Builtins cannot be deleted; archive them instead. Executing a workflow creates a normal plan in `approved` state, so you can inspect and edit it before running tasks. Sensitive steps still stop for per-action approval.

Users can create, edit, save, duplicate, execute, archive, restore and delete their own workflows. Every step must use a registered task type with validated arguments. Creating a workflow never executes it, and a previous run's output is never reused as a new result.

### Database and migration

Migration `0006_agentic_automation` is additive and creates eight tables plus indexes:

- `agent_plans` - objective, intent, context, priority, complexity, status and timestamps.
- `agent_tasks` - plan order, type, tool, dependencies, input, result, error, attempts and approval flag.
- `agent_executions` - owner, plan, status, progress counters, pause/cancel flags, heartbeat and learning summary.
- `tool_invocations` - tool, attempt, arguments, result summary, error and duration.
- `agent_approvals` - action, tool, parameters, hash, TTL, status, decision note and decision timestamp.
- `execution_events` - ordered, owner-scoped event log.
- `task_verifications` - verification type, expected/observed values, status, evidence and timestamp.
- `workflow_templates` - builtin or user workflow definitions, steps, status, source and usage counters.

Back up the database before upgrading, then apply the migration from `backend`:

```powershell
Copy-Item memory_agent.db "memory_agent.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss').db"
$env:PYTHONPATH = (Get-Location).Path
python -m alembic upgrade head
python -m alembic current
```

`alembic current` should print `0006_agentic_automation (head)`. Existing rows in Milestones 1-8 tables are not modified.

### Configuration

Optional backend variables (defaults shown):

```dotenv
AGENTS_ENABLED=true
AGENT_MAX_TASKS_PER_PLAN=15
AGENT_MAX_EXECUTION_SECONDS=300
AGENT_TOOL_TIMEOUT_SECONDS=10
AGENT_MAX_TOOL_RETRIES=2
AGENT_RETRY_BACKOFF_SECONDS=0.2
AGENT_MAX_CONCURRENT_EXECUTIONS=3
AGENT_RATE_LIMIT_EXECUTIONS_PER_HOUR=40
AGENT_APPROVAL_TTL_MINUTES=30
AGENT_AUTO_APPROVE_REVERSIBLE=true
AGENT_LEARNING_ENABLED=true
AGENT_PATTERN_THRESHOLD=2
AGENT_CONTEXT_MAX_MEMORIES=8
AGENT_CONTEXT_MAX_GRAPH_FACTS=8
AGENT_MAX_DOCUMENT_CHARS=20000
AGENT_MAX_RESULT_CHARS=8000
AGENT_PROJECT_ROOT=
AGENT_PROJECT_MAX_FILE_BYTES=200000
AGENT_WEB_SEARCH_PROVIDER=
AGENT_WEB_SEARCH_API_KEY=
AGENT_WEB_SEARCH_TIMEOUT_SECONDS=15
```

No new backend dependency is required. The agent uses the existing FastAPI, SQLAlchemy, Pydantic and Alembic stack. The frontend uses the existing Next.js, React, TypeScript, Tailwind and Lucide packages; no new npm package is needed.

To enable repository analysis, set `AGENT_PROJECT_ROOT` to an absolute path you are willing to expose read-only (for example the MNEMORA project root). Only known text and source extensions inside that root are readable, path traversal is rejected, and `.env`, key files and binary blobs are excluded. To enable research, set `AGENT_WEB_SEARCH_PROVIDER=tavily` with a Tavily API key. Until then both tools remain visibly disabled with a reason in the UI and in `GET /api/v1/agents/tools`.

### Using the Agent Control Center

Open **Agents** from the chat sidebar or visit `/agents`.

- **Overview** shows executions, active runs, completed/failed counts, pending approvals and recent tasks from the backend.
- **Planner** accepts an objective, optional title, priority and up to three documents. You can create, edit, reorder, approve, execute, pause, resume and cancel plans.
- **Executions** shows pending approvals, live progress, the current task, per-task output, verification results, errors and the event log.
- **Tools & workflows** shows every registered tool with permission, availability, disabled reason and success/failure counts, plus the workflow library with create, duplicate, archive, restore, execute and delete controls.

Approvals display the action, tool, exact parameters, reversibility, impact, expiry and a single **Approve once** button. The UI never marks a task complete before the backend confirms it.

### Phase A-F manual verification in VS Code

The commands below use the project defaults (`http://127.0.0.1:8000` and `http://localhost:3000`). The results recorded after each step are from an actual run of this repository on Windows; live checks used ports `8010` and `3001` only to avoid a local conflict, with the same code and commands.

**Phase A - installation and migration.**

1. Activate the backend virtual environment and install dependencies:

   ```powershell
   cd backend
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

2. Confirm `backend/.env` exists (`Copy-Item .env.example .env` if it does not) and keep `AGENTS_ENABLED=true`. Leave `AGENT_PROJECT_ROOT` and the web-search values empty for the default safe configuration.

3. Back up and migrate the database as shown above, then verify:

   ```powershell
   python -m alembic current
   ```

   Observed: `0006_agentic_automation (head)`; all eight agent tables existed and the pre-migration backup was preserved.

4. Confirm the frontend configuration:

   ```powershell
   cd ..\frontend
   Copy-Item .env.local.example .env.local -ErrorAction SilentlyContinue
   npm install
   ```

   Observed: no new npm package was added, so `npm install` only reconciled the existing lockfile.

**Phase B - start the application.**

1. Backend terminal (from `backend`, with the virtual environment active):

   ```powershell
   python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

2. Frontend terminal (from `frontend`):

   ```powershell
   npm run dev
   ```

3. Open `http://localhost:3000`, `http://localhost:8000/api/v1/health` and `http://localhost:8000/docs`. Then open `http://localhost:3000/agents`.

   Observed: health returned `{"status":"healthy","application":"MNEMORA","version":"1.0.0"}`; Swagger listed the `/api/v1/agents` routes; the Agent Control Center loaded with real (initially zero) data and no browser console errors.

**Phase C - manual functional tests.**

*TEST 1 - simple task planning.* In **Planner**, enter `Create a plan to learn Python fundamentals.` and select **Create plan**. Verify the intent, ordered steps, dependencies and expected outputs, edit nothing or change a title, then approve.

Observed: a valid plan was created and approved; edit, reorder and invalid/cyclic rejection are covered by automated tests.

*TEST 2 - memory-aware planning.* Approve a memory such as "I am learning Python and prefer short daily sessions", then plan `Create a learning plan based on my current skills and learning preferences.` Verify the plan cites approved preferences and ignores unrelated memories.

Observed in automated tests: context assembly returns only owner-approved memories and preferences, and the plan records the retrieved IDs. This specific prompt was not re-run live because the workspace guest had no approved learning memories at verification time.

*TEST 3 - multi-step execution.* Enter `Please calculate 12 * 12 for me.`, approve the plan and select **Execute**. Open **Executions** and confirm the task order, tool activity, outputs and verification.

Observed live: five tasks completed and verified in order (`memory_search`, `preference_lookup`, `knowledge_graph_search`, `calculator`, `report_generation`), progress `100%` with the definition text, calculator result `12 * 12 = 144`, and 13 events, 5 verifications and 5 invocations. The project-audit variant could not run because `project_analysis` is disabled without `AGENT_PROJECT_ROOT`; the UI reported the missing tool instead of pretending to analyse the repository.

*TEST 4 - knowledge graph context.* Ask `Identify the technologies connected to my current project and suggest a suitable improvement.` after approving graph facts. Verify matched entities, real paths and labelled recommendations.

Observed live: `knowledge_graph_search` executed and truthfully returned zero entities for the new guest. Automated tests cover traversal and evidence-filtered retrieval with populated graph rows. No unsupported connection was invented.

*TEST 5 - human approval.* Enter `Remember this: I use FastAPI for MNEMORA.`, approve the plan, execute it, then use the pending approval card.

Observed live: execution stopped at `awaiting_approval` with the exact parameters and 30-minute expiry. Approving once resumed and completed the run, and the resulting memory stayed `pending`. Replaying the same approval returned HTTP 409 (`This approval is already consumed.`). A second run using `Remember this: my favourite editor is Neovim.` was rejected; its task became `cancelled`, the execution became `partially_completed`, and no memory was created.

*TEST 6 - failure recovery.* In a plan, set a task input to an invalid type (for example `{"expression": 123}`) and execute. For a timeout/retry demonstration, rely on the automated timeout and retry tests, which replace a tool with a slow or failing stub.

Observed live: invalid arguments failed closed before invocation with a schema error, the task was not marked complete, and the failure was recorded. Automated tests confirmed bounded read-only retries, timeout recording, no retry for side-effecting tools, and preserved partial results.

*TEST 7 - execution monitoring and cancellation.* Start a multi-step run, watch **Executions**, then select **Cancel**. Resume a paused run when it is safe.

Observed live: progress, current task, events, verification and errors updated from backend rows; cancellation produced `partially_completed` with completed tasks preserved; resuming a cancelled execution returned HTTP 409. Pause/resume is covered by automated tests and by the approval-blocked flow.

*TEST 8 - workflow reuse.* In **Tools & workflows**, create a workflow with one `retrieve_memory` step, duplicate it, edit it, execute it, archive it, restore it and delete the copy. Try the same actions on a builtin.

Observed live: create, duplicate, archive, restore, execute and delete all succeeded. An archived workflow refused execution. Builtin delete returned HTTP 409, and executing the builtin Project Audit returned HTTP 409 naming the unconfigured `project_analysis` tool. Re-executing the Memory Review Workflow created a new plan and new results rather than reusing the previous run.

*TEST 9 - restart recovery.* Start a safe read-only run, stop the backend, start it again, and inspect the execution.

Observed in automated tests (`test_restart_recovery_pauses_without_rerunning_side_effects`): interrupted `created`/`planning`/`executing` runs become `paused`, receive an explanatory error and an `execution.recovered` event, and no task is re-run. A live mid-run restart was not performed because the synchronous executor finishes read-only calculator plans in well under a second; the recovery path was verified against the database instead.

*TEST 10 - security.* Try invalid arguments, an unknown task type, another browser session, a disabled tool and a document containing instructions.

Observed live: an unknown task type returned HTTP 422; cross-user execution, plan and approval access all returned HTTP 404; a rejected approval prevented execution; disabled tools could not be planned. Automated tests also cover tool allowlisting after database tampering, prompt-injection text inside documents, and approval parameter binding.

**Phase D - automated testing.**

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "backend")
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q
Set-Location frontend
npm run lint
npm run build
```

Observed: **164 passed, 0 failed, 0 skipped** in 124.31 seconds, including **43** agentic-automation tests and 25 knowledge-graph tests. `npm run lint` completed with no warnings or errors. `npm run build` succeeded and produced `/`, `/agents`, `/graph` and `/memory`. All Milestones 1-8 regression tests passed.

**Phase E - internal verification.**

Use SQLite from `backend` (or your configured database client) to confirm the UI is not using demo data:

```powershell
python -c "import sqlite3; c=sqlite3.connect('memory_agent.db'); print(c.execute('select status,count(*) from agent_executions group by status').fetchall()); print(c.execute('select tool_name,attempt,success,duration_ms from tool_invocations order by created_at desc limit 10').fetchall()); print(c.execute('select task_id,verification_status,verification_type from task_verifications order by verified_at desc limit 10').fetchall())"
```

Then check the API directly with the same browser session cookie:

- `GET /api/v1/agents/executions` - persisted status, progress, task results, verification and learning summary.
- `GET /api/v1/agents/executions/{id}/events` - ordered lifecycle log.
- `GET /api/v1/agents/executions/{id}/verification` - stored expected/observed values.
- `GET /api/v1/agents/executions/{id}/invocations` - redacted tool attempts and durations.
- `GET /api/v1/agents/approvals?status=pending` - exact parameters and expiry.
- `GET /api/v1/agents/analytics` - totals computed from the same rows.
- `GET /api/v1/agents/tools` - availability and disabled reasons.
- `GET /api/v1/agents/workflows` - template steps and last execution.

Observed live: analytics reported 6 executions, 5 completed, 1 failed, 10 verified tasks and an 83% success rate; the counters matched the persisted rows. The calculator output `144` came from the registered calculator tool and was independently recomputed by the verifier. The UI's execution detail rendered those same backend values. Backend logs showed no secret values and no traceback during successful runs; browser console had no errors.

**Phase F - final acceptance.**

- [x] Task planning works and complex objectives decompose into meaningful steps.
- [x] Memory-aware planning uses only relevant, approved, owner-scoped context.
- [x] Knowledge graph context is retrieved and never invented.
- [x] Tool registry, schemas, allowlisting and disabled-state reporting work.
- [x] Task selection is fixed per task type, not free-form model output.
- [x] Multi-step execution respects dependencies and records every invocation.
- [x] Human approval is required for sensitive actions and bound to exact parameters.
- [x] Rejected actions are not executed; expired and replayed approvals are rejected.
- [x] Execution monitoring, events, progress and verification use persisted state.
- [x] Pause and resume work where implemented; cancellation preserves completed work.
- [x] Failure recovery respects retry bounds and never blindly retries side effects.
- [x] Result verification distinguishes verified, partial, failed and unverifiable outcomes.
- [x] Workflow templates support create, edit, duplicate, execute, archive, restore and delete.
- [x] Execution history persists across requests and application restarts.
- [x] Adaptive memory integration follows the existing approval policy.
- [x] User isolation and security checks pass for executions, plans, approvals and workflows.
- [x] Milestones 1-8 regression tests pass.
- [x] Automated backend tests, frontend lint and frontend build pass.
- [x] No critical errors remain in the verified flows.

### Troubleshooting

- **No tools are available.** Confirm `AGENTS_ENABLED=true`, restart the backend, and open `GET /api/v1/agents/tools`. `project_analysis` and `web_research` are disabled by design until configured.
- **A plan cannot be approved.** It may need clarification answers, contain a cycle, exceed `AGENT_MAX_TASKS_PER_PLAN`, or reference a disabled tool. The response names the reason.
- **Execute returns 409.** The plan is not approved, the execution is already active, or the workflow needs an unconfigured tool. Read the `detail` field.
- **An approval cannot be approved.** It may have expired or already be consumed. Create or resume the action to request a fresh approval; approvals are never reusable.
- **Execution stops at `awaiting_approval`.** That is correct for a sensitive tool. Open **Executions**, inspect the exact parameters, then approve or reject.
- **A run is `partially_completed`.** Some tasks were cancelled, rejected or failed while earlier verified results were kept. Inspect per-task errors and verification rather than assuming success.
- **Progress looks low after a restart.** Interrupted runs are paused intentionally and are not re-run. Resume only after checking the current task; side effects are never repeated automatically.
- **`/agents` shows a request error.** Confirm the backend URL, that migration `0006_agentic_automation` is applied, and that the browser session has not changed (all agent rows are owner-scoped).
- **Project analysis reports missing files.** Set `AGENT_PROJECT_ROOT` to the absolute repository path and restart. Only allowlisted text/source files inside that root are readable.
- **Research is disabled.** Set `AGENT_WEB_SEARCH_PROVIDER` and `AGENT_WEB_SEARCH_API_KEY`, restart, and confirm the provider is reachable. Without them the tool stays disabled and no live search is claimed.

### Known limitations

- Planning is deterministic and intent-driven, not a general open-ended planner. It recognises the documented task types and goals; unusual objectives may produce a conservative plan or a clarification request rather than an elaborate guess.
- Execution is synchronous within the request threadpool. Long plans are bounded by `AGENT_MAX_EXECUTION_SECONDS`; there is no distributed worker queue.
- Independent tasks are executed in dependency order rather than truly in parallel. The dependency graph is enforced, but the runtime does not spawn concurrent task workers.
- `progress_summary` is registered but no task type maps to it; execution progress is exposed through the execution API and UI.
- Pause is cooperative and checked at task boundaries. A tool already running cannot be interrupted mid-call; its timeout bounds the wait.
- Reusable workflows are templates of known task types, not arbitrary scripts. Workflow steps cannot introduce new tools or code.
- Learning suggests at most one workflow and one pending memory per verified run. It does not create recurring automations or auto-approve anything.
- Builtin workflows are seeded per user and cannot be deleted; archive them instead.
- Live verification of `project_analysis` and `web_research` requires their external configuration and was not performed in the default workspace.
- The SQLite deployment is single-host. Multi-worker coordination relies on database flags and is not a fully distributed scheduler.
