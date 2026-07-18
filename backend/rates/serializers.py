from rest_framework import serializers

from rates.ingestion import ParseError, parse_rate
from rates.models import RateRecord


class RateRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = RateRecord
        fields = ["id", "provider_name", "rate_type", "rate_value", "effective_date", "ingested_at"]


class IngestSerializer(serializers.Serializer):
    provider = serializers.CharField()
    rate_type = serializers.CharField()
    rate_value = serializers.DecimalField(max_digits=9, decimal_places=4)
    effective_date = serializers.DateField()
    ingestion_ts = serializers.DateTimeField()

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({"non_field_errors": ["Invalid data. Expected a dictionary."]})
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: ["Unknown field."] for key in sorted(unknown)})
        return super().to_internal_value(data)

    def validate(self, attrs):
        try:
            parse_rate(attrs)
        except ParseError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return attrs
