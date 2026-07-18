# Decisions

Engineering choices reflected in the running code. This file is the assessment-required record of assumptions, idempotency, tradeoffs, and follow-ups — not a second README.

## Assumptions

These shaped the design and are the main things a production engineer would verify before deploy:

- **Seed file is the real assessment source.** The supplied Snappy Parquet file (`forbes_docs/rates_seed.parquet`) is loaded via `python manage.py seed_data`. There is no live external rate feed.
- **HTTP requirement is demonstrated separately.** A small `HttpRateSource` covers timeouts, errors, partial responses, and a mocked pytest path. It is not the primary production path.
- **~1M-row import must not block first paint.** Reviewers need the dashboard at `localhost:3000` within two minutes of cloning. Seeding is therefore manual (`make seed`) after Compose is up; Celery Beat still schedules the same path hourly afterward.
- **Source profile (read-only scan).**
  - 1,005,000 rows in 21 row groups (20 × 50,000 + 5,000)
  - Columns: `provider`, `rate_type`, `rate_value`, `effective_date`, `ingestion_ts`, `source_url`, `raw_response_id`, `currency`
  - 200 null rates, 15 non-positive rates; required provider/type/date/timestamp fields are never null
  - Provider casing varies (`HSBC` / `Hsbc` / `hsbc`); currency varies (`USD` / `usd` / `US Dollar`)
  - Last 5,000 rows include 46 case-folded keys already seen earlier in the file
- **Normalization.**
  - Provider names: trimmed and case-folded for identity
  - Rate types: trimmed
  - Rate values: `Decimal(9,4)`; non-positive rejected (observed range 3.5–97.3949, ≤4 decimal places)
  - Timezone-naive Parquet `ingestion_ts` treated as UTC; `effective_date` kept as a calendar date
  - Raw JSON retains original spelling/variants for audit and replay
- **“Latest” rate.** Ordered by `effective_date`, then ingestion timestamp, then id (all descending). Without `?type=`, one row per provider across all types; with type filter, one row per provider for that type.
- **30-day change.** For a provider + rate type, compare the latest effective rate with the most recent record whose effective date is on or before 30 calendar days before that latest date. Return `null` if no baseline exists.
- **Dashboard is delivery-critical.** The technical brief labels Next.js optional, but the submission brief requires `localhost:3000` within two minutes, so the dashboard is implemented against the real API.

## Idempotency strategy

How the worker handles the seed file’s data issues (nulls, non-positive rates, casing variants, duplicates, reruns):

1. **Batch identity** — hash Parquet bytes in 1 MiB chunks. The same file always maps to the same batch.
2. **Bounded reads** — PyArrow record batches of ≤5,000 rows; one DB transaction per batch (never load ~1M rows into Python memory).
3. **Raw first** — every source row is stored as JSON with unique `(batch, source_row_number)`. Failed parses stay as `failed` raw rows with an error message so they can be replayed.
4. **Normalized fact uniqueness** —  
   `(case-folded provider_name, rate_type, effective_date, rate_value)`  
   - Same fact on retry → skipped (no duplicate)  
   - Same provider/type/date with a **different** value → kept (genuine same-day change)
5. **Rerun behavior** — reuses the batch, keeps original raw rows, reports normalized rows as skipped instead of inserting again.
6. **Hard failures** — unrecoverable source/DB errors mark the batch failed and fail the command (no silent crash).
7. **Scheduler overlap** — Celery Beat hourly; Redis `SET NX` lock with UUID token, 90-minute lease, 5-minute renew, compare-and-delete Lua release. Concurrent run returns `skipped_overlap`.

**Observed full-file result**

| Run | Raw rows | Normalized created | Skipped | Parse failures |
| --- | ---: | ---: | ---: | ---: |
| First seed | 1,005,000 | 999,096 | 5,689 | 215 |
| Immediate repeat | 0 new | 0 | 1,004,785 valid | same 215 retained |

## Conscious tradeoff (48-hour window)

**Chose: owned Redis lease for scheduled ingestion**  
**Over: durable job orchestration (DB-backed run records, external queue leases, full heartbeat recovery UI)**

Why: Compose + Celery Beat + a tokenized Redis lock is enough to prevent overlapping million-row imports locally, ship within the assessment window, and keep the stack reviewable with one `docker-compose up`. A durable runner would improve mid-run worker-failure recovery and operational visibility, but would not change the core product demo.

Related product tradeoffs made for the same reason:

- Manual first seed vs auto-seed on boot (protects the two-minute dashboard requirement)
- Case-folded provider labels vs a full provider registry (correct identity now; prettier display later)
- Standard app logging vs structured JSON observability stub (required scope first)

## One thing I would change with more time

**Replace dashboard polling with a lightweight WebSocket (or SSE) push for latest-rate updates**, while keeping the REST endpoints for history, options, and webhook ingest.

Why: the UI already refetches `/rates/latest` and selected history every 60 seconds. After webhook ingest or a finished seed batch, clients wait up to a full poll interval even though the server already invalidated Redis. A push channel tied to those invalidation events would cut stale-window latency, reduce empty poll traffic, and better match a production Marketplace-style refresh loop. Polling remains a fine fallback for simple deploys.

Also with more time: a provider registry (official names + aliases) and durable run/lease records with heartbeat recovery for worker death mid-import.

## API, cache, and operations (supporting detail)

- **`GET /rates/latest`** — cached 60s under `rates:latest:all` or `rates:latest:type:<type>`. `type` validated before use as a cache key (1–64 chars; letters, numbers, spaces, `_`, `-`). Webhook success deletes all-types + that type key; Parquet success that creates rows invalidates all-types + every type present in the batch.
- **`GET /rates/history`** — paginated (default 50); requires provider + type; supports date bounds; never unbounded.
- **`GET /rates/options`** — distinct provider/type pairs for dashboard selectors.
- **`POST /rates/ingest`** — bearer token; strict validation; structured errors; cache invalidation on success.
- **Stack** — Django + DRF + PostgreSQL; Redis cache/broker; Celery worker + Beat; Next.js; PyArrow batches.
- **Startup** — only API runs `migrate` after PostgreSQL/Redis checks; worker/Beat/web wait on API health.
- **Dashboard** — real API only; comparison table; 30-day chart; 60s refresh without full reload; loading/error states; responsive layout. On first load (empty selection), the UI prefers a seed pair known to have a multi-point 30-day window (`bank of america` / `savings_easy_access`, then similar savings pairs) so reviewers see a real line chart without hunting; user selections still win afterward.
