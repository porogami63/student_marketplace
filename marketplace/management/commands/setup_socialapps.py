from __future__ import annotations

import os

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Create or update django-allauth SocialApp(s) from environment variables'

    def handle(self, *args, **options):
        # Optional dependency. If not installed/used, do nothing.
        try:
            from allauth.socialaccount.models import SocialApp
        except Exception:
            self.stdout.write(self.style.WARNING('django-allauth SocialApp model unavailable; skipping.'))
            return

        google_client_id = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', os.environ.get('GOOGLE_CLIENT_ID', '')).strip()
        google_secret = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', os.environ.get('GOOGLE_CLIENT_SECRET', '')).strip()

        if not google_client_id or not google_secret:
            self.stdout.write(self.style.WARNING('GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET not set; skipping Google SocialApp.'))
            return

        site_id = getattr(settings, 'SITE_ID', 1)
        allowed_hosts = [h.strip() for h in getattr(settings, 'ALLOWED_HOSTS', []) if h.strip()]
        default_domain = allowed_hosts[0] if allowed_hosts else 'localhost'
        site, _ = Site.objects.get_or_create(pk=site_id, defaults={'domain': default_domain, 'name': default_domain})
        # Keep Site domain aligned with the deployed host.
        if site.domain != default_domain:
            site.domain = default_domain
        if site.name != default_domain:
            site.name = default_domain
        site.save()

        app_name = os.environ.get('GOOGLE_SOCIALAPP_NAME', 'Google OAuth').strip() or 'Google OAuth'

        app, created = SocialApp.objects.update_or_create(
            provider='google',
            defaults={
                'name': app_name,
                'client_id': google_client_id,
                'secret': google_secret,
                'key': '',
            },
        )

        if not app.sites.filter(pk=site.pk).exists():
            app.sites.add(site)

        msg = 'Created' if created else 'Updated'
        self.stdout.write(self.style.SUCCESS(f'{msg} Google SocialApp and linked to Site {site.pk} ({site.domain}).'))
