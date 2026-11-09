# MNEMORA — An AI That Remembers, Learns and Evolves

MNEMORA is a personal assistant designed to gain useful context over time. Milestone 1 established the project scaffold and health dashboard. Milestone 2 adds a streaming conversational assistant with temporary, per-conversation history. Persistent memory, voice and agent orchestration remain future work.

## Objectives and planned capabilities

The planned product includes conversational AI, short and long-term memory, semantic retrieval, voice input/output, memory extraction and categorization, knowledge graph visualization, contradiction detection, personalization and multi-agent orchestration. These are future milestones; this repository currently provides the foundation only.

## Technology and architecture

- **FastAPI, Uvicorn and Pydantic Settings** provide a typed Python API, local ASGI server and environment configuration.
- **SQLAlchemy** prepares relational persistence; SQLite is the default and the URL can later target PostgreSQL.
- **Google GenAI SDK** generates asynchronous Gemini chat responses and token streams.
- **ChromaDB** is reserved for semantic long-term memory; **Redis** for short-lived state and caching.
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

Copy `backend/.env.example` to `backend/.env` and add your Google AI Studio API key locally to enable chat. Copy `frontend/.env.local.example` to `frontend/.env.local`; it contains only the public API base URL. Both real environment files are ignored by Git. Never put secrets in a `NEXT_PUBLIC_` variable because those values are included in browser code.

The backend reads the Gemini key, model, generation, context-limit, database, Redis, ChromaDB and CORS settings from its `.env` or process environment. It starts without a key, but chat requests remain unavailable until one is configured. Redis and ChromaDB are not contacted in this milestone.

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

Visit `http://localhost:3000`. The dashboard shows a loading state and then a green connected or red disconnected status based on the actual backend response. To verify separately, visit `http://localhost:8000/` and `http://localhost:8000/api/v1/health`. The latter returns `{"status":"healthy","application":"MNEMORA","version":"1.0.0"}`. The API documentation is at `http://localhost:8000/docs`.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Application name, version and running message |
| GET | `/api/v1/health` | Health status consumed by the dashboard |

All future endpoints should be registered beneath `/api/v1` as routers are added.

## Tests

From the repository root, after installing backend dependencies:

```powershell
python -m pip install -r backend/requirements.txt
$env:PYTHONPATH = (Join-Path (Get-Location) "backend")
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest
```

The tests cover root and health response JSON and the local frontend CORS preflight. The browser's live status is also an end-to-end connectivity check.

## GitHub preparation

Git is initialized in this workspace. No remote has been configured and nothing has been pushed. After reviewing the files, create the first commit with:

```powershell
git add .
git commit -m "Initial MNEMORA project setup"
```

To initialize a repository in a fresh copy, run `git init` first. Add a remote only when ready to publish.

## Future milestones

1. **Project setup and architecture** — complete.
2. **Conversational AI Engine** — this milestone.
3. **Short-term memory persistence** — replace process-local conversation state with durable storage.
4. **Long-term memory** — extraction, semantic retrieval, and contradiction-aware updates.
5. **Voice and knowledge views** — input/output and memory visualization.
6. **Personalization and orchestration** — specialized agents and evolving user context.

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

`api/chat.py` validates requests, manages conversation endpoints, and exposes REST and SSE routes. `agents/assistant.py` assembles the configured system prompt, recent conversation context, and current user message. `services/llm_service.py` is the only module that creates or calls the Google GenAI SDK. It uses the official Python SDK's async `generate_content` and `generate_content_stream` methods. The client is initialized lazily; application startup and health checks make no Gemini calls. [Google GenAI SDK documentation](https://googleapis.github.io/python-genai/)

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

### Conversation context and limitations

`InMemoryConversationStore` gives each conversation a unique ID and stores role-tagged user and assistant messages separately. The assistant receives at most `CHAT_MAX_HISTORY_MESSAGES` recent messages plus the current request. Conversations can be listed, opened, renamed, cleared, and deleted through the chat API.

This is process-local temporary state. Restarting the backend clears all conversations; running multiple backend workers would give each worker separate history. It is not long-term user memory, and no Redis or vector database is used in this milestone. A storage interface isolates the API and assistant from the in-memory implementation so a persistent store can replace it later.

### Chat endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/chat/health` | Reports configured model and whether an API key is set; makes no model call |
| POST | `/api/v1/chat/conversations` | Create a conversation |
| GET | `/api/v1/chat/conversations` | List conversations |
| GET | `/api/v1/chat/conversations/{id}` | Retrieve one conversation and its messages |
| PATCH | `/api/v1/chat/conversations/{id}` | Rename a conversation |
| DELETE | `/api/v1/chat/conversations/{id}/messages` | Clear its messages |
| DELETE | `/api/v1/chat/conversations/{id}` | Delete it |
| POST | `/api/v1/chat` | Generate one complete response |
| POST | `/api/v1/chat/stream` | Stream a response as Server-Sent Events |

Example non-streaming request:

```json
{"conversation_id":"conv_example","message":"Explain how neural networks work"}
```

The stream sends `conversation`, `token`, then `done` events. If generation fails it sends an `error` event with a safe message and retry guidance. Only a completed assistant turn is stored; a partial stream is not added to conversation history.

### Frontend integration

`frontend/lib/api.ts` centralizes the backend URL and HTTP errors. `frontend/lib/chat.ts` owns typed conversation requests and parses SSE frames across network chunk boundaries. The chat UI uses reusable sidebar, message, input, typing, and welcome components. Markdown is rendered with `react-markdown` and `remark-gfm`; raw HTML is not enabled. The right details panel displays the configured model and actual backend/chat health state, not simulated metrics.

### Run and test the chatbot

Follow the Windows setup commands above. Set a real API key in `backend/.env`, start the backend and frontend, open `http://localhost:3000`, and send a suggested prompt or your own message. Try “My name is Alex” followed by “What is my name?” in one conversation, then ask the same question in a new conversation to confirm their histories are independent. Use the sidebar controls to rename, clear, switch, and delete conversations. Stop and restart the backend to confirm that temporary history resets.

Automated tests mock all model calls and require no Gemini API usage. From the repository root:

```powershell
python -m pip install -r backend/requirements.txt
$env:PYTHONPATH = (Join-Path (Get-Location) "backend")
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest
```

To inspect the health state without sending a prompt, open `http://localhost:8000/api/v1/chat/health`. No actual Gemini call is made by tests, health checks, or application startup.
