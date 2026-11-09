# MNEMORA — An AI That Remembers, Learns and Evolves

MNEMORA is a personal assistant foundation designed to gain useful context over time. This milestone creates the project structure, configuration, API health check and connected dashboard. It intentionally does not call an LLM or perform memory operations.

## Objectives and planned capabilities

The planned product includes conversational AI, short and long-term memory, semantic retrieval, voice input/output, memory extraction and categorization, knowledge graph visualization, contradiction detection, personalization and multi-agent orchestration. These are future milestones; this repository currently provides the foundation only.

## Technology and architecture

- **FastAPI, Uvicorn and Pydantic Settings** provide a typed Python API, local ASGI server and environment configuration.
- **SQLAlchemy** prepares relational persistence; SQLite is the default and the URL can later target PostgreSQL.
- **LangChain, LangGraph and OpenAI** are planned agent and model dependencies; no model calls happen in this milestone.
- **ChromaDB** is reserved for semantic long-term memory; **Redis** for short-lived state and caching.
- **Next.js, React, TypeScript and Tailwind CSS** provide the responsive App Router dashboard. **Lucide React** supplies icons.

The browser dashboard calls `GET /api/v1/health` using `NEXT_PUBLIC_API_URL`. FastAPI allows the configured `FRONTEND_URL` origin. Backend settings remain server-side; no API key is put in frontend configuration.

## Folder structure

```text
backend/
  app/
    agents/       memory/       voice/
    api/          database/     models/
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

Copy `backend/.env.example` to `backend/.env`. Keep `OPENAI_API_KEY` empty until a later milestone needs it. Copy `frontend/.env.local.example` to `frontend/.env.local`; it contains only the public API base URL. Both real environment files are ignored by Git. Never put secrets in a `NEXT_PUBLIC_` variable because those values are included in browser code.

The backend reads `OPENAI_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `CHROMA_DB_PATH` and `FRONTEND_URL` from its `.env` or process environment. Defaults allow local startup without Redis, ChromaDB or credentials; those services are not contacted in this milestone.

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
python -m pip install pytest httpx
$env:PYTHONPATH = (Join-Path (Get-Location) "backend")
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

1. **Project setup and architecture** — this milestone.
2. **Persistence and memory foundations** — database models, short-term state and vector storage.
3. **Agent and LLM integration** — conversation flow, prompts and provider configuration.
4. **Memory extraction and retrieval** — durable user context and semantic search.
5. **Voice and knowledge views** — input/output and memory visualization.
6. **Personalization and orchestration** — updates, contradiction handling and specialized agents.

## Milestone 1 checklist

- [x] Modular backend/frontend folders and environment examples
- [x] FastAPI root and versioned health endpoints with local CORS
- [x] Responsive dark dashboard with real health endpoint status
- [x] Dependency manifests and Git ignore rules
- [x] Beginner-friendly setup and API documentation
- [x] Pytest health/CORS checks (3 passed)
- [x] Production build, ESLint, and live frontend-to-backend connection verified

The listed backend dependencies include the planned agent and memory integrations; those unused services are not initialized in this milestone. The frontend production dependency audit is clean. The full dependency tree retains 8 moderate advisories in ESLint's transitive TypeScript parser (`minimatch`); npm's suggested automatic fix would downgrade the Next lint config across a major version, so that was not applied.
