# Rate Tracker — Implementation Plan

## 1. Goal

Build a production-shaped interest-rate tracker in a 48-hour assessment window.

The system should ingest the supplied Parquet data safely, persist both clean and raw records, expose a secure REST API, and run locally with one Docker Compose command. A real Next.js dashboard is delivery-critical for this submission because the submission requirements require a dashboard at `localhost:3000` within two minutes of cloning, despite the technical brief labelling the frontend bonus work.

Maintain a root-level `DECISIONS.md` throughout implementation. Record every material assumption, architectural choice, tradeoff, idempotency decision, scheduler choice, cache strategy, and future improvement when it is actually made. Update it alongside the related code, keep it synchronized with the implementation, and never invent a decision that the code does not reflect.

```text
rates_seed.parquet / webhook payload
        ↓
ingestion service + validation
        ↓
PostgreSQL (raw batches + normalized rates)
        ↓
Django REST API + Redis cache
        ↓
Next.js dashboard
```

## 2. Recommended Stack

| Concern | Choice | Why |
| --- | --- | --- |
| Backend | Django + Django REST Framework | Explicitly requested and strong for migrations, auth, admin, and testing. |
| Database | PostgreSQL | Required-compatible and well suited to indexed time-series queries. |
| Cache | Redis + Django cache framework | Meets the latest-rates caching requirement. |
| Background work | Celery + Celery Beat | Lets the scheduled ingestion run inside Docker Compose. |
| Parquet reading | PyArrow | Supports Snappy-compressed Parquet and batch-based reads. |
| Frontend | Next.js + TypeScript + a chart library | Required for a safe submission because the reviewer must reach `localhost:3000`. |
| Tests | pytest + pytest-django | Concise unit and API integration tests. |
| Local environment | Docker Compose | Required single-command startup. |

## 3. Scope and Priority

Finish work in this order. Do not start a lower-priority item if a higher one is incomplete.

1. Docker, Django, PostgreSQL, Redis, configuration, and migrations.
2. Correct, repeatable Parquet ingestion with raw-record storage.
3. Required API endpoints, auth, cache invalidation, and tests.
4. Scheduler, operational commands, documentation, and clean-start verification.
5. Next.js dashboard, then structured logging bonus work if time permits.

## 4. Phase 0 — Project Foundation

### Steps

1. Create a Django project and a `rates` application.
2. Add dependencies: Django, DRF, psycopg, Celery, Redis client, PyArrow, pytest, pytest-django, and environment-variable support.
3. Add `docker-compose.yml` services for `api`, `db`, `redis`, `worker`, `beat`, and `web`.
4. Add `.env.example` with non-secret placeholder values for database, Redis, Django secret key, debug setting, and ingest bearer token.
5. Validate required environment variables during Django startup with human-readable errors.
6. Add health checks for PostgreSQL, Redis, and the API. On a clean database, the API startup path must wait for PostgreSQL, apply Django migrations, and expose its health check only when ready; worker, Beat, and web must wait for the API to be healthy.
7. Add a `Makefile` or `scripts/` commands for startup, seed, tests, and logs.

### Done when

- From a clean clone with an empty database volume, the exact `docker-compose up` command starts Django, PostgreSQL, Redis, Celery worker, Celery Beat, and Next.js.
- The API applies migrations automatically, then passes its health check after connecting to PostgreSQL and Redis.
- Worker, Beat, and dashboard wait for the functional API; the dashboard can make real API requests within two minutes, even before the manual seed runs.
- Missing required configuration fails immediately with a helpful message.

## 5. Phase 1 — Data Model and Migration

### Proposed tables

#### `ingestion_batches`

Represents one attempt to import data.

- `id` — UUID or bigint primary key
- `source` — e.g. `rates_seed_parquet` or `webhook`
- `source_identifier` — filename, request ID, or content hash
- `started_at`, `finished_at`
- `status` — started, succeeded, partially_succeeded, failed
- `records_seen`, `records_created`, `records_skipped`, `records_failed`
- `error_summary`

#### `raw_rate_records`

Stores the original input so parsing failures can be investigated or replayed.

- `id`
- `batch` — foreign key to `ingestion_batches`
- `source_row_number` or source record ID
- `payload` — JSONB
- `payload_hash`
- `parse_status`
- `parse_error`
- `received_at`

Unique constraint: `(batch, source_row_number)` for safe retries of the same batch.

#### `rate_records`

Normalized, queryable financial-rate facts.

- `id`
- `provider_name`
- `rate_type`
- `rate_value` — fixed precision decimal
- `effective_date`
- `ingested_at`
- `raw_record` — foreign key to `raw_rate_records`

