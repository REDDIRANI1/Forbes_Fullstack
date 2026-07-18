# Decisions

This record contains only decisions that have been made and agreed for the current implementation. It must be updated with the code that implements each decision; proposed ideas are not decisions.

## Scope and delivery

- **Dashboard is delivery-critical.** Although the detailed technical brief labels the Next.js frontend as optional bonus work, the submission brief requires a reviewer to access a dashboard at `localhost:3000` within two minutes of cloning. Therefore, the dashboard will be implemented and connected to the real API for a safe submission.
- **Live deployment is optional.** We will consider deploying only after the required local Docker workflow, tests, documentation, and dashboard are complete. The submission must not depend on a live URL.
- **Use standard Docker Compose in the repository.** The project must use ordinary Docker/Docker Compose configuration that works on any compatible Docker runtime.
- **Keep version control local for now.** Create local commits only when the relevant work is verified and the user authorizes a commit, using `./commit-as-rrr.sh`. Do not create a remote repository, push, or grant reviewer access until the user explicitly directs it.

## Data acquisition and ingestion

- **The supplied Snappy Parquet file is the primary assessment data source.** The required command will be `python manage.py seed_data`.
- **Use a small HTTP source adapter only for the explicit HTTP requirement.** The brief also requires handling HTTP timeouts/errors/partial responses and a pytest test that mocks an HTTP call. The implementation will demonstrate this with a bounded adapter and mocked test, while Parquet remains the real source. It will not invent or depend on an external live rate-data source.
- **Initial seeding is manual.** A reviewer/developer will run `make seed` (or the documented equivalent `python manage.py seed_data`) after starting Docker Compose. This avoids placing a ~1,000,000-row import on the critical startup path and helps keep the dashboard reachable within the two-minute requirement. README will state the command; this file records why it is manual.
- **Final idempotency and invalid-data rules are pending data profiling and implementation.** They must be based on the actual Parquet columns and defects, then recorded here alongside the implemented constraint and retry behavior. Do not claim a duplicate key or handling rule before it exists in code.
- **30-day change definition:** for a provider + rate type, compare the latest effective rate with the most recent record whose effective date is on or before 30 calendar days before the latest effective date. Return `null` when that baseline does not exist.

## Architecture and operations

- **Backend and persistence:** Django with Django REST Framework and PostgreSQL.
- **Latest-rate semantics and caching:** without a type filter, `GET /rates/latest` will return one latest record per provider across all rate types. With `?type=`, it will filter by type first and return one latest record per provider for that type. “Latest” is ordered by effective date, then ingestion timestamp, then record ID, all descending; the response includes the selected record's rate type. Redis will cache the response and a successful ingest will invalidate only the affected latest-rate cache key(s); the exact key format will be recorded when implemented.
- **Scheduling:** Celery worker plus Celery Beat will schedule ingestion locally through Docker Compose. This satisfies the local scheduling requirement without relying on host-machine cron.
- **Migration ownership and readiness:** only the API container runs `migrate`, after actively checking PostgreSQL and Redis. It repeats `migrate` on each API start because Django migrations are idempotent; worker, Beat, and web are held until the API health endpoint proves both dependencies are usable.
- **Parquet processing:** PyArrow will read the file in record batches, rather than loading the full dataset into Python memory.
- **Observability is a time-permitting bonus.** After required scope is working, add structured JSON logging for API and worker paths, including ingestion start/end/error and slow-query warnings. Do not use `print()` in production paths.

## Future improvement

- **No specific future improvement has been selected yet.** Before submission, choose one concrete improvement that reflects the implemented system and explain why it would be valuable. It must not be a generic claim such as “add more tests.”
