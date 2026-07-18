import re
from collections.abc import Iterable

from django.core.cache import cache

from rates.models import RateRecord

LATEST_ALL_CACHE_KEY = "rates:latest:all"
LATEST_TYPE_CACHE_KEY_PREFIX = "rates:latest:type:"
_RATE_TYPE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_ -]{0,63}$")


def normalize_rate_type(value: str | None) -> tuple[str | None, list[str]]:
    if value is None:
        return None, []
    normalized = value.strip()
    if not normalized:
        return None, ["Must not be blank."]
    if not _RATE_TYPE_PATTERN.fullmatch(normalized):
        return None, ["Use 1-64 letters, numbers, spaces, underscores, or hyphens."]
    return normalized, []


def latest_cache_key(rate_type: str | None = None) -> str:
    return f"{LATEST_TYPE_CACHE_KEY_PREFIX}{rate_type}" if rate_type else LATEST_ALL_CACHE_KEY


def invalidate_latest_cache(rate_types: Iterable[str] | None = None) -> None:
    keys = [LATEST_ALL_CACHE_KEY]
    if rate_types is None:
        rate_types = RateRecord.objects.order_by().values_list("rate_type", flat=True).distinct()
    keys.extend(latest_cache_key(rate_type) for rate_type in set(rate_types))
    cache.delete_many(keys)
