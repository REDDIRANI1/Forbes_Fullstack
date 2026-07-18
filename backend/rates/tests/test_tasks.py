import threading
import time

import pytest
import redis
from django.conf import settings

from rates.tasks import (
    SEED_LOCK_KEY,
    SEED_LOCK_TTL_SECONDS,
    _RELEASE_LOCK_SCRIPT,
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
