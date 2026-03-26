from __future__ import annotations

from django.apps import apps
from django.core.management.base import BaseCommand
from django.core.management.color import no_style
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Reset database sequences after fixture imports (PostgreSQL only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "app_labels",
            nargs="*",
            help=(
                "Optional app labels to reset (e.g. marketplace auth). "
                "If omitted, resets sequences for all installed apps."
            ),
        )

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping: database vendor is '{connection.vendor}', not PostgreSQL."
                )
            )
            return

        app_labels: list[str] = options["app_labels"] or [
            app_config.label for app_config in apps.get_app_configs()
        ]

        models = []
        for label in app_labels:
            try:
                app_config = apps.get_app_config(label)
            except LookupError:
                raise SystemExit(f"Unknown app label: {label}")
            models.extend(list(app_config.get_models(include_auto_created=True)))

        sql_statements = connection.ops.sequence_reset_sql(no_style(), models)
        if not sql_statements:
            self.stdout.write("No sequences to reset.")
            return

        with transaction.atomic():
            with connection.cursor() as cursor:
                for statement in sql_statements:
                    cursor.execute(statement)

        self.stdout.write(
            self.style.SUCCESS(f"Reset {len(sql_statements)} sequence(s).")
        )
