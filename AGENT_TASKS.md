# Rate Tracker — Agent Task Pack

Use this file to delegate the assessment in small, one-shot implementation tasks.
Each task is intended for **one agent**, run to completion before starting the next dependent task.

## Coordinator Rules

1. Run the tasks in the listed order. Do not run implementation tasks concurrently in this shared repository; several tasks change the same Django settings, Docker, migrations, and documentation files.
2. Before working, every agent must read `AGENTS.md`, `IMPLEMENTATION_PLAN.md`, and the two files in `forbes_docs/`.
3. Preserve existing user changes. Do not revert, delete, reformat, or stage unrelated files.
4. Make only the changes within the assigned task. Use Django migrations rather than raw SQL schema dumps.
5. Run the task's verification commands where possible. Report the files changed, commands run, results, and any blocker.
6. Maintain the root-level `DECISIONS.md` during implementation. When a task makes a material assumption, architectural choice, tradeoff, idempotency decision, scheduler choice, cache strategy, or future-improvement decision, update the file in the same task. Record only decisions supported by the current code and documentation; never invent decisions.
7. Do **not** create a commit unless the coordinator explicitly asks. If asked to commit, use only `./commit-as-rrr.sh`; never run `git commit` directly. Keep commits local: do not create a remote repository, run `git push`, or grant repository access unless the user explicitly directs it.
8. Do not invent a live rate-data source or put secrets in the repository. The supplied Parquet file is the assessment data source.

## Shared Product Decisions

- Backend: Django + Django REST Framework.
- Database: PostgreSQL.
- Cache and Celery broker: Redis.
- Scheduler: Celery Beat, running in Docker Compose.
- Parquet reader: PyArrow using record batches.
- Frontend: Next.js connected to the real Django API.
- The dashboard is treated as required for a safe submission because the submission instructions require `localhost:3000`, even though the technical brief labels the frontend bonus work.
- A clean clone must work with the exact documented `docker-compose up` command and expose the dashboard within two minutes.

## Task 00 — Reconcile the Plan With the Brief

**Depends on:** nothing
**Purpose:** Correct delivery-risk wording before code work starts.
**Status:** completed during planning review; rerun only if the brief or plan changes.

### Agent prompt

> Read `IMPLEMENTATION_PLAN.md`, `forbes_docs/Sr-Full stack developer assessment brief.docx`, and `forbes_docs/Rate-Tracker.docx`. Verify that the plan accurately reflects every requirement. In particular, verify dashboard delivery, the exact `docker-compose up` command, automatic migrations/readiness from an empty database, manual seed-data profiling, optional observability, and conditional remote-submission handoff. Correct only any remaining inconsistency. Preserve the plan’s existing structure and keep changes concise. Run `git diff --check` and report the changed sections. Do not commit, create a remote, grant access, or push.

### Acceptance checks

- Dashboard language no longer suggests it can be skipped for final delivery.
- Final verification contains only an authorization-gated remote handoff procedure and includes the video link.
- The exact fresh-clone Compose command is stated consistently.
- Seed-data profiling is explicitly planned.
- The clean-start workflow applies migrations and verifies API readiness before the dashboard is treated as available.

## Task 01 — Django Foundation and Local Stack

**Depends on:** Task 00
**Owns:** Django scaffold, dependency manifests, Docker files, environment configuration, Makefile/scripts.

### Agent prompt

> Implement the project foundation described in `IMPLEMENTATION_PLAN.md`. Create a Django + DRF backend and Docker Compose services for Django API, PostgreSQL, Redis, Celery worker, Celery Beat, and the Next.js web application. Add `.env.example` with documented non-secret placeholders and fail-fast settings validation with clear errors. Add health checks for PostgreSQL, Redis, and API. On every startup, the API must wait for PostgreSQL and run Django migrations idempotently before serving requests; only the API service may run migrations. Expose API health only when PostgreSQL and Redis are usable, and make worker, Beat, and web wait for API health. Add a Makefile or scripts for startup, seed, tests, and logs. Ensure the documented exact `docker-compose up` command works from a clean clone with an empty database volume. Do not implement domain models, endpoints, or frontend screens yet. Run syntax/configuration checks that do not require the full app to be complete; run `git diff --check`. Do not commit.

### Acceptance checks