Recommended unique constraint: `(provider_name, rate_type, effective_date, rate_value)`.
This makes reruns safe while preserving distinct rate changes occurring on different effective dates.
Treat this as provisional until seed-data profiling confirms it correctly represents real duplicates and legitimate corrections; record the final implemented rule in `DECISIONS.md`.

### Required indexes

- `(provider_name, rate_type, effective_date DESC)` — history and 30-day change.
- `(rate_type, provider_name, effective_date DESC)` — filtered latest-rate queries.
- `(ingested_at)` — 24-hour ingestion-window queries.
- `(batch_id, parse_status)` on raw records — replay/diagnostic queries.

### Query-semantics decisions

- **Latest rate:** an unfiltered latest-rates response returns one latest record for each `(provider_name, rate_type)` pair. With `?type=<rate_type>`, it returns one latest record per provider for that type. “Latest” is ordered by `effective_date`, then `ingested_at`, then record ID, all descending.
- **30-day change:** for one provider + rate type, compare the latest effective rate with the most recent rate whose effective date is on or before 30 calendar days before that latest date. Return `null` when no baseline record exists. The `(provider_name, rate_type, effective_date DESC)` index supports this lookup.

### Done when

- Django migrations create all tables, constraints, and indexes.
- `schema.md` explains each table and the query/index tradeoffs.
- A duplicate logical rate cannot be inserted twice.

## 6. Phase 2 — Ingestion Pipeline

### Steps

1. Profile the supplied Parquet file with a bounded-memory, read-only inspection. Record its real columns, invalid rows, and duplicate patterns in `DECISIONS.md` before finalizing validation rules.
2. Implement `python manage.py seed_data`; expose the same manual initial-seed operation through `make seed` or an equivalent documented script.
3. Read the Snappy Parquet file using PyArrow in record batches; do not load all ~1M rows into Python memory at once.
4. For every batch:
   - create or resume an `ingestion_batch`;
   - save the raw payload/row first;
   - validate and normalize its fields;
   - bulk insert valid rate records with conflict handling;
   - mark malformed input with a parse error rather than silently discarding it.
5. Use transactions per batch, not one transaction for the full file.
6. Produce a summary: seen, created, skipped as duplicate, and failed.
7. Define a reusable ingestion service so both the Parquet command and webhook use the same validation and persistence logic.

### Initial-seed decision

The initial load is deliberately manual rather than automatic during Docker startup. A million-row import should not delay the requirement to reach the dashboard within two minutes. `README.md` must provide the exact seed command, and `DECISIONS.md` must keep the rationale synchronized with the implementation.

### Provisional idempotency strategy — confirm after profiling

- Give each source run a stable source identifier or content hash.
- Deduplicate raw rows within a batch.
- Use the database unique constraint plus conflict-safe bulk insert for normalized rate records.
- Record errors and continue with later batches when safe.
- Rerunning `seed_data` should produce zero duplicate normalized rows and a clear result summary.

### Important brief ambiguity to document

The brief provides Parquet input but also mentions HTTP error handling and a test that mocks an HTTP call. Treat the ingestion source as an adapter:

- `ParquetRateSource` is the production assessment source.
- `HttpRateSource` is a small, tested adapter/example that demonstrates timeout/error/partial-response handling.
- Both send data to the same parser and persistence service.

This meets the spirit of the brief without pretending the provided Parquet file is an HTTP response.

### Tests

- Parser unit tests: valid source row, missing field, invalid decimal/date.
- Source-client test: mock HTTP success, timeout/error, and partial/malformed response.
- Command/integration test: ingest a tiny Parquet fixture twice and prove no duplicate rates are created.

### Done when

- `python manage.py seed_data` loads the supplied data in bounded memory.
- A rerun is safe and reports duplicates instead of creating them.
- Failed rows are stored with enough raw information to replay them.

## 7. Phase 3 — REST API

### `GET /rates/latest`

- Public endpoint.
- Optional `?type=` filter.
- Without `?type=`, return one latest record for each provider + rate-type pair; with `?type=`, return one latest record per provider for that type.
- Select the latest record by `effective_date`, then `ingested_at`, then record ID, all descending.
- Use a bounded cache key, e.g. `rates:latest:all` or `rates:latest:type:<rate_type>`.
- Invalidate only affected latest-rate cache keys after successful ingestion.

### `GET /rates/history`

- Public endpoint.
- Require `provider` and `type` query parameters.
- Optional ISO date `from` and `to` filters.
- Enforce pagination and a maximum page size.
- Return data in effective-date order with pagination metadata.

### `POST /rates/ingest`

- Require `Authorization: Bearer <token>`.
- Use a strict DRF serializer: reject unknown/malformed fields and return structured `400` errors.
- Reuse the ingestion service, store raw payload, persist validated data, and invalidate relevant cache keys.
- Use `401` for absent/invalid tokens; never convert client validation problems into `500` errors.

