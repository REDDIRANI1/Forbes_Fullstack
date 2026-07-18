import logging
import threading
import uuid

import redis
from celery import shared_task
from django.conf import settings

from rates.ingestion import IngestionAbortedError, ingest_parquet

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
        try:
            renewed = client.eval(_RENEW_LOCK_SCRIPT, 1, SEED_LOCK_KEY, token, SEED_LOCK_TTL_SECONDS)
        except Exception:
            logger.exception("scheduled ingestion lock renewal raised; treating as ownership loss")
            aborted.set()
            stop.set()
            return
        if not renewed:
            logger.warning("scheduled ingestion lock renewal failed; ownership was lost")
            aborted.set()
            stop.set()
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

    def _check_ownership() -> bool:
        """Live ownership check: verifies the Redis key still holds our token.

        Called at each Parquet batch boundary.  Checks the renewal thread's
        signal first (cheap) and falls back to a Redis GET so that ownership
        loss is detected even between 5-minute renewal cycles.
        """
        if lock_stolen.is_set():
            return False
        try:
            still_ours = client.get(SEED_LOCK_KEY) == token
        except Exception:
            logger.exception("ownership check could not reach Redis; assuming loss")
            still_ours = False
        if not still_ours:
            lock_stolen.set()
        return still_ours

    try:
        batch, summary = ingest_parquet("/data/rates_seed.parquet", is_owner=_check_ownership)

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
    except IngestionAbortedError:
        logger.critical(
            "scheduled ingestion aborted mid-flight because ownership was lost"
        )
        return {"status": "lock_stolen", "created": 0}
    finally:
        stop_renewal.set()
        renewal_thread.join(timeout=1)
        if not lock_stolen.is_set():
            # Only release the lock when we still own it; the Lua guard would
            # make a release on a stolen lock a no-op, but being explicit avoids
            # accidentally deleting a key that now belongs to another worker.
            client.eval(_RELEASE_LOCK_SCRIPT, 1, SEED_LOCK_KEY, token)
