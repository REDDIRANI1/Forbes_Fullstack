from datetime import date, datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import requests
from django.core.management import call_command

from rates.ingestion import HttpRateSource, HttpSourceError, parse_rate
from rates.models import RawRateRecord, RateRecord


@pytest.fixture
def valid_payload():
    return {
        "provider": "HSBC",
        "rate_type": "savings_1yr_fixed",
        "rate_value": 4.125,
        "effective_date": "2025-01-10",
        "ingestion_ts": "2025-01-10T12:00:00",
        "currency": "USD",
    }


@pytest.fixture
def tiny_parquet(tmp_path, valid_payload):
    rows = [
        valid_payload,
        {
            **valid_payload,
            "provider": "Chase",
            "rate_value": 5.25,
            "effective_date": "2025-01-11",
        },
        {**valid_payload, "provider": "Broken", "rate_value": None},
    ]
    path = tmp_path / "rates.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path, compression="snappy")
    return path


@pytest.mark.django_db
def test_seed_command_is_idempotent_and_keeps_failed_raw_rows(tiny_parquet):
    call_command("seed_data", path=tiny_parquet, batch_size=2)
    call_command("seed_data", path=tiny_parquet, batch_size=2)

    assert RateRecord.objects.count() == 2
    assert RawRateRecord.objects.count() == 3
    assert RawRateRecord.objects.filter(parse_status="failed").count() == 1


def test_parser_normalizes_provider_and_rejects_invalid_rate(valid_payload):
    parsed = parse_rate(valid_payload)

    assert parsed.provider_name == "hsbc"
    assert parsed.effective_date == date(2025, 1, 10)
    assert parsed.ingested_at == datetime(2025, 1, 10, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="rate_value"):
        parse_rate({**valid_payload, "rate_value": 0})


def test_http_source_handles_partial_payload_and_timeout(monkeypatch, valid_payload):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"records": [valid_payload], "partial": True}

    monkeypatch.setattr("rates.ingestion.requests.get", lambda *args, **kwargs: Response())
    records = HttpRateSource("https://example.test/rates").fetch()
    assert parse_rate(records[0]).provider_name == "hsbc"

    def timeout(*args, **kwargs):
        raise requests.Timeout("slow upstream")

    monkeypatch.setattr("rates.ingestion.requests.get", timeout)
    with pytest.raises(HttpSourceError, match="slow upstream"):
        HttpRateSource("https://example.test/rates").fetch()
