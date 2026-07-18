from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from rates.ingestion import ingest_parquet


class Command(BaseCommand):
    help = "Ingest the supplied Parquet rate data in bounded record batches."

    def add_arguments(self, parser):
        parser.add_argument("--path", default="/data/rates_seed.parquet")
        parser.add_argument("--batch-size", type=int, default=5_000)

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"Parquet seed file does not exist: {path}")
        if options["batch_size"] <= 0:
            raise CommandError("--batch-size must be greater than zero.")
        try:
            batch, summary = ingest_parquet(path, batch_size=options["batch_size"])
        except Exception as exc:
            raise CommandError(f"Seed ingestion failed: {exc}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Batch {batch.id}: seen={summary.seen} created={summary.created} "
                f"skipped={summary.skipped} failed={summary.failed}"
            )
        )
