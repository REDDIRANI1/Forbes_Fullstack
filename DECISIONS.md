# Decisions

Design and implementation choices for this submission, with short rationale.  
Only decisions reflected in the running code are listed here.

## Scope and delivery

- **Dashboard is required for submission.**  
  The technical brief marks the Next.js frontend as optional, but the submission brief requires a reviewer to open a dashboard at `localhost:3000` within two minutes of cloning. The dashboard is therefore implemented and wired to the real API.

- **Local Docker Compose is the primary demo path.**  
  Standard Docker Compose is used so any compatible Docker runtime can run the stack. Live cloud deployment is optional and is not required to review the work.

- **Initial seed is manual (`make seed`).**  
  Importing ~1,000,000 rows on container start would block the two-minute dashboard target. Reviewers start Compose first, then run `make seed` (or `python manage.py seed_data`) when ready. The README documents the command.

## Data source and ingestion

- **Parquet is the primary data source.**  
  The supplied Snappy Parquet file is loaded via `python manage.py seed_data`.

- **HTTP adapter exists only to satisfy the HTTP requirement.**  
  A small `HttpRateSource` demonstrates timeouts, error handling, partial responses, and a mocked pytest path. It is not backed by a live external rate feed; Parquet remains the real source.

- **Source profile (from a read-only scan).**  
  - 1,005,000 rows in 21 row groups (20 × 50,000 + 5,000)  
  - Columns: `provider`, `rate_type`, `rate_value`, `effective_date`, `ingestion_ts`, `source_url`, `raw_response_id`, `currency`  
  - 200 null rates, 15 non-positive rates; required provider/type/date/timestamp fields are never null  
  - Provider casing varies (`HSBC` / `Hsbc` / `hsbc`); currency varies (`USD` / `usd` / `US Dollar`)  
  - Last 5,000 rows include 46 case-folded keys already seen earlier in the file  

- **Normalization rules.**  
  - Provider names: trimmed and case-folded  
  - Rate types: trimmed  
  - Rate values: `Decimal(9,4)`; non-positive values rejected (observed range 3.5–97.3949, ≤4 decimal places)  
  - `ingestion_ts`: timezone-naive in Parquet → treated as UTC  
  - `effective_date`: stored as a calendar date  
  - Raw payloads keep original variants for audit/replay  

- **Duplicate definition.**  
  A normalized fact is unique on  
  `(case-folded provider_name, rate_type, effective_date, rate_value)`.  
  Retries of the same fact are rejected; a genuine same-day change with a different value is kept. Every source row is also stored as raw JSON with a unique `(batch, source_row_number)` position.

- **Idempotent batch ingestion.**  
  - Batch identity = content hash of the Parquet file (1 MiB chunks)  
  - Read ≤5,000 rows per batch; one DB transaction per batch  
  - Raw rows use conflict-safe insert on `(batch, source_row_number)`  
  - Normalized facts use the unique constraint above  
  - Rerun reuses the same batch, keeps original raw rows, and reports normalized rows as skipped  
  - Parse failures (null/non-positive rates, etc.) are stored as `failed` raw records with an error message  
  - Unrecoverable source/DB errors mark the batch failed and fail the command  

- **Observed full-file seed result.**  
  | Run | Raw rows | Normalized created | Skipped | Parse failures |
  | --- | ---: | ---: | ---: | ---: |
  | First seed | 1,005,000 | 999,096 | 5,689 | 215 |
  | Immediate repeat | 0 new | 0 | 1,004,785 valid | same 215 retained |

- **HTTP adapter behavior.**  
  Explicit timeout; request/status/JSON failures surface as source errors; partial responses still accept the available `records` list so malformed rows can be retained for replay.

## API, cache, and product semantics

- **`GET /rates/latest`.**  
  - No `type`: one latest record per provider across all rate types  
  - With `?type=`: filter by validated type first, then one latest per provider  
  - “Latest” order: `effective_date` → ingestion timestamp → id (all descending)  
  - Response includes the selected record’s rate type  

- **Cache.**  
  - TTL 60s under `rates:latest:all` or `rates:latest:type:<type>`  
  - `type` is normalized/validated before use as a cache key (1–64 chars; letters, numbers, spaces, `_`, `-`; blank rejected)  
  - Successful webhook insert invalidates the all-types key and that record’s type key  
  - Successful Parquet ingestion that creates normalized rows invalidates the all-types key and every rate type present in the batch  

- **History and options.**  
  - History: default page size 50; requires provider and type  
  - `GET /rates/options`: distinct provider/type pairs for dashboard selectors (not limited to the one-latest-per-provider table)  



## Architecture and operations

- **Stack.**  
  Django + Django REST Framework + PostgreSQL; Redis for cache and Celery; Next.js dashboard; PyArrow for batched Parquet reads (not full-file load into memory).

- **Scheduling.**  
  Celery worker + Celery Beat run ingestion hourly inside Compose (no host cron).  
  Overlap control: Redis `SET NX` lock, UUID token, 90-minute lease, renew every 5 minutes while owned, release via compare-and-delete Lua script. If the lock is held, the task returns `skipped_overlap`.

- **Startup and migrations.**  
  Only the API container runs `migrate`, after checking PostgreSQL and Redis. Migrations re-run on each API start (idempotent). Worker, Beat, and web wait until the API health endpoint reports dependencies ready.

- **Dashboard behavior.**  
  Polls every 60 seconds; refetches `/rates/latest` and the selected 30-day history without a full page reload. Provider/type dropdowns use `/rates/options`; changing provider clamps rate type to a valid pair.

- **Observability (time-boxed).**  
  Structured JSON logging was deferred after required scope. API and worker use standard application logging; `print()` is avoided on production paths.

## Known tradeoffs / follow-ups

- **Redis lease vs durable job orchestration.**  
  The 48-hour assessment window favors an owned Redis lease over a full job-runner. With more time: durable run/lease + heartbeat recovery for mid-run worker failure.

- **Case-folded provider labels vs registry.**  
  Display names are case-folded for identity. With more time: a provider registry of official names and aliases for cleaner presentation.
