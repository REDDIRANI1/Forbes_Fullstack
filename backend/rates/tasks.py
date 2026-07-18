import logging
import threading
import uuid

import redis
from celery import shared_task
from django.conf import settings

from rates.ingestion import ingest_parquet

logger = logging.getLogger(__name__)
SEED_LOCK_KEY = "rates:seed:lock"
SEED_LOCK_TTL_SECONDS = 90 * 60
SEED_LOCK_RENEW_SECONDS = 5 * 60

_RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""
_RENEW_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""


def _redis_client():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _renew_lock_until_stopped(
    client, token: str, stop: threading.Event, aborted: threading.Event
) -> None:
    while not stop.wait(SEED_LOCK_RENEW_SECONDS):
        renewed = client.eval(_RENEW_LOCK_SCRIPT, 1, SEED_LOCK_KEY, token, SEED_LOCK_TTL_SECONDS)
        if not renewed:
            logger.warning("scheduled ingestion lock renewal failed; ownership was lost")
            aborted.set()  # signal main thread that the lock was stolen
            stop.set()     # exit the renewal loop
            return


@shared_task
def scheduled_seed_data():
    token = uuid.uuid4().hex
    client = _redis_client()
    acquired = client.set(SEED_LOCK_KEY, token, nx=True, ex=SEED_LOCK_TTL_SECONDS)
    if not acquired:
        logger.warning("scheduled ingestion skipped because another run is active")
        return {"status": "skipped_overlap"}

    stop_renewal = threading.Event()
    lock_stolen = threading.Event()
    renewal_thread = threading.Thread(
        target=_renew_lock_until_stopped,
        args=(client, token, stop_renewal, lock_stolen),
        daemon=True,
    )
    renewal_thread.start()
    try:
        batch, summary = ingest_parquet("/data/rates_seed.parquet")

        if lock_stolen.is_set():
            logger.critical(
                "scheduled ingestion completed but Redis lock was stolen mid-flight; "
                "a duplicate import may have run — batch=%s created=%s",
                batch.id,
                summary.created,
            )
            return {"status": "lock_stolen", "created": summary.created}

        logger.info("scheduled ingestion complete batch=%s created=%s", batch.id, summary.created)
        return {"status": batch.status, "created": summary.created}
    finally:
        stop_renewal.set()
        renewal_thread.join(timeout=1)
        if not lock_stolen.is_set():
            # Only release the lock when we still own it; the Lua guard would
            # make a release on a stolen lock a no-op, but being explicit avoids
            # accidentally deleting a key that now belongs to another worker.
            client.eval(_RELEASE_LOCK_SCRIPT, 1, SEED_LOCK_KEY, token)
