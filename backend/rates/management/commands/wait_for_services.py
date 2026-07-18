import time

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Wait until PostgreSQL and Redis are both usable."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=60)

    def handle(self, *args, **options):
        deadline = time.monotonic() + options["timeout"]
        while time.monotonic() < deadline:
            try:
                connection.ensure_connection()
                cache.set("startup-check", "ok", timeout=5)
                if cache.get("startup-check") == "ok":
                    self.stdout.write("PostgreSQL and Redis are ready.")
                    return
            except Exception:
                time.sleep(1)
        raise CommandError("PostgreSQL and Redis were not ready before timeout.")
