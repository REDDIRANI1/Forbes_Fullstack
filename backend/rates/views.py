from datetime import date

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from rest_framework import generics, pagination, permissions, response, views

from rates.authentication import BearerTokenAuthentication
from rates.cache import invalidate_latest_cache, latest_cache_key, normalize_rate_type
from rates.ingestion import ingest_webhook_record
from rates.models import RateRecord
from rates.serializers import IngestSerializer, RateRecordSerializer


def health(request):
    try:
        connection.ensure_connection()
        cache.set("healthcheck", "ok", timeout=5)
        if cache.get("healthcheck") != "ok":
            raise RuntimeError("Redis cache round trip failed")
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


class LatestRatesView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        rate_type, errors = normalize_rate_type(request.query_params.get("type"))
        if errors:
            return response.Response({"type": errors}, status=400)
        key = latest_cache_key(rate_type)
        cached = cache.get(key)
        if cached is not None:
            return response.Response(cached)
        records = RateRecord.objects.all()
        if rate_type:
            records = records.filter(rate_type=rate_type)
        records = records.order_by("provider_name", "-effective_date", "-ingested_at", "-id").distinct("provider_name")
        payload = RateRecordSerializer(records, many=True).data
        cache.set(key, payload, timeout=60)
        return response.Response(payload)


class RateOptionsView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        rows = (
            RateRecord.objects.order_by("provider_name", "rate_type")
            .values_list("provider_name", "rate_type")
            .distinct()
        )
        combinations = [{"provider_name": provider, "rate_type": rate_type} for provider, rate_type in rows]
        return response.Response({"combinations": combinations})


class HistoryRatesView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = RateRecordSerializer

    class Pagination(pagination.PageNumberPagination):
        page_size = 50
        page_size_query_param = "page_size"
        max_page_size = 100

    pagination_class = Pagination

    def get_queryset(self):
        provider = self.request.query_params.get("provider", "").strip()
        rate_type = self.request.query_params.get("type", "").strip()
        if not provider or not rate_type:
            return RateRecord.objects.none()
        queryset = RateRecord.objects.filter(provider_name=provider.casefold(), rate_type=rate_type)
        for parameter, lookup in (("from", "effective_date__gte"), ("to", "effective_date__lte")):
            value = self.request.query_params.get(parameter)
            if value:
                queryset = queryset.filter(**{lookup: date.fromisoformat(value)})
        return queryset.order_by("effective_date", "id")

    def list(self, request, *args, **kwargs):
        errors = {}
        if not request.query_params.get("provider", "").strip(): errors["provider"] = ["This query parameter is required."]
        if not request.query_params.get("type", "").strip(): errors["type"] = ["This query parameter is required."]
        for name in ("from", "to"):
            if request.query_params.get(name):
                try: date.fromisoformat(request.query_params[name])
                except ValueError: errors[name] = ["Use ISO date format YYYY-MM-DD."]
        if errors:
            return response.Response(errors, status=400)
        return super().list(request, *args, **kwargs)


class IngestRatesView(views.APIView):
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = IngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch, summary = ingest_webhook_record(serializer.validated_data)
        parsed = RateRecord.objects.filter(raw_record__batch=batch).order_by("-id").first()
        if summary.created and parsed:
            invalidate_latest_cache([parsed.rate_type])
        status_code = 201 if summary.created else 200
        return response.Response({"batch_id": str(batch.id), "created": summary.created, "skipped": summary.skipped, "rate": RateRecordSerializer(parsed).data if parsed else None}, status=status_code)
