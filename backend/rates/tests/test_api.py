from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from rates.models import IngestionBatch, RateRecord, RawRateRecord


def make_rate(provider, rate_type, value, effective_date, ingested_at):
    batch = IngestionBatch.objects.create(source="api-test", source_identifier=f"{provider}-{rate_type}-{value}-{ingested_at}")
    raw = RawRateRecord.objects.create(batch=batch, source_row_number=1, payload={}, payload_hash="a" * 64, parse_status="parsed")
    return RateRecord.objects.create(raw_record=raw, provider_name=provider, rate_type=rate_type, rate_value=Decimal(value), effective_date=effective_date, ingested_at=ingested_at)


@pytest.mark.django_db
def test_latest_selects_one_record_per_provider_and_caches():
    make_rate("alpha", "fixed", "4.0000", date(2025, 1, 1), datetime(2025, 1, 1, tzinfo=timezone.utc))
    newest = make_rate("alpha", "variable", "5.0000", date(2025, 1, 2), datetime(2025, 1, 2, tzinfo=timezone.utc))
    bravo = make_rate("bravo", "fixed", "3.0000", date(2025, 1, 1), datetime(2025, 1, 1, tzinfo=timezone.utc))
    response = APIClient().get("/rates/latest")
    assert response.status_code == 200
    assert {item["id"] for item in response.data} == {newest.id, bravo.id}
    assert cache.get("rates:latest:all") is not None
    filtered = APIClient().get("/rates/latest?type=fixed")
    assert filtered.status_code == 200
    assert len(filtered.data) == 2


@pytest.mark.django_db
def test_history_validates_and_paginates():
    for day in range(3):
        make_rate("alpha", "fixed", f"{4 + day}.0000", date(2025, 1, day + 1), datetime(2025, 1, day + 1, tzinfo=timezone.utc))
    client = APIClient()
    assert client.get("/rates/history").status_code == 400
    response = client.get("/rates/history?provider=alpha&type=fixed&page_size=2&from=2025-01-02")
    assert response.status_code == 200
    assert response.data["count"] == 2
    assert len(response.data["results"]) == 2


@pytest.mark.django_db
def test_ingest_auth_validation_idempotency_and_cache_invalidation(settings):
    client = APIClient()
    payload = {"provider": "New", "rate_type": "fixed", "rate_value": "4.0000", "effective_date": "2025-01-01", "ingestion_ts": "2025-01-01T00:00:00Z"}
    assert client.post("/rates/ingest", payload, format="json").status_code == 401
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {settings.INGEST_BEARER_TOKEN}")
    assert client.post("/rates/ingest", {**payload, "unexpected": True}, format="json").status_code == 400
    cache.set("rates:latest:all", [])
    cache.set("rates:latest:type:fixed", [])
    created = client.post("/rates/ingest", payload, format="json")
    assert created.status_code == 201
    assert cache.get("rates:latest:all") is None
    assert cache.get("rates:latest:type:fixed") is None
    repeated = client.post("/rates/ingest", payload, format="json")
    assert repeated.status_code == 200
    assert repeated.data["created"] == 0
