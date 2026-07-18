from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse


def health(request):
    try:
        connection.ensure_connection()
        cache.set("healthcheck", "ok", timeout=5)
        if cache.get("healthcheck") != "ok":
            raise RuntimeError("Redis cache round trip failed")
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