- `docker-compose.yml` contains `api`, `db`, `redis`, `worker`, `beat`, and `web` services.
- `.env.example` has no real credentials and documents every variable.
- Missing mandatory configuration produces a clear startup error.
- On every startup, `docker-compose up` idempotently applies pending migrations through the API service and reports healthy API readiness before worker, Beat, and web start.
- Startup, seed, test, and log commands are available.

## Task 02 — Profile Data, Model It, and Document the Schema

**Depends on:** Task 01
**Owns:** seed-data profile notes, Django models/migrations, `schema.md`, initial `DECISIONS.md` assumptions.

### Agent prompt

> Inspect `forbes_docs/rates_seed.parquet` with a bounded-memory/read-only approach. Record its actual columns, representative invalid/duplicate cases, and assumptions needed to ingest it. Implement Django models and migrations for ingestion batches, raw source records, and normalized rate records. Include provider name, rate type, decimal rate value, effective date, and ingestion timestamp. Add constraints and indexes that efficiently support latest rate per provider, 30-day change by type, and a 24-hour ingestion window. Implement and document the agreed 30-day-change lookup: compare a provider/type’s latest effective rate with its most recent rate on or before 30 calendar days earlier, returning `null` without a baseline. Create `schema.md` explaining every table, index, query, and tradeoff. Update the existing `DECISIONS.md` with concrete data assumptions and duplicate-definition rules. Do not implement the importer or API. Run migrations/checks and `git diff --check`. Do not commit.

### Acceptance checks

- The schema uses Django migrations, not raw SQL dumps.
- Raw records retain the original payload and parsing state/error.
- Normalized rate uniqueness makes retries safe without removing legitimate historical changes.
- `schema.md` explicitly maps indexes to all three required queries.
- The actual seed-data issues are documented, not guessed.

## Task 03 — Batch-based, Idempotent Ingestion

**Depends on:** Task 02
**Owns:** ingestion services, `seed_data` command, ingestion tests, source-adapter decision detail.

### Agent prompt

> Implement `python manage.py seed_data` for the supplied Snappy Parquet file. Use PyArrow record batches so approximately one million rows are never loaded into Python memory at once. Persist the raw row before or alongside normalization, validate fields, bulk insert valid records safely, save parse errors, use per-batch transactions, and produce counts for seen/created/duplicate/failed rows. Make reruns idempotent. Create a reusable ingestion service shared by Parquet ingestion and future webhook ingestion. Add a small HTTP source adapter solely to satisfy the brief’s HTTP timeout/error/partial-response requirement; add at least one pytest test mocking the HTTP call and asserting known parsed output. Add command/integration tests using a tiny Parquet fixture and a repeat run. Update `DECISIONS.md` with the exact idempotency and error-handling strategy. Run focused tests and `git diff --check`. Do not commit.

### Acceptance checks

- `python manage.py seed_data` exists and processes Parquet incrementally.
- Invalid records do not crash or silently disappear; they are replayable from raw data.
- Running the command twice creates no duplicate normalized records.
- At least one pytest test mocks the HTTP call and checks parsed fixture output.

## Task 04 — REST API, Bearer Authentication, and Redis Cache

**Depends on:** Task 03
**Owns:** DRF serializers/views/URLs/authentication/cache logic and API integration tests.

### Agent prompt

> Implement the three required DRF endpoints against the existing models and ingestion service: public `GET /rates/latest` with optional `?type=`, public paginated `GET /rates/history` for provider + type with optional `from`/`to`, and bearer-token-protected `POST /rates/ingest`. For latest rates, return one latest record per provider across all rate types when no type is supplied; with `?type=`, filter first and return one latest record per provider for that type. Break ties by effective date, then ingestion timestamp, then record ID, all descending. Use DRF authentication classes, strict serializers that reject malformed and unknown input, structured 400 responses, and 401 for missing/invalid tokens. Cache latest-rate responses in Redis/Django cache and invalidate only affected keys after successful ingestion. Add integration tests with DRF’s client or pytest-django for authentication, validation, pagination, filters, latest-rate selection and tie-breaking, cache hit/invalidation, and idempotent ingest retry. Document endpoint semantics, pagination, and cache invalidation in `DECISIONS.md`. Run focused tests and `git diff --check`. Do not commit.

