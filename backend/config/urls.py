from django.contrib import admin
from django.urls import path

from rates.views import HistoryRatesView, IngestRatesView, LatestRatesView, RateOptionsView, health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("rates/latest", LatestRatesView.as_view()),
    path("rates/options", RateOptionsView.as_view()),
    path("rates/history", HistoryRatesView.as_view()),
    path("rates/ingest", IngestRatesView.as_view()),
]
