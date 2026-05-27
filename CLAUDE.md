# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (Python/FastAPI)
```bash
cd backend

# Run dev server (port 8000)
uvicorn app.main:app --reload

# Run database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"

# Seed database
python -m app.seeds.seed_db

# Run tests
pytest app/tests/
pytest app/tests/test_agent.py          # single test file
pytest app/tests/test_llm.py -k "name"  # single test by name
```

### Frontend (Angular 21)
```bash
cd frontend

npm install                # install deps
npm start                  # dev server on localhost:4200
npm run build              # production build
npm test                   # Karma + Jasmine unit tests
```

## Architecture

### Monorepo structure
- `backend/` — FastAPI async Python API
- `frontend/` — Angular 21 standalone-component SPA
- `docs/diagrams/` — Architecture diagrams (PNG)

### Backend (`backend/app/`)

**Entry point:** `main.py` — Mounts all routers, runs lifespan (DB init, Redis, SSE), adds CORS/rate-limit/request-ID middleware.

**Layer pattern:**
```
API Router (api/) → Service (services/) → Repository (repositories/) → SQLAlchemy Model (models/)
```

**Key directories:**
- `api/` — 25 FastAPI routers (one file per domain: auth, projects, test-cases, risks, playwright, jira, pipeline, etc.)
- `api/deps.py` — `get_current_user()` / `get_current_admin()` JWT dependency injection
- `core/config.py` — Pydantic settings (reads from `.env`)
- `core/database.py` — Async SQLAlchemy engine (pool_size=20, asyncpg)
- `core/security.py` — bcrypt hashing, JWT access + refresh tokens, Redis-backed refresh token blacklisting
- `llm/llm_control.py` — LLM key pool rotation; Groq (5 keys) → OpenRouter (6 keys) fallback, 10s min interval, retry delays [15s, 30s, 60s]
- `workers/` — Async task queues (us_worker, tc_worker, risk_worker) with SSE streaming; max 5 concurrent workers, 120s timeout
- `streaming/sse_manager.py` — Server-sent events for real-time job status to frontend
- `ai_workflows/` — Stateless LangChain pipelines: test case generation (Gherkin), test plan building, test suite organization, risk scoring, user story refinement
- `ai_agents_v2/` — LangGraph stateful agents: Playwright E2E script generator, TASTY agent, test case generator (React graph with tool nodes)
- `repositories/` — Data-access layer; all DB queries go here, not in services or routers

**Database:** PostgreSQL via asyncpg. Alembic for migrations. LangGraph also uses PostgreSQL for checkpoint storage (separate `CHECKPOINT_DB_URL`). Redis for caching (TTL=604800s) and refresh-token blacklisting.

**Observability:** Langfuse traces every LLM call. All requests get an `X-Request-ID` header via middleware.

### Frontend (`frontend/src/app/`)

**Entry point:** `app.routes.ts` — Root route guarded by `AuthGuard`; lazy-loads all feature modules. Unauthenticated routes use `BlankLayout`.

**Auth flow:** `auth.interceptor.ts` attaches Bearer token to every request, catches 401s, calls refresh endpoint, then retries the original request. `auth.guard.ts` auto-attempts token refresh on navigation to protected routes.

**Key directories:**
- `layouts/` — `FullLayout` (authenticated shell with sidebar/header) and `BlankLayout` (login/register)
- `pages/` — Feature pages: projects, test-plans, test-cases, test-suites, user-stories, risks, playwright-details, execution-dashboard, jira, admin, profile
- `services/` — 24 Angular services; each maps 1:1 to a backend domain (e.g. `test-case.service.ts`, `playwright-e2e.service.ts`, `sse.service.ts` for SSE consumption)
- `core/guards/` and `core/interceptors/` — Auth guard + HTTP interceptor
- `environments/` — `apiUrl` points to `http://localhost:8000` in dev

**Styling:** Angular Material 21 + Tailwind CSS 4 (via PostCSS). Component styles in SCSS. Budget: 12MB initial bundle.

### AI pipeline flow (test case generation example)
1. Frontend calls `POST /pipeline` → triggers worker via queue
2. `tc_worker.py` picks up job, runs `ai_workflows/test_case/` LangChain pipeline
3. Pipeline calls `llm_control.py` which rotates through Groq/OpenRouter keys
4. Results saved to DB; status streamed to frontend via `sse_manager.py` → `EventSource` in `sse.service.ts`
5. For Playwright script generation, `ai_agents_v2/playwright_e2e/` LangGraph agent runs via `POST /playwright`

### Environment
Backend reads from `backend/.env`. Required variables: `DATABASE_URL`, `SECRET_KEY`, `GROQ_API_KEY_1`–`5`, `OPENROUTER_API_KEY_1`–`6`, `REDIS_HOST`, `REDIS_PORT`, `CHECKPOINT_DB_URL`. Frontend `apiUrl` is in `src/environments/environment.ts`.