### Acceptance checks

- Only `POST /rates/ingest` requires a bearer token.
- History endpoint cannot return an unbounded response.
- Latest responses are cached and a successful ingest invalidates the affected cache.
- API test coverage exercises all three endpoints.

## Task 05 — Scheduler, Operations, and Required Documentation

**Depends on:** Task 04
**Owns:** Celery schedule/locking, structured logging, `README.md`, final `DECISIONS.md` content.

### Agent prompt

> Complete the required operational work. Configure Celery Beat to invoke the existing ingestion path on a local-demo schedule through Docker Compose, with overlap protection. Complete `README.md` with prerequisites, exact local startup, seed/test/log commands, API examples, every required environment variable, architecture rationale, and honest incomplete-scope notes if any. Complete `DECISIONS.md` with assumptions, exact idempotency handling for the real seed data, scheduler/cache choices, one 48-hour tradeoff, and one specific improvement with more time. Only after required scope passes, if time permits, add structured JSON logging using the standard logging module for ingestion and API events: job start/end/error and warnings for queries slower than 200ms; do not use `print()` in production paths. Run available checks and `git diff --check`. Do not commit.

### Acceptance checks

- Celery Beat runs locally under Compose and cannot overlap the same job.
- `README.md`, `schema.md`, and `DECISIONS.md` satisfy the briefs’ explicit documentation requirements.
- If observability is implemented, logs are JSON structured for both API and worker paths.

## Task 06 — Real Next.js Dashboard

**Depends on:** Task 04
**Owns:** `web` application implementation, API integration, responsive dashboard tests/checks.

### Agent prompt

> Build the Next.js dashboard using the real Django API—no hardcoded or mocked rate data. At `localhost:3000`, display a sortable latest-rate comparison table (sort by rate value and last-updated date), a selectable provider/type 30-day history line chart, 60-second refresh without a full page reload, and meaningful loading, empty, and error states for every fetch. Ensure it is usable at a 375px viewport. Configure the browser-to-API connection appropriately for Docker and document any public API base URL variable in `.env.example` and README. Run the frontend’s lint/type/build checks and `git diff --check`. Do not commit.

### Acceptance checks

- `docker-compose up` exposes the dashboard at `http://localhost:3000`.
- The table and chart use live Django API responses.
- Sorting, selection, 60-second refresh, loading/error states, and 375px usability are present.

## Task 07 — Fresh-Clone Release Verification

**Depends on:** Tasks 05 and 06
**Owns:** verification-only fixes, final consistency review, release checklist.

### Agent prompt

> Act as the release verifier. Review the whole repository against both assessment documents and `IMPLEMENTATION_PLAN.md`. From a clean, non-destructive state, follow the README exactly: create `.env` from `.env.example`, run the exact documented `docker-compose up`, confirm that migrations were applied automatically, verify dashboard availability at `localhost:3000` within two minutes, run `seed_data` twice, run all tests, exercise all API endpoints including invalid/unauthenticated ingest requests, and confirm cache invalidation and scheduled ingestion. Fix only defects required to make the documented workflow pass. Check that no secrets or assignment DOCX/PDF files are staged, while the required Parquet seed file is available. Update the final checklist in README if needed. Report exact results, remaining limitations, and the screen-recording sequence. Do not commit.

### Acceptance checks

- A reviewer can follow the README successfully from a clean clone.
- All required services start in one Compose command.
- Dashboard, seed command, API behaviour, scheduler, and tests are demonstrably working.
- The report identifies the exact steps for the final video and private-repo reviewer handoff.

## Recommended Handoff Format

Every agent should finish with this compact report:

```text
Task: <ID and title>
Status: completed | blocked
Changed: <files>
Verified: <commands and pass/fail result>
Notes: <assumptions, limitations, or next dependency>
Commit: not created
```

## Final Human-Owned Submission Steps (Only After Explicit Remote Authorization)

After Task 07 passes:

1. Review `git status` and make the intended local commit using only `./commit-as-rrr.sh`.
2. Only after explicit user approval, create a private GitHub repository and grant the requested reviewer collaborator access.
3. Record the required local demo: Compose startup, dashboard, seed command, tests, and repository/docs.
4. Only after explicit user approval, push the repository and submit the repository link and recording link.
