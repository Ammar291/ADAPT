# ADAPT backend: domain model, storage, API and privacy

Owner: backend workstream (FastAPI, PostgreSQL + pgvector, Redis, ARQ, migrations, API
contracts, authentication, privacy boundaries). Feature workstreams own their logic in
their own packages and build on what is described here. The overview is in
[ARCHITECTURE.md](../ARCHITECTURE.md).

## Contents

1. [Domain model](#1-domain-model)
2. [Graph storage](#2-graph-storage)
3. [Governance corpus (RAG)](#3-governance-corpus-rag)
4. [API](#4-api)
5. [Agent runs and streaming](#5-agent-runs-and-streaming)
6. [Authentication](#6-authentication)
7. [Privacy boundaries and security](#7-privacy-boundaries-and-security)
8. [Migrations](#8-migrations)
9. [Seed data](#9-seed-data)
10. [Tests](#10-tests)
11. [Extending the backend](#11-extending-the-backend)

---

## 1. Domain model

Every entity is a SQLAlchemy model in `backend/app/db/models/`. "Private" tables carry
`tenant_id` + `user_id` and an owner-only RLS policy; "public" tables are shared reference
data that the runtime role can only read.

| Entity | Table | Kind | Owner of the logic |
|---|---|---|---|
| User | `users` (+ `tenants`) | account (RLS: self only) | backend |
| UserProfile | `user_profiles` (1 per user) | private | backend |
| HouseholdMember | `household_members` | private | backend |
| UserPreference | `user_preferences` | private | backend |
| UserGoal | `user_goals` | private | backend |
| UserDocument | `user_documents` | private | documents workstream (rev 0004) |
| ExtractedFact | `extracted_facts` | private | documents workstream (rev 0004) |
| GraphNode / GraphEdge | `graph_nodes` / `graph_edges` | shared (governance) + private (user) | backend (schema), knowledge + personalization (content) |
| GovernanceSource | `governance_sources` | public | backend (schema), knowledge (content) |
| GovernanceDocument | `governance_documents` | public | backend (schema), knowledge (content) |
| GovernanceChunk | `governance_chunks` | public | backend (schema + `similarity_search`), knowledge (ranking) |
| Journey | `journeys` | private | backend (storage, reads), journey agent (planning) |
| JourneyNode / JourneyEdge | `journey_nodes` / `journey_edges` | private | backend (storage), journey agent |
| AgentRun / AgentEvent | `agent_runs` / `agent_events` | private | backend |
| GeneratedDocument | `generated_documents` | private | backend |
| Action / ActionApproval | `actions` / `action_approvals` | private | backend (schema, invariants), journey agent (state machine, adapters) |
| ResearchJob / ResearchResult | `research_jobs` / `research_results` (+ `research_citations`) | private | research workstream (rev 0003, 0005) |
| Community / Event / CulturalGuide | `communities` / `events` / `cultural_guides` | public | backend (schema, browse API), research (curated data) |
| Appointment | `appointments` | private | backend |

Vocabularies are closed `StrEnum`s in `app/domain/enums.py`, stored as varchar with a
named CHECK constraint. They are exported to TypeScript, so renaming a member is a breaking
change.

### Invariants the database enforces

| Rule | Where |
|---|---|
| A user row is visible and writable only by its owner | RLS `<table>_owner` on every private table; `users_self` / `tenants_self` on accounts |
| Governance graph rows are shared and read-only for the runtime role | RLS `graph_nodes_read` / `graph_nodes_write_user` (same on edges) |
| A governance edge never touches a user node; a user edge never reaches another user's node | trigger `graph_edges_enforce_graph_type` (SECURITY INVOKER, so RLS applies inside it) |
| Journey edges connect nodes of the same journey | composite FKs `(journey_id, node_id)` |
| An action moves to `approved` / `submitted` / `completed` only with an **approved** approval of that same action | trigger `actions_require_approved_approval` |
| `completed` needs an external reference; simulated adapters can't submit (unless the user reports completion); handoffs need an https URL | CHECK constraints on `actions` (written NULL-safe) |
| An approval's `decided_at` is set exactly when it is no longer pending; one approval per action | CHECK + UNIQUE on `action_approvals` |
| Generated documents: `approved` ⇔ `approved_at` set | CHECK on `generated_documents` |
| A confirmed appointment has an external reference | CHECK on `appointments` |
| Faith preferences can only be user-stated | CHECK `faith_is_user_stated` on `user_preferences` |
| Catalogue rows cite a source or are flagged sample, and are never "authoritative requirements" | CHECKs on `communities` / `events` / `cultural_guides` |

## 2. Graph storage

Both logical graphs share two tables. Column names follow the product spec.

```
graph_nodes
  id · graph_type ('governance' | 'user') · entity_type · key · label · summary
  properties_json · source_id → governance_sources (nullable) · user_id · tenant_id (nullable)
  provenance · official_url · valid_from · valid_to · version · embedding vector(1536)
  created_at · updated_at
  CHECK ownership_matches_graph   governance ⇒ user_id/tenant_id NULL; user ⇒ both NOT NULL
  CHECK entity_type_matches_graph governance types vs user types
  UNIQUE (key) WHERE governance · UNIQUE (user_id, key) WHERE user

graph_edges
  id · graph_type · relation · source_node_id → graph_nodes · target_node_id → graph_nodes
  properties_json · user_id · tenant_id (nullable) · label · provenance · created_at
  UNIQUE (source_node_id, target_node_id, relation) · CHECK no self loops

graph_node_evidence / graph_edge_evidence   node|edge → governance_documents / governance_chunks
```

**Rule:** user-graph rows are always scoped to `user_id` (CHECK + RLS + trigger), and
governance rows are shared. Personalisation links (`pursues`, `satisfies`, `instance_of`,
`eligible_for`, `blocked_by`) go from a user node to a governance node, and they are private
because they are stored as user-graph edges.

**Vocabulary** (`GovernanceNodeType`, `TwinNodeType`, `GraphEdgeType`):

| Graph | Entity types | Relations |
|---|---|---|
| governance | authority, service, requirement, eligibility_rule, document, dependency, appointment, portal, location, process_step, fee, legal_instrument | provides, requires, depends_on, satisfied_by, produces, applies_to, available_at, may_require, governed_by, located_in |
| user | person, household, spouse, child, passport, visa, nationality, company, business_activity, goal, housing_preference, budget, language, preference, document, appointment, community_preference | has_household_member, member_of, has_document, holds_visa, has_nationality, has_goal, prefers, seeks, founder_of, engages_in, speaks, has_budget, has_appointment |
| user → governance | | pursues, satisfies, instance_of, eligible_for, blocked_by |

`depends_on` is AND over its targets. A `dependency` node is an OR group: it is satisfied by
any one of its `satisfied_by` services (for example, a company licence from the mainland
*or* ADGM). Once revision 0004 is applied, user-graph facts live in `extracted_facts` with
per-fact provenance, and user nodes keep `properties_json = '{}'`.

**Repositories** (`app/repositories/graph.py`): `GovernanceGraphRepository` always filters
on `graph_type = 'governance'` and hides nodes retired via `valid_to`.
`UserGraphRepository` requires a user-scoped session and filters on the principal's
`user_id` in addition to RLS.

## 3. Governance corpus (RAG)

```
governance_sources    publisher registry: key · name · authority · base_url · source_type
                      is_official · priority · metadata
governance_documents  one retrieved VERSION of one page: source_url · title · authority
                      document_type · language · effective_date · retrieved_at
                      content_hash · is_official · superseded_at · metadata
                      UNIQUE (source_url, content_hash) · UNIQUE (source_url) WHERE live
governance_chunks     content · context · section · page · page_or_section (generated)
                      embedding vector(1536) HNSW cosine · embedding_model
                      content_tsv (generated, 'simple' config, context + content) GIN
```

* **Similarity search** is `app/repositories/governance_corpus.py → similarity_search(session,
  vector, *, k, embedding_model, authorities=None, document_types=None)`. It is cosine kNN
  over live document versions only, and only compares vectors from the same embedder
  (`embedding_model` = `Embedder.model_id`), so demo hashing vectors and OpenAI vectors are
  never mixed. `lexical_search` is the tsvector counterpart.
* Ranking, hybrid fusion, evidence objects and `/api/knowledge/*` are the knowledge layer's
  ([docs/knowledge-layer.md](knowledge-layer.md)).
* The corpus is written only by the owner role (seed and curated ingestion). The runtime role
  gets `permission denied` (tested).

## 4. API

Base path **`/api`**. JSON in and out. Errors are RFC 9457 problem details with a stable
`code` and a `request_id`. Every `/api` response is `Cache-Control: no-store`. Auth is the
session cookie, or `Authorization: Bearer` for tools and tests. The OpenAPI document (dev
only) is at `/api/openapi.json`, and TypeScript types are generated into `packages/contracts`.

| Method and path | Purpose | Owner |
|---|---|---|
| `GET /health` · `GET /health/ready` · `GET /system/info` | liveness, readiness, adapter modes + feature flags | backend |
| `POST /auth/demo-session` (`{sample_household: true}` signs into the seeded household) · `POST /auth/logout` · `GET /me` · `PATCH /me/preferences` · `DELETE /me` | sessions, consents, account deletion | backend |
| `POST /onboarding/profile` · `GET /profile` · `PATCH /profile` | profile, household, goals, preferences (+ user-graph projection) | backend |
| `POST /documents/upload` · `GET /documents` · `GET /documents/{id}` · `POST /documents/{id}/process` · `…/review` · `…/content` · `DELETE /documents/{id}` | document pipeline | documents |
| `GET /documents/generated` · `GET /documents/generated/{id}` · `POST /documents/generated/{id}/approve` · `…/discard` | generated documents | backend |
| `GET /graph/governance` · `GET /graph/governance/nodes/{ref}` | governance graph (knowledge view) · node detail | knowledge · backend |
| `GET /graph/user` (+ facts, schema, explain) | the caller's user graph | personalization |
| `GET /graph/journey/{journey_id}` | a journey as a dependency graph | backend |
| `GET /journey` · `POST /journey` · `GET /journey/{id}` · `GET /journey/{id}/what-if/variables` · `POST /journey/{id}/simulate` · `POST /journey/{id}/nodes/{key}/done` · `…/answer` | journeys (backend serves read-only fallbacks when the agent router is absent); see [journey-agent.md](journey-agent.md) | journey agent |
| `GET /agents` · `POST /agents/run` · `GET /agents/{run_id}` · `GET /agents/{run_id}/events` · `WS /agents/{run_id}/stream` | agent runs and streaming | backend |
| `GET /agents/{run_id}/review` · `POST /agents/{run_id}/resume` · `GET /agents/what_if/topology` | human-in-the-loop gates of a paused run | journey agent |
| `GET /actions` · `GET /actions/{id}` · `POST /actions/prepare` · `POST /actions/{id}/approve` · `POST /actions/{id}/reject` | human approval of actions | journey agent |
| `POST /research` · `GET /research/{job_id}` · `GET /discover` | research and Discover | research |
| `GET /communities` · `GET /events` · `GET /cultural-guides` | catalogue browse (faith items only after opt-in) | backend |
| `GET /appointments` · `GET /appointments/{id}` · `POST /appointments/{id}/prepare` | appointments and preparation (never booking) | backend |
| `POST /voice/session` · `POST /voice/tool-calls` · `POST /voice/assistant` | voice; see [voice.md](voice.md) | voice |
| `GET /knowledge/search` · `POST /knowledge/retrieve` · `POST /knowledge/explain` | evidence retrieval and explanations | knowledge |

**Router composition** (`app/api/router.py`): core routers live in `app/api/routes`. Feature
routers are mounted when their module imports. For the few paths the core also serves
(governance graph, user graph, journey reads), the feature router replaces the core
fallback. A feature router that fails to import is logged (`feature_router_unavailable`) and
skipped, so one unfinished workstream can't take the API down. `/documents/generated` is
mounted before any `/documents/{id}` route.

## 5. Agent runs and streaming

* `POST /api/agents/run {agent, input}` validates `input` against the agent's registered
  schema (`app/services/agent_registry.py`), creates the RLS-owned `agent_runs` row and
  enqueues the ARQ job (idempotent per run id). It answers `202` with `{run, events_url,
  stream_url}`. `GET /api/agents` lists the registered agents with their input schemas.
* Events are **flat structured JSON** discriminated by `event`:

  ```json
  {"event": "node_started", "run_id": "…", "seq": 3, "ts": "…",
   "node": "document_analysis", "label": "Analyzing your documents"}
  ```

  Types: `run_started`, `run_status`, `run_completed`, `run_failed`, `run_cancelled`,
  `node_started`, `node_progress`, `node_completed`, `error`, `tool_called`, `tool_result`,
  `evidence_found`, `document_generated`, `action_prepared`, `approval_required`,
  `approval_resolved`, `question_asked`, `message_delta`, `artifact_created`,
  `artifact_updated`, and the research events `research_started`, `research_source_found`,
  `research_category_completed`, `research_completed`, `research_failed`. The fields per type
  are the `AgentEvent` union in `app/contracts/events.py` (exported to TypeScript).
* Emitters use `EventSink` helpers (`events.tool_called(...)`, `events.evidence_found(...)`,
  …). Each event is validated against the contract before it is persisted. `RunEventEmitter`
  allocates `seq` with a row-locked `UPDATE agent_runs … RETURNING` (gap-free, safe for
  parallel LangGraph branches), writes `agent_events` in the same transaction, keeps the run
  status in step, then publishes a Redis wake-up.
* **Transports** (same objects everywhere):
  `GET /api/agents/{id}/events` returns JSON `{run_id, status, last_seq, events}`
  (`?after=`), or **Server-Sent Events** when the client sends `Accept: text/event-stream`
  (`id: <seq>`, resume with `Last-Event-ID`). `WS /api/agents/{id}/stream` sends one text
  frame per event plus `{"event":"ping"}` keep-alives, closing with 1000 after a terminal
  event, **4401** without a session or from a foreign `Origin` (cross-site WebSocket
  hijacking), and **4404** for runs the caller doesn't own.
* Events carry pointers and short labels, never private payloads. Evidence quotes are
  truncated to 600 characters and come from the public corpus only.

## 6. Authentication

`app/core/auth.py` separates **sessions** from **identity providers**:

* Every request resolves to a `Principal(user_id, tenant_id)` from a signed session token
  (httpOnly `SameSite=Lax` cookie on path `/api`, or a Bearer header). Nothing downstream
  knows how the user signed in.
* An `IdentityProvider` turns a sign-in into an `ExternalIdentity(provider, subject)`.
  `sign_in()` maps it to an account through `users.auth_provider` / `users.auth_subject`,
  creating the account on first use. The lookup is a narrow SECURITY DEFINER function
  (`app_resolve_identity`), because under RLS the runtime role can't see other accounts.
* Only `DemoIdentityProvider` ships (a fresh private account per sign-in). A production OIDC
  provider plugs in with no schema change. ADAPT never acts as, or collects credentials for,
  UAE PASS.

## 7. Privacy boundaries and security

| Requirement | Implementation |
|---|---|
| Never expose `OPENAI_API_KEY` | `SecretStr` in settings. The browser only ever receives ephemeral voice secrets. The log filter masks `sk-…` keys. A test asserts that no public response contains the configured key. |
| Validate user ownership | RLS on every private table and on accounts (transaction-local `app.user_id` / `app.tenant_id`). Services also filter on `user_id`. Other users' resources return 404 (API tests). |
| Never return another user's graph | user-graph RLS, the edge trigger, repository filters. Tests cover unfiltered queries, forged ownership, cross-user links and API responses. |
| Signed/private document access | `app/core/signing.py`: document content needs the owner's session **and** an HMAC signature bound to user + document + expiry (default 5 minutes), from a key derived from the session secret with a purpose label. Documents are Fernet-encrypted at rest. |
| Don't log raw passport content or full document bodies | Logs carry IDs. `RedactingFilter` on every handler masks sensitive keys (passport_number, date_of_birth, content, body, prompt, …), MRZ lines, Emirates ID numbers, e-mail addresses, JWTs and API keys, in messages, args and `extra` fields. Bytes are logged as their length. |
| Redact sensitive data in request logging | ADAPT's access log (`adapt.access`) records method, path, **redacted** query (e.g. `sig=[REDACTED]`), status and duration: never headers, cookies or bodies. Uvicorn's raw access log is disabled. |
| Faith and sensitive attributes | Faith preferences need explicit opt-in (422 `faith_consent_required` otherwise), are user-stated only (DB CHECK), and are deleted when consent is withdrawn. Faith communities/events are listed only after opt-in. |
| Account deletion | `DELETE /api/me` removes the tenant; FKs cascade every private row. |

## 8. Migrations

| Revision | Content | Owner |
|---|---|---|
| `0001` | foundation schema (frozen: it keeps its own copies of the SQL it used) | backend |
| `0002` | domain model v2: spec graph columns, governance corpus, private domain tables, catalogue, account RLS, action-approval trigger, identity lookup | backend |
| `0003_research` | research_jobs, research_results, research_citations | research |
| `0004_user_data` | user_documents, extracted_facts, review_tasks; moves user-node facts into extracted_facts | documents |
| `0005_research_fact_ids` | research_results.fact_ids | research |

`0002` drops the foundation's provisional private tables and both graphs (demo data only;
accounts are kept) and rebuilds them. Its downgrade restores `0001`'s schema by calling that
revision's `create_content_tables()` / `secure_content_tables()`. The integration suite runs
`downgrade base` → `upgrade head` at the start of every session, so every downgrade path is
exercised. `alembic check` reports no drift between the models and the migrated schema.

New private tables: create them in a new revision, call `rls.private_table_sql(table)`, and
list them in `PRIVATE_TABLES` (feature models modules export their own tuple). A test
compares the list with the live policies.

## 9. Seed data

`python -m app.seed` (run by the `migrate` compose service; idempotent):

1. **Governance knowledge.** The knowledge layer's cited corpus and graph
   (`app.knowledge.seed.seed_knowledge`). It falls back to the interim
   `app/seed/governance.yaml` only if the knowledge graph file is missing.
2. **Discover catalogue.** `app/seed/catalogue.yaml` (curated and URL-verified by the research
   workstream). `official_guidance` is kept only for official domains; anything else is stored
   as `community_web`.
3. **The fictional demo household** (`app/seed/demo.py`, `--no-demo` to skip). Arjun Mehta
   (founder of Mehta Analytics Ltd, setting up in ADGM), his wife Priya and daughter Aanya,
   who join later. The seed covers the profile, household, goals and preferences, then uploads
   five SPECIMEN documents (passport, marriage certificate, ADGM licence, salary certificate,
   tenancy contract) through the real encrypted storage and reading pipeline, offline. The
   journey (22 steps), its plan snapshot, the draft cover letter, the prepared actions and the
   run's event log come from running the journey agent's own nodes in scripted mode, so
   What-if works on it. It also has two planned (not booked) appointments. The shared account
   has fixed ids and is rebuilt on every run. Sign in with
   `POST /api/auth/demo-session {"sample_household": true}`, or set
   `DEMO_SEED_SAMPLE_HOUSEHOLD=true` so every new demo account starts as a copy.

No real personal data is used. Nothing claims external success: actions are prepared or
awaiting approval, and appointments are only planned.

## 10. Tests

Backend-owned suites (the other workstreams' suites live next to them):

| Suite | Covers |
|---|---|
| `tests/integration/test_isolation.py` | **user isolation** and **graph isolation**: RLS policy coverage, accounts invisible to others, unfiltered queries, forged ownership, cross-user links, governance/user edge rules, run and event privacy, account deletion cascade, API 401/404s for other users' resources |
| `tests/integration/test_rag.py` | **RAG retrieval**: nearest passage first, citation fields and generated `page_or_section`, authority filter, embedder isolation, superseded versions excluded, lexical search, corpus write denial |
| `tests/integration/test_journeys_and_approvals.py` | **journey creation** (storage round trip, same-journey edges, add-node helper, the seeded plan ordered by dependencies with blockers) and **approval states** (pending/rejected can't authorise, approved can, decided_at consistency, one approval per action, NULL-safe honesty CHECKs, simulated adapters) |
| `tests/integration/test_documents_and_discover.py` | **generated-document lifecycle** (draft → approve with edits → idempotent → no discard; discard → no approve; other users 404), appointment preparation (checklist + brief, never booked), faith opt-in for catalogue and preferences |
| `tests/integration/test_event_log.py` | event sequencing, flat JSON format, JSON replay, SSE replay and live delivery, **WebSocket** stream and its rejections, agent start + input validation |
| `tests/unit/test_security.py` | redaction (keys, MRZ, Emirates ID, nested fields, log records), signed document links, no API-key leakage |
| `tests/unit/test_agents_and_events.py`, `test_graph_and_seed.py`, `test_platform.py`, `test_trust_rules.py` | event contract, instrumentation and interrupts, graph rules, seed files, settings, sessions, adapters, OpenAPI freshness, provenance |

The *uploaded*-document lifecycle (upload → process → review → confirm → delete) is tested by
the documents workstream (`tests/integration/test_document_pipeline.py`).

Run the integration tests against your own database, because the suite resets the schema:

```bash
ADAPT_TEST_DATABASE_URL=postgresql+psycopg://adapt_app:adapt_app@127.0.0.1:55432/adapt_test_<you> \
ADAPT_TEST_OWNER_DATABASE_URL=postgresql+psycopg://adapt:adapt@127.0.0.1:55432/adapt_test_<you> \
uv run pytest tests/integration
```

Create the database once with `docker exec adapt-postgres-1 psql -U adapt -c "CREATE DATABASE
adapt_test_<you>"`, then run `CREATE EXTENSION vector` inside it and grant `CONNECT` plus
schema `USAGE` to `adapt_app`, as in `infra/postgres/init/01-roles.sh`.

## 11. Extending the backend

* **New agent:** `register_agent(AgentSpec(name, kind, job, input_model, description))` in
  a module that the API router or worker imports, and add the job to `_FEATURE_JOBS` in
  `app/workers/settings.py`.
* **New feature router:** expose `router` in your package and add the module name in
  `app/api/router.py`.
* **New feature tables:** a `models` module listed in `app/db/models/__init__.py`
  (`_FEATURE_MODEL_MODULES`) that exports `PRIVATE_TABLES`, plus your own revision.
* **Contracts:** after changing any Pydantic model used by a route, run
  `npm run contracts:generate` from the repository root; `test_generated_contract_is_up_to_date`
  fails until you do.
