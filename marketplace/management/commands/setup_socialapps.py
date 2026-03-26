from django.core.management.base import BaseCommand
from django.contrib.sites.models import Site
from django.conf import settings
import os


class Command(BaseCommand):
    help = 'Create or update django-allauth SocialApp(s) from environment variables'

    def handle(self, *args, **options):
        # Optional dependency. If not installed/used, do nothing.
        try:
            from allauth.socialaccount.models import SocialApp
        except Exception:
            self.stdout.write(self.style.WARNING('django-allauth SocialApp model unavailable; skipping.'))
            return

        google_client_id = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
        google_secret = os.environ.get('GOOGLE_CLIENT_SECRET', '').strip()

        if not google_client_id or not google_secret:
            self.stdout.write(self.style.WARNING('GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET not set; skipping Google SocialApp.'))
            return

        try:
            site = Site.objects.get(pk=getattr(settings, 'SITE_ID', 1))
        except Site.DoesNotExist:
            site = Site.objects.create(pk=getattr(settings, 'SITE_ID', 1), domain='localhost', name='U-Belt Student Marketplace')

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

        app.sites.add(site)

        msg = 'Created' if created else 'Updated'
        self.stdout.write(self.style.SUCCESS(f'{msg} Google SocialApp and linked to Site {site.pk} ({site.domain}).'))