### Tests

- Latest endpoint: cache miss/hit, type filter, correct latest selection.
- History endpoint: validation, date filtering, pagination, and no unbounded response.
- Ingest endpoint: unauthenticated rejection, invalid payload errors, valid create, idempotent retry, and cache invalidation.

### Done when

- All three endpoints return documented, stable JSON responses.
- GET is public; only webhook ingest needs bearer auth.
- API integration tests pass against PostgreSQL-compatible behaviour.

## 8. Phase 4 — Scheduled Ingestion and Operations

### Steps

1. Configure Celery Beat to invoke the ingestion task at a reasonable local-demo cadence.
2. Keep the scheduled task thin: it calls the same ingestion service/management command logic.
3. Prevent overlapping scheduled runs using a database or Redis lock.
4. If time permits after required scope, add structured JSON logging via the standard logging module for API and worker paths. Log ingestion job start, finish, counts, and errors; warn for queries over 200ms; use no `print()` calls in production paths.
5. Write `README.md`, `schema.md`, and the root-level `DECISIONS.md` as implementation decisions are made—not at the end. Record only choices actually reflected by the code.

### Required documentation checklist

`README.md`

- Prerequisites
- Exact local startup steps
- Seed, test, and log commands
- Every required environment variable, its purpose, and a non-secret example value
- Why the initial seed is manual
- API endpoint examples
- Non-obvious architecture rationale
- Known incomplete items, if any

`schema.md`

- Tables, relationships, constraints, and indexes
- How each required query is efficient
- Any deliberate schema compromise

`DECISIONS.md`

- Assumptions: source schema, timezone, rate precision, and duplicate definition
- Exact idempotency strategy
- Scheduler choice and cache invalidation design
- One conscious 48-hour tradeoff
- One specific improvement with more time

### Done when

- `docker-compose up` starts the complete required stack.
- Scheduler runs without needing a host-machine cron job.
- A new reviewer can run, seed, test, and inspect logs from the README.

## 9. Phase 5 — Next.js Dashboard (Delivery-Critical)

### Steps

1. Add the `web` service to Docker Compose and expose it at `http://localhost:3000`.
2. Fetch `GET /rates/latest` from the actual Django API.
3. Render a sortable comparison table for provider, rate type, value, and last update.
4. Let the user choose a provider and rate type; fetch 30-day history from `GET /rates/history`.
5. Render a line chart from returned API data.
6. Refresh data every 60 seconds without a full-page reload.
7. Show meaningful loading, empty, and error states for both requests.
8. Verify usability at 375px viewport width.

### Done when

- No dashboard data is hardcoded or mocked.
- The dashboard works at `localhost:3000` after Docker Compose startup.
- The table, chart, refresh, loading/error, and mobile requirements work.

## 10. Final Verification Checklist

- [ ] Clone into a clean directory.
- [ ] Copy `.env.example` to `.env` and use only local placeholder values.
- [ ] From an empty database volume, run the exact `docker-compose up` command from the README.
- [ ] Confirm automatic migrations complete, then the backend and dashboard can make real API requests within two minutes.
- [ ] Run the documented manual seed command (`make seed` or `python manage.py seed_data`).
- [ ] Run the command again and verify idempotency.
- [ ] Run all backend tests.
- [ ] Manually check the three API endpoints, including unauthenticated and invalid ingest requests.
- [ ] Confirm cache invalidation after a successful webhook ingestion.
- [ ] Confirm Celery Beat triggers an ingestion run and overlap protection works.
- [ ] Review all docs for accurate commands and explicit tradeoffs.
- [ ] Record a short video: clean startup, dashboard/API, seed command, tests, and repository/docs.
- [ ] When explicitly authorized, create the private remote repository, grant reviewer access, push the local commits, and submit the repository and video links.

## 11. Suggested 48-Hour Timebox

| Time | Outcome |
| --- | --- |
| Hours 0–3 | Project skeleton, Docker, environment configuration, initial data model. |
| Hours 3–9 | Migrations, batch-based Parquet ingestion, raw records, idempotency tests. |
| Hours 9–15 | REST endpoints, bearer auth, cache behaviour, API integration tests. |
| Hours 15–18 | Celery scheduling, operational scripts, schema documentation. |
| Hours 18–26 | Next.js dashboard connected to the real API. |
| Hours 26–30 | Responsive polish, loading/error states, structured logging bonus. |
| Final time | Fresh-clone verification, documentation review, screen recording, submission. |

## 12. Definition of a Strong Submission

The strongest version is not necessarily the one with the most features. It is one that starts reliably, handles a million-row source safely, cannot create accidental duplicates, has well-tested API behaviour, and clearly explains every non-obvious engineering decision.
