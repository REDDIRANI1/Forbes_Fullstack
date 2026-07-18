import uuid

from django.core.validators import MinValueValidator
from django.db import models


class IngestionBatch(models.Model):
    class Status(models.TextChoices):
        STARTED = "started", "Started"
        SUCCEEDED = "succeeded", "Succeeded"
        PARTIALLY_SUCCEEDED = "partially_succeeded", "Partially succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=64)
    source_identifier = models.CharField(max_length=128)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.STARTED)
    records_seen = models.PositiveIntegerField(default=0)
    records_created = models.PositiveIntegerField(default=0)
    records_skipped = models.PositiveIntegerField(default=0)
    records_failed = models.PositiveIntegerField(default=0)
    error_summary = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_identifier"],
                name="unique_ingestion_source_identifier",
            )
        ]


class RawRateRecord(models.Model):
    class ParseStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PARSED = "parsed", "Parsed"
        FAILED = "failed", "Failed"

    batch = models.ForeignKey(IngestionBatch, on_delete=models.CASCADE, related_name="raw_records")
    source_row_number = models.PositiveBigIntegerField()
    payload = models.JSONField()
    payload_hash = models.CharField(max_length=64)
    parse_status = models.CharField(max_length=16, choices=ParseStatus.choices, default=ParseStatus.PENDING)
    parse_error = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["batch", "source_row_number"], name="unique_raw_batch_row")
        ]
        indexes = [models.Index(fields=["batch", "parse_status"], name="raw_batch_parse_idx")]


class RateRecord(models.Model):
    raw_record = models.OneToOneField(RawRateRecord, on_delete=models.PROTECT, related_name="rate_record")
    provider_name = models.CharField(max_length=128)
    rate_type = models.CharField(max_length=64)
    rate_value = models.DecimalField(max_digits=9, decimal_places=4, validators=[MinValueValidator(0)])
    effective_date = models.DateField()
    ingested_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider_name", "rate_type", "effective_date", "rate_value"],
                name="unique_normalized_rate_fact",
            ),
            models.CheckConstraint(condition=models.Q(rate_value__gt=0), name="rate_value_positive"),
        ]
        indexes = [
            models.Index(
                fields=["provider_name", "-effective_date", "-ingested_at", "-id"],
                name="rate_latest_provider_idx",
            ),
            models.Index(
                fields=["rate_type", "provider_name", "-effective_date", "-ingested_at", "-id"],
                name="rate_latest_type_idx",
            ),
            models.Index(
                fields=["provider_name", "rate_type", "-effective_date"],
                name="rate_history_lookup_idx",
            ),
            models.Index(fields=["ingested_at"], name="rate_ingested_at_idx"),
        ]
