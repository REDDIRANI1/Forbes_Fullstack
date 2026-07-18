# Rate Tracker

## Prerequisites

Docker Desktop or another Docker runtime with Docker Compose v2. Copy the local template once:

```sh
cp .env.example .env
docker-compose up --build
```

The dashboard is at `http://localhost:3000`; the API is at `http://localhost:8000`. The API owns and runs idempotent Django migrations before it becomes healthy. Worker, Beat, and web wait for that health check.

## Commands

```sh
make seed
make test
make lint
make logs
```

`make seed` runs `python manage.py seed_data` against `forbes_docs/rates_seed.parquet`. Seeding is deliberately manual: importing about one million rows would prevent the dashboard from meeting its two-minute startup target.

`make test` runs backend pytest in the API container and the frontend Node test suite in the web container. `make lint` runs `npm run lint` non-interactively in the web container.

## Configuration

| Variable | Purpose | Local example |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Django signing key | `django-insecure-local-development-only-not-a-secret` |
| `DJANGO_DEBUG` | Development error detail | `true` |
| `DJANGO_ALLOWED_HOSTS` | Accepted API hosts | `localhost,127.0.0.1,api` |
| `DATABASE_URL` | PostgreSQL connection | `postgresql://rate_tracker:rate_tracker@db:5432/rate_tracker` |
| `REDIS_URL` | Cache and Celery broker | `redis://redis:6379/0` |
| `INGEST_BEARER_TOKEN` | Webhook bearer token | `local-demo-ingest-token` |
| `NEXT_PUBLIC_API_BASE_URL` | Browser API origin | `http://localhost:8000` |

## API

```sh
curl http://localhost:8000/rates/latest
curl http://localhost:8000/rates/options
curl 'http://localhost:8000/rates/history?provider=bank%20of%20america&type=savings_easy_access&page_size=50'
curl -X POST http://localhost:8000/rates/ingest -H 'Authorization: Bearer local-demo-ingest-token' -H 'Content-Type: application/json' -d '{"provider":"Example","rate_type":"fixed","rate_value":"4.0000","effective_date":"2025-01-01","ingestion_ts":"2025-01-01T00:00:00Z"}'
```

Celery Beat invokes the same seed path hourly. An owned Redis lease with token compare-and-delete prevents overlapping runs and lock theft on late release. Raw source rows are retained for parsing failures and normalized facts are idempotent. The dashboard auto-refreshes latest rates and selected history every 60 seconds; on first load it prefers a dense 30-day provider/type pair when available. See `schema.md` and `DECISIONS.md` for query and tradeoff details.

## Known Limits

The assessment source is static rather than a live provider feed. Structured JSON logging and production deployment are deferred; the API and worker currently use standard application logging.

## Recording Checklist

Record the clean Compose startup, dashboard at `localhost:3000`, a manual seed and repeat seed, API tests, authenticated ingest validation, and the repository documentation. Grant reviewer collaborator access and attach the video link when submitting.
