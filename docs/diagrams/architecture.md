# TestForge AI — Architecture Diagrams

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        FRONTEND  (Angular 21 — :4200)                   │
│                                                                         │
│  Pages: Projects · UserStories · TestPlans · TestSuites · TestCases    │
│         RiskAnalysis · PlaywrightScripts · ExecutionDashboard           │
│                                                                         │
│  auth.interceptor ──► Bearer JWT        sse.service ──► EventSource    │
└────────────────────────────────┬────────────────────────────────────────┘
                      REST/HTTP  │  SSE (text/event-stream)
┌────────────────────────────────▼────────────────────────────────────────┐
│                        BACKEND  (FastAPI — :8000)                       │
│                                                                         │
│  Middleware: CORS · RateLimit · X-Request-ID                            │
│                                                                         │
│  Routers (21): /auth /projects /user-stories /test-plans /test-suites  │
│                /test-cases /risks /playwright /pipeline /dashboard      │
│                /jira /defects /notifications                            │
│                                                                         │
│  ┌─────────────┐   ┌──────────────────────────────────────────────┐    │
│  │  SSE Manager │   │              WORKER POOLS                    │    │
│  │  (Redis buf) │   │                                              │    │
│  └──────┬───────┘   │  TC Worker ×5  (600s)  ──► ai_workflows/   │    │
│         │           │  Risk Worker ×5         ──► test_case/      │    │
│         │           │  US Worker ×3           ──► risk_analysis/  │    │
│         │           │                         ──► user_story_ref/ │    │
│         │           └──────────────────────────────────────────────┘    │
└─────────┼───────────────────────────────────────────────────────────────┘
          │
┌─────────▼───────────────────────────────────────────────────────────────┐
│                           AI LAYER                                      │
│                                                                         │
│  ai_workflows/ (LangChain — stateless)                                  │
│    risk_analysis · test_case · test_suite · user_story_refinement       │
│                                                                         │
│  ai_agents_v2/ (LangGraph — stateful, PostgreSQL checkpoints)           │
│    playwright_e2e · test_case_generator · tasty                         │
│                                                                         │
│  llm_control.py: Groq pool (5 keys) ──► OpenRouter (6 keys) fallback   │
└────────┬─────────────────────────────────────────┬───────────────────────┘
         │                                         │
┌────────▼──────────┐                   ┌──────────▼──────────┐
│   GROQ API        │                   │  OPENROUTER API     │
│  (primary LLM)    │                   │  (fallback LLM)     │
└───────────────────┘                   └─────────────────────┘

┌───────────────────────────────────────────────────────────────────────┐
│                          DATA LAYER                                   │
│                                                                       │
│  PostgreSQL (asyncpg, pool=20)       Redis                           │
│  ├── Main DB (18 tables)             ├── SSE event buffer             │
│  │   Alembic migrations              ├── Refresh token blacklist      │
│  └── Checkpoint DB (LangGraph)       └── Cache (TTL=604800s)          │
└───────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL SERVICES                              │
│                                                                       │
│  Jira Cloud API        Langfuse (LLM tracing)                        │
│  MCP Playwright Server (browser automation)                           │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Model — Entity Relationship (ISTQB Hierarchy)

