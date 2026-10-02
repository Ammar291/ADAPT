# ADAPT: Abu Dhabi Digital Arrival & Planning Twin

ADAPT helps a person arrive, settle, connect and build a future in Abu Dhabi. It combines
a shared **governance knowledge graph** (public rules, services, requirements, authorities)
with a **private user digital twin** (the person's own facts, documents, relationships and
goals). Evidence retrieved from official sources then turns the two into a personalised,
dependency-aware settlement journey.

> **Status:** shared foundations are in place (contracts, schema with row-level security,
> event streaming, agent runtime, adapters, app shell). Feature workstreams build on them.
> See [ARCHITECTURE.md](ARCHITECTURE.md) for the design, the API contract plan and the
> dependency map.

The product's privacy boundaries, evidence rules, provider confirmation requirements and
security verification are documented in [TRUST.md](TRUST.md).

## Quick start (Docker)

Requirements: Docker Desktop (Compose v2).

```bash
cp .env.example .env            # optional: set OPENAI_API_KEY for live AI capabilities
docker compose up --build
```

| What | URL |
|---|---|
| App (PWA, served by nginx; proxies `/api`) | http://localhost:8080 |
| API docs (development only) | http://localhost:8100/api/docs |
| Postgres (owner `adapt`/`adapt`, runtime `adapt_app`/`adapt_app`) | `127.0.0.1:55432` |
| Redis | `127.0.0.1:56379` |

Start-up order is automatic: `postgres` → `migrate` (Alembic, then the governance seed) →
`backend` + `worker` → `frontend`. Open the app: a new visitor lands on onboarding, and
finishing it opens **Agents**, where the plan is built live. **Agents → Run a system check**
streams a real agent run through the whole pipeline.

**No OpenAI key?** Everything still runs. Each AI capability falls back to a deterministic
demo adapter, which refuses rather than inventing content. Developers can see which adapters
are simulated from the dashed badge in the UI, the `X-ADAPT-Demo-Adapters` response header,
and `GET /api/health/ready`.

Reset all data (including the database volume): `docker compose down -v`.

**Demo documents.** [`demo-documents/`](demo-documents) holds clearly marked SPECIMEN PDFs for
the demo persona (passport with a valid machine-readable zone, marriage certificate, ADGM
licence, salary certificate, tenancy contract). ADAPT reads them offline from their text layer,
so no key is needed; photos need `OPENAI_API_KEY` and otherwise go to review. Nothing is ever
made up. Regenerate them with `cd backend && uv run python -m app.documents.specimens ../demo-documents`.
See [docs/private-user-twin.md](docs/private-user-twin.md).

## Live demo: Founder Arrival

**Hackathon stage mode:** run `npm run demo`, then open
**http://127.0.0.1:5181/demo/founder-arrival**. This isolated synthetic presentation has
voice/text recovery, a visible **Demo Reset**, background research, branch comparison and
the final Arrive / Settle / Connect / Build plan. It explicitly replays real recorded
LangGraph and document-reader results and uses a dated reviewed research catalogue.
It needs no backend or API key and blocks private API access and real document uploads.
See [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) for the exact three-minute sequence and fallbacks.
`npm run demo:build && npm run audit:demo` runs the production browser rehearsal (Playwright required).

The separate live-stack scenario below is available with `DEMO_MODE=false`:

A deterministic, presenter-driven run of the real pipeline for an Indian founder moving to
Abu Dhabi with his wife (fictional people, synthetic SPECIMEN documents). Open
**http://localhost:8080/demo/founder-arrival** (also in the sidebar and in Settings) and press
**Continue** act by act, or **Play all**. **Start a fresh run** gives every rehearsal a new
private account. Rehearse it headlessly first:

```bash
cd backend && uv run python scripts/demo_founder_arrival.py --twice   # two fresh runs must match
```

What it shows, why it is repeatable and the presenter runbook:
[docs/demo-founder-arrival.md](docs/demo-founder-arrival.md). The synthetic PDFs are in
[`demo-documents/founder-arrival/`](demo-documents/founder-arrival) for manual uploads too.

## Native development

Run Postgres and Redis in Docker, and the apps on your machine for hot reload:

```bash
docker compose up -d postgres redis
cp .env.example .env                    # native defaults point at 127.0.0.1:55432 / 56379
```

