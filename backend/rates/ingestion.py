import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

import pyarrow.parquet as pq
import requests
from django.db import transaction
from django.utils import timezone as django_timezone

from rates.models import IngestionBatch, RateRecord, RawRateRecord


class ParseError(ValueError):
    pass


class HttpSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedRate:
    provider_name: str
    rate_type: str
    rate_value: Decimal
    effective_date: date
    ingested_at: datetime


@dataclass
class IngestionSummary:
    seen: int = 0
    created: int = 0
    skipped: int = 0
    failed: int = 0

    def add(self, other: "IngestionSummary") -> None:
        self.seen += other.seen
        self.created += other.created
        self.skipped += other.skipped
        self.failed += other.failed


class HttpRateSource:
    """Small adapter for the assessment's HTTP error-handling requirement."""

    def __init__(self, url: str, timeout: float = 10) -> None:
        self.url = url
        self.timeout = timeout

    def fetch(self) -> list[Mapping[str, Any]]:
        try:
            response = requests.get(self.url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise HttpSourceError(f"Unable to fetch rate source: {exc}") from exc

        records = payload.get("records") if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            raise HttpSourceError("HTTP rate source returned no records list.")
        return records


def json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def parse_rate(payload: Mapping[str, Any]) -> ParsedRate:
    if not isinstance(payload, Mapping):
        raise ParseError("Record must be an object.")

    provider = payload.get("provider")
    rate_type = payload.get("rate_type")
    if not isinstance(provider, str) or not provider.strip():
        raise ParseError("provider must be a non-empty string.")
    if not isinstance(rate_type, str) or not rate_type.strip():
        raise ParseError("rate_type must be a non-empty string.")

    try:
        rate_value = Decimal(str(payload["rate_value"]))
    except (KeyError, InvalidOperation, ValueError) as exc:
        raise ParseError("rate_value must be a decimal.") from exc
    if not rate_value.is_finite() or rate_value <= 0 or -rate_value.as_tuple().exponent > 4:
        raise ParseError("rate_value must be a positive decimal with at most four decimal places.")

    effective_date = _parse_date(payload.get("effective_date"))
    ingested_at = _parse_datetime(payload.get("ingestion_ts"))
    return ParsedRate(
        provider_name=provider.strip().casefold(),
        rate_type=rate_type.strip(),
        rate_value=rate_value,
        effective_date=effective_date,
        ingested_at=ingested_at,
    )


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ParseError("effective_date must be an ISO date.") from exc
    raise ParseError("effective_date must be an ISO date.")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ParseError("ingestion_ts must be an ISO timestamp.") from exc
    if not isinstance(value, datetime):
        raise ParseError("ingestion_ts must be an ISO timestamp.")
    return value.replace(tzinfo=timezone.utc) if django_timezone.is_naive(value) else value


def persist_records(
    batch: IngestionBatch, rows: Iterable[tuple[int, Mapping[str, Any]]]
) -> IngestionSummary:
    rows = list(rows)
    summary = IngestionSummary(seen=len(rows))
    if not rows:
        return summary

    with transaction.atomic():
        prepared_rows = [(row_number, json_safe(payload)) for row_number, payload in rows]
        RawRateRecord.objects.bulk_create(
            [
                RawRateRecord(
                    batch=batch,
                    source_row_number=row_number,
                    payload=payload,
                    payload_hash=_payload_hash(payload),
                )
                for row_number, payload in prepared_rows
            ],
            ignore_conflicts=True,
            batch_size=len(prepared_rows),
        )
        raw_by_row = {
            raw.source_row_number: raw
            for raw in RawRateRecord.objects.filter(
                batch=batch,
                source_row_number__in=[row_number for row_number, _ in prepared_rows],
            )
        }
        valid: list[tuple[RawRateRecord, ParsedRate]] = []
        raw_updates: list[RawRateRecord] = []
        for row_number, payload in prepared_rows:
            raw_record = raw_by_row[row_number]
            try:
                valid.append((raw_record, parse_rate(payload)))
                raw_record.parse_status = RawRateRecord.ParseStatus.PARSED
                raw_record.parse_error = ""
            except ParseError as exc:
                raw_record.parse_status = RawRateRecord.ParseStatus.FAILED
                raw_record.parse_error = str(exc)
                summary.failed += 1
            raw_updates.append(raw_record)
        RawRateRecord.objects.bulk_update(raw_updates, ["parse_status", "parse_error"])

        raw_ids = [raw_record.id for raw_record, _ in valid]
        existing = RateRecord.objects.filter(raw_record_id__in=raw_ids).count()
        RateRecord.objects.bulk_create(
            [
                RateRecord(
                    raw_record=raw_record,
                    provider_name=parsed.provider_name,
                    rate_type=parsed.rate_type,
                    rate_value=parsed.rate_value,
                    effective_date=parsed.effective_date,
                    ingested_at=parsed.ingested_at,
                )
                for raw_record, parsed in valid
            ],
            ignore_conflicts=True,
            batch_size=len(valid) or 1,
        )
        linked = RateRecord.objects.filter(raw_record_id__in=raw_ids).count()
        summary.created = linked - existing
        summary.skipped = len(valid) - summary.created
    return summary


def ingest_parquet(path: str | Path, batch_size: int = 5_000) -> tuple[IngestionBatch, IngestionSummary]:
    path = Path(path)
    source_identifier = _file_digest(path)
    batch, _ = IngestionBatch.objects.get_or_create(
        source="rates_seed_parquet",
        source_identifier=source_identifier,
    )
    total = IngestionSummary()
    source_row_number = 1
    try:
        parquet = pq.ParquetFile(path)
        for record_batch in parquet.iter_batches(batch_size=batch_size):
            rows = record_batch.to_pylist()
            summary = persist_records(
                batch,
                ((source_row_number + offset, row) for offset, row in enumerate(rows)),
            )
            total.add(summary)
            source_row_number += len(rows)
    except Exception as exc:
        batch.status = IngestionBatch.Status.FAILED
        batch.error_summary = str(exc)
        batch.finished_at = django_timezone.now()
        batch.save(update_fields=["status", "error_summary", "finished_at"])
        raise

    batch.status = (
        IngestionBatch.Status.PARTIALLY_SUCCEEDED if total.failed else IngestionBatch.Status.SUCCEEDED
    )
    batch.records_seen = total.seen
    batch.records_created = total.created
    batch.records_skipped = total.skipped
    batch.records_failed = total.failed
    batch.error_summary = ""
    batch.finished_at = django_timezone.now()
    batch.save(
        update_fields=[
            "status",
            "records_seen",
            "records_created",
            "records_skipped",
            "records_failed",
            "error_summary",
            "finished_at",
        ]
    )
    return batch, total


def ingest_webhook_record(payload: Mapping[str, Any]) -> tuple[IngestionBatch, IngestionSummary]:
    normalized_payload = json_safe(payload)
    source_identifier = _payload_hash(normalized_payload)
    batch, _ = IngestionBatch.objects.get_or_create(
        source="webhook",
        source_identifier=source_identifier,
    )
    summary = persist_records(batch, [(1, normalized_payload)])
    batch.status = (
        IngestionBatch.Status.PARTIALLY_SUCCEEDED if summary.failed else IngestionBatch.Status.SUCCEEDED
    )
    batch.records_seen = summary.seen
    batch.records_created = summary.created
    batch.records_skipped = summary.skipped
    batch.records_failed = summary.failed
    batch.finished_at = django_timezone.now()
    batch.save(
        update_fields=[
            "status",
            "records_seen",
            "records_created",
            "records_skipped",
            "records_failed",
            "finished_at",
        ]
    )
    return batch, summary


def _payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