```
User ─────────────────────────────────────────────┐
  │ 1                                              │
  │ CASCADE                                        │
  ▼ N                                              │
JiraConnection                                     │
  │ 1                                              │
  │ CASCADE (delete-orphan)                        │
  ▼ N                                              │
JiraProject                                        │
  │ 1                    │ 1                       │
  │ CASCADE              │ CASCADE                 │
  ▼ N                    ▼ N                       │
UserStory             TestPlan ──────────────────► TcCoverage
  │ 1                    │ 1         CASCADE         (SET NULL user_story_id)
  │ CASCADE              │ CASCADE
  ├──► UserStoryVersion  ├──► TestSuite
  │      │ SET NULL      │        │ SET NULL
  │      ▼               │        ▼
  │    Defect            │      TestCase ◄─────── UserStory (SET NULL)
  │                      │        │ 1
  │ passive_deletes       │        │ CASCADE
  ├──► Risk               └──────► │
  │   (test_plan_id FK)            ├──► PlaywrightScriptVersion
  │                                │        │ CASCADE
  │ passive_deletes                 │        ▼
  └──► Defect (test_case_id: SET NULL)     TestRun ──► TestResult
                                           │ 1         (CASCADE)
                                           │ CASCADE
                                           ▼ N
                                         TestStepResult

Legend:
  ──► CASCADE          delete parent → delete child
  ··► SET NULL         delete parent → null FK in child
  passive_deletes      SQLAlchemy delegates to DB cascade (no ORM interference)
```

---

## 3. AI Pipeline Flow (Test Case Generation — ISTQB §5.2)

```
                    ┌─────────────────┐
                    │   Jira Import   │
                    └────────┬────────┘
                             │ UserStory created
                             ▼
                    ┌─────────────────┐
                    │  US Refinement  │  LangChain
                    │  (US Worker)    │  testability scoring
                    └────────┬────────┘
                             │ acceptance_criteria refined
                             ▼
                    ┌─────────────────┐
                    │  Risk Analysis  │  LangChain
                    │  (Risk Worker)  │  P×I → score → level
                    └────────┬────────┘
                             │ Risk record (critical/high/medium/low)
                             ▼
                    ┌─────────────────┐
                    │   Test Plan     │  AI draft: objective,
                    │   Generation    │  entry/exit criteria
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   Test Suite    │  LangChain grouping
                    │   Organization  │  by business flow
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Test Case Gen  │  LangGraph agent
                    │  (TC Worker)    │  Given/When/Then
                    └────────┬────────┘
                             │ TestCase (Gherkin + steps + test data)
                             ▼
                    ┌─────────────────┐
                    │ Playwright Gen  │  LangGraph ReAct
                    │  v1 (draft)     │  [TESTFORGEAI: selector]
                    └────────┬────────┘
                             │ PlaywrightScriptVersion
                             ▼
                    ┌─────────────────┐
                    │   Execution     │  MCP Playwright
                    │   (TestRun)     │  chromium/firefox/webkit
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │                 │
                    ▼                 ▼
              TestResult          TestRun
              (passed/failed)     Steps (ReAct log)
                    │
                    ▼ if failed
              Defect ──► Jira ticket
```

---

## 4. Job Lifecycle (Worker Persistence — ISTQB §5.1)

```
API Request
    │
    ▼
POST /test-cases/generate/{plan_id}/async
    │
    ├── Create Job record (status=pending) ──► PostgreSQL
    │
    ├── Push to asyncio.Queue
    │
    ▼
TC Worker picks up job
    │
    ├── Job.status = "running"
    │   Job.started_at = now()
    │
    ├── Push SSE events ──► sse_manager ──► Frontend EventSource
    │   (progress: analyzing, generating, persisting)
    │
    ├── Run LangChain pipeline
    │
    ├── Save TestCase records
    │
    └── Job.status = "completed"
        Job.result_summary = {tc_count, coverage_pct}
        Job.completed_at = now()

On restart:
    SELECT * FROM jobs WHERE status='pending'
    → re-enqueue all pending jobs
```

---

## To generate visual diagrams

Install [eralchemy2](https://github.com/maurerle/eralchemy2) for the ER diagram:

```bash
pip install eralchemy2
eralchemy2 -i "postgresql://user:pass@localhost/testforge" -o docs/diagrams/er_model.png
```

Or connect the Eraser MCP in `~/.claude/mcp.json`:
```json
{
  "mcpServers": {
    "eraser": {
      "type": "http",
      "url": "https://app.eraser.io/api/mcp"
    }
  }
}
```
