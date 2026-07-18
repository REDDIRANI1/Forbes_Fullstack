import threading
import time

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import redis
from django.conf import settings

from rates.ingestion import IngestionAbortedError, ingest_parquet
from rates.models import IngestionBatch, RateRecord, RawRateRecord
from rates.tasks import (
    SEED_LOCK_KEY,
    SEED_LOCK_TTL_SECONDS,
    _RELEASE_LOCK_SCRIPT,
    _RENEW_LOCK_SCRIPT,
    scheduled_seed_data,
)


@pytest.fixture
def redis_client():
    client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    client.delete(SEED_LOCK_KEY)
    yield client
    client.delete(SEED_LOCK_KEY)


@pytest.mark.django_db
def test_scheduled_seed_skips_when_lock_held(redis_client, monkeypatch):
    assert redis_client.set(SEED_LOCK_KEY, "other-owner", nx=True, ex=SEED_LOCK_TTL_SECONDS)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("ingest_parquet should not run while lock is held")

    monkeypatch.setattr("rates.tasks.ingest_parquet", fail_if_called)
    assert scheduled_seed_data() == {"status": "skipped_overlap"}
    assert redis_client.get(SEED_LOCK_KEY) == "other-owner"


@pytest.mark.django_db
def test_scheduled_seed_releases_only_owned_lock(redis_client, monkeypatch):
    def fake_ingest(*args, **kwargs):
        return (type("Batch", (), {"id": "batch", "status": "succeeded"})(), type("Summary", (), {"created": 0})())

    monkeypatch.setattr("rates.tasks.ingest_parquet", fake_ingest)
    result = scheduled_seed_data()
    assert result["status"] == "succeeded"
    assert redis_client.get(SEED_LOCK_KEY) is None


@pytest.mark.django_db
def test_scheduled_seed_does_not_delete_stolen_lock(redis_client, monkeypatch):
    def steal_lock(*args, **kwargs):
        redis_client.set(SEED_LOCK_KEY, "stolen-token", ex=SEED_LOCK_TTL_SECONDS)
        return (type("Batch", (), {"id": "batch", "status": "succeeded"})(), type("Summary", (), {"created": 0})())

    monkeypatch.setattr("rates.tasks.ingest_parquet", steal_lock)
    assert scheduled_seed_data()["status"] == "succeeded"
    assert redis_client.get(SEED_LOCK_KEY) == "stolen-token"
    redis_client.eval(_RELEASE_LOCK_SCRIPT, 1, SEED_LOCK_KEY, "stolen-token")


@pytest.mark.django_db
def test_scheduled_seed_renews_owned_lock(redis_client, monkeypatch):
    renewed = threading.Event()
    original_eval = redis.Redis.eval

    def tracking_eval(self, script, numkeys, *keys_and_args):
        result = original_eval(self, script, numkeys, *keys_and_args)
        if "expire" in script and result:
            renewed.set()
        return result

    monkeypatch.setattr(redis.Redis, "eval", tracking_eval)
    monkeypatch.setattr("rates.tasks.SEED_LOCK_RENEW_SECONDS", 0.05)

    def slow_ingest(*args, **kwargs):
        deadline = time.time() + 2
        while time.time() < deadline and not renewed.is_set():
            time.sleep(0.02)
        assert renewed.is_set()
        ttl = redis_client.ttl(SEED_LOCK_KEY)
        assert ttl is not None and ttl > 0
        return (type("Batch", (), {"id": "batch", "status": "succeeded"})(), type("Summary", (), {"created": 0})())

    monkeypatch.setattr("rates.tasks.ingest_parquet", slow_ingest)
    assert scheduled_seed_data()["status"] == "succeeded"
    assert redis_client.get(SEED_LOCK_KEY) is None