**Backend** (Python 3.13 with [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
uv sync
uv run alembic upgrade head             # runs as the schema owner (MIGRATION_DATABASE_URL)
uv run python -m app.seed               # governance graph (idempotent)
uv run uvicorn app.main:app --reload --port 8100 --loop app.core.compat:new_event_loop
uv run python -m app.workers            # ARQ worker (in a second terminal)
```

`--loop app.core.compat:new_event_loop` is only required on Windows, because psycopg's async
driver can't use the default Proactor loop. It's harmless elsewhere. Inside Docker the worker
runs as `arq app.workers.settings.WorkerSettings`.

**Frontend** (Node 22 or later):

```bash
npm install                             # from the repository root (npm workspaces)
npm run dev                             # http://localhost:5180, proxies /api to 127.0.0.1:8100
```

The frontend picks its data per capability (see ARCHITECTURE.md §9 and D21):

| `VITE_DATA_MODE` | Behaviour |
|---|---|
| `auto` (default) | The API for every capability the backend reports as shipped in `/system/info`; typed in-memory mocks for the rest |
| `mock` | Everything from mocks, including the session. No backend needed: `VITE_DATA_MODE=mock npm run dev` |
| `live` | Never mocks. Unshipped capabilities show "not available yet". Use this for real deployments |

With journeys served by mocks, append `?seed=sample` to any URL (e.g. `/home?seed=sample`) to load
a sample founder-with-spouse plan a few weeks in, or choose **Explore with a sample plan** on onboarding.

## Everyday commands

| Task | Command |
|---|---|
| Backend unit tests | `cd backend && uv run pytest tests/unit` |
| Backend integration tests (needs compose Postgres) | `cd backend && uv run pytest tests/integration` |
| Lint and format backend | `cd backend && uv run ruff check app tests && uv run ruff format app tests` |
| Founder Arrival rehearsal (against a running stack; `--twice` checks determinism) | `cd backend && uv run python scripts/demo_founder_arrival.py --twice` |
| End-to-end demo smoke test (against a running stack; all 19 demo steps) | `cd backend && uv run python scripts/smoke_demo.py` (add `--base http://127.0.0.1:8100/api` for a native backend) |
| Frontend tests | `npm test` |
| Typecheck contracts and frontend | `npm run typecheck` |
| Production build of the frontend | `npm run build` |
| **Regenerate shared API contracts** after changing `backend/app/contracts` | `npm run contracts:generate` |
| New migration | `cd backend && uv run alembic revision --autogenerate -m "…"`, then add RLS for private tables with `app.db.rls.private_table_sql` |
| Regenerate PWA icons and iOS splash screens from `frontend/public/brand-mark.svg` | `npm run icons -w @adapt/frontend` (then paste the printed splash `<link>` tags between the `apple-splash` markers in `frontend/index.html`) |

A backend test fails when `packages/contracts/openapi.json` is out of date, so contract
changes can't silently drift from the frontend.

## Configuration

All configuration is environment variables, documented in [`.env.example`](.env.example).
The most important ones:

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Enables live LLM, embeddings, OCR, voice and web research. Stays server-side; the browser only ever gets short-lived voice session secrets |
| `ADAPTER_<LLM\|EMBEDDINGS\|OCR\|VOICE\|WEB_SEARCH>` | `auto` (live if a key is present), `live` (fail without a key) or `demo` |
| `DATABASE_URL` / `MIGRATION_DATABASE_URL` | Runtime role (row-level security applies) / schema owner (migrations and seeding) |
| `SESSION_SECRET`, `DOCUMENT_ENCRYPTION_KEY` | Required and validated in production (`ADAPT_ENV=production`) |
| `DEMO_AUTH_ENABLED` | Transparent private demo accounts. Must be `false` in production |
| `*_HOST_PORT` | Change host ports if 55432, 56379, 8100 or 8080 are taken |
| `VITE_SHOW_DEV_BADGE` | Developer-only badge listing demo adapters and mocked frontend capabilities (build argument for the frontend image) |
| `VITE_DATA_MODE` | Frontend data source: `auto` (default), `mock` or `live` (build argument for the frontend image) |

## Trust and safety rules (enforced in code)

* Government submissions and bookings are never reported as done without a real external
  reference. Simulated adapters can't claim success, and the database rejects it too.
* Services that need the user's own login are **official handoffs**. ADAPT never collects or
  stores UAE PASS credentials.
* Every claim carries a trust tier: *Required*, *Official guidance*, *From the web*,
  *ADAPT suggestion*. Official tiers must cite an official government domain.
* Faith and other sensitive attributes are never inferred. They are recorded only when the
  user states them, and faith only after explicit opt-in.
* Private data is isolated per user by PostgreSQL row-level security. Documents are encrypted
  at rest and never cached by the browser or service worker.

## Repository layout

```
backend/            FastAPI API, LangGraph agents, ARQ worker, Alembic migrations, tests
frontend/           React + Vite PWA (app shell, design system, domain model, service layer with live adapters and mocks, feature screens)
packages/contracts/ TypeScript API contracts generated from the backend's Pydantic models
infra/postgres/     database roles and extensions for local and Docker setups
```

## Troubleshooting

ADAPT Interpreter is a separate human-to-human translation experience at `/interpreter`.
See [the interpreter guide](docs/INTERPRETER.md) for setup, language capabilities,
WebRTC credentials, recorded fallback, PWA requirements, and verification.

* **Port already in use:** set `POSTGRES_HOST_PORT`, `REDIS_HOST_PORT`, `BACKEND_HOST_PORT` or
  `FRONTEND_HOST_PORT` in `.env`.
* **Slow database connections on Windows:** use `127.0.0.1` rather than `localhost` in URLs
  (avoids an IPv6 fallback delay). `.env.example` already does.
* **Role `adapt_app` missing:** the init script runs only when the data volume is first
  created. Run `docker compose down -v` to recreate it.
* **UI stuck on an old version:** the PWA asks before updating. Choose *Reload* in the
  "new version is ready" banner, or hard-refresh.
