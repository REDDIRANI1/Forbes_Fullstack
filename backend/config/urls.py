from django.contrib import admin
from django.urls import path, re_path

from rates.views import HistoryRatesView, IngestRatesView, LatestRatesView, RateOptionsView, health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    re_path(r"^rates/latest/?$", LatestRatesView.as_view()),
    re_path(r"^rates/options/?$", RateOptionsView.as_view()),
    re_path(r"^rates/history/?$", HistoryRatesView.as_view()),
    re_path(r"^rates/ingest/?$", IngestRatesView.as_view()),
]
