from __future__ import annotations

import os

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = (
        "DANGEROUS: Drop and recreate the public schema (PostgreSQL only). "
        "Requires ALLOW_DB_RESET=1. Use for wiping a target DB before re-importing fixtures."
    )

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stderr.write(
                self.style.ERROR(
                    f"This command only works on PostgreSQL (current vendor: {connection.vendor})."
                )
            )
            return

        if os.environ.get("ALLOW_DB_RESET", "").strip() != "1":
            self.stderr.write(
                self.style.ERROR(
                    "Refusing to run without ALLOW_DB_RESET=1 (this command deletes ALL data)."
                )
            )
            return

        self.stdout.write(self.style.WARNING("Dropping schema public CASCADE..."))
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS public CASCADE;")
            cursor.execute("CREATE SCHEMA public;")
            # Ensure the connection user can use the schema.
            cursor.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER;")
            cursor.execute("GRANT ALL ON SCHEMA public TO public;")

        self.stdout.write(self.style.SUCCESS("PostgreSQL public schema reset complete."))
