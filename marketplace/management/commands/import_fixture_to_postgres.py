from __future__ import annotations

from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "One-shot: flush + migrate + loaddata + reset_sequences (PostgreSQL only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "fixture",
            nargs="?",
            default="sqlite_export.json",
            help="Fixture file to load (default: sqlite_export.json)",
        )
        parser.add_argument(
            "--no-flush",
            action="store_true",
            help="Skip flush (not recommended unless DB is empty)",
        )

    def handle(self, *args, **options):
        fixture_path = Path(options["fixture"]).resolve()
        if not fixture_path.exists():
            raise CommandError(f"Fixture not found: {fixture_path}")

        self.stdout.write(f"DB vendor: {connection.vendor}")
        if connection.vendor != "postgresql":
            raise CommandError(
                "Refusing to run: this command is PostgreSQL-only. "
                "Set DATABASE_URL to your Postgres URL and try again."
            )

        if not options["no_flush"]:
            self.stdout.write("Flushing database...")
            call_command("flush", interactive=False)

        self.stdout.write("Applying migrations...")
        call_command("migrate")

        self.stdout.write(f"Loading fixture: {fixture_path.name} ...")
        call_command("loaddata", str(fixture_path))

        self.stdout.write("Resetting sequences...")
        call_command("reset_sequences")

        self.stdout.write(self.style.SUCCESS("Import complete."))