@pytest.mark.django_db
def test_scheduled_seed_aborts_import_on_ownership_loss(redis_client, monkeypatch, tmp_path):
    """Exercises the real scheduled_seed_data → ingest_parquet pipeline.

    A tiny two-batch Parquet file is created.  After the first batch is
    persisted, we overwrite the Redis lock key to simulate another worker
    stealing the lease.  At the next batch boundary, ingest_parquet's
    is_owner callback (which does a live Redis GET) returns False and
    raises IngestionAbortedError.  The task catches this and returns
    {"status": "lock_stolen"}.  We assert the second batch was never
    persisted and the new owner's key was not deleted.
    """
    # Build a Parquet file with 4 rows.  We use batch_size=2 to get two
    # iter_batches iterations and therefore two ownership checks.
    rows = [
        {
            "provider": f"Provider{i}",
            "rate_type": "savings_1yr_fixed",
            "rate_value": 4.0 + i * 0.1,
            "effective_date": f"2025-01-{10 + i:02d}",
            "ingestion_ts": "2025-01-10T12:00:00",
        }
        for i in range(4)
    ]
    parquet_path = tmp_path / "rates.parquet"
    pq.write_table(pa.Table.from_pylist(rows), parquet_path, compression="snappy")

    first_batch_done = threading.Event()
    original_persist = None

    # Track persist_records calls so we can steal the lock right after batch 1.
    import rates.ingestion as ingestion_module
    original_persist = ingestion_module.persist_records

    persist_call_count = 0

    def intercepting_persist(batch, rows_iter):
        nonlocal persist_call_count
        persist_call_count += 1
        result = original_persist(batch, rows_iter)
        if persist_call_count == 1:
            # After the first batch is persisted, simulate lock theft.
            redis_client.set(SEED_LOCK_KEY, "new-owner-token", ex=SEED_LOCK_TTL_SECONDS)
            first_batch_done.set()
        return result

    monkeypatch.setattr("rates.ingestion.persist_records", intercepting_persist)

    # Use batch_size=2 to force two iterations, and point at our temp file.
    monkeypatch.setattr(
        "rates.tasks.ingest_parquet",
        lambda path, is_owner=None: ingest_parquet(parquet_path, batch_size=2, is_owner=is_owner),
    )

    # Suppress the renewal thread (we don't need it; the live Redis GET is the detection mechanism).
    monkeypatch.setattr("rates.tasks.SEED_LOCK_RENEW_SECONDS", 999)

    result = scheduled_seed_data()

    # ---- Assertions ----
    # 1. Task must report lock_stolen.
    assert result["status"] == "lock_stolen", f"Expected lock_stolen, got {result}"

    # 2. The new owner's Redis key must still be intact.
    assert redis_client.get(SEED_LOCK_KEY) == "new-owner-token"

    # 3. Only the first batch's rows (2 rows) should be persisted;
    #    the second batch (2 rows) should never have been written.
    assert persist_call_count == 1, (
        f"persist_records should have been called once (first batch only), got {persist_call_count}"
    )

    # Clean up the new owner's key.
    redis_client.delete(SEED_LOCK_KEY)


@pytest.mark.django_db
def test_renewal_thread_handles_redis_errors(redis_client, monkeypatch):
    """If Redis raises during renewal, the thread must set aborted."""
    from rates.tasks import _renew_lock_until_stopped

    stop = threading.Event()
    aborted = threading.Event()

    failing_client = type("FailClient", (), {
        "eval": staticmethod(lambda *args, **kwargs: (_ for _ in ()).throw(redis.ConnectionError("boom"))),
    })()

    monkeypatch.setattr("rates.tasks.SEED_LOCK_RENEW_SECONDS", 0.01)
    thread = threading.Thread(
        target=_renew_lock_until_stopped,
        args=(failing_client, "any-token", stop, aborted),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=2)
    assert aborted.is_set(), "aborted must be set when Redis raises during renewal"
    assert stop.is_set(), "stop must be set when Redis raises during renewal"
