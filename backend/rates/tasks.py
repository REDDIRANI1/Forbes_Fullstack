import logging

from celery import shared_task
from django.core.cache import cache

from rates.ingestion import ingest_parquet

logger = logging.getLogger(__name__)
SEED_LOCK_KEY = "rates:seed:lock"


@shared_task
def scheduled_seed_data():
    if not cache.add(SEED_LOCK_KEY, "locked", timeout=60 * 60):
        logger.warning("scheduled ingestion skipped because another run is active")
        return {"status": "skipped_overlap"}
    try:
        batch, summary = ingest_parquet("/data/rates_seed.parquet")
        logger.info("scheduled ingestion complete batch=%s created=%s", batch.id, summary.created)
        return {"status": batch.status, "created": summary.created}
    finally:
        cache.delete(SEED_LOCK_KEY)
