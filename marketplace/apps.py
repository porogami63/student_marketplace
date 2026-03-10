from django.apps import AppConfig


class MarketplaceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'marketplace'
    verbose_name = 'U-Belt Student Marketplace'

    def ready(self):
        import marketplace.signals  # noqa: F401
        import marketplace.social_signals  # noqa: F401
        self._ensure_site_exists()

    def _ensure_site_exists(self):
        """Ensure the Django Site object exists on app startup."""
        try:
            from django.contrib.sites.models import Site
            from django.conf import settings
            import os
            
            site_id = settings.SITE_ID
            
            # Check if the site exists
            if not Site.objects.filter(pk=site_id).exists():
                allowed_hosts = os.environ.get('ALLOWED_HOSTS', 'localhost:8000')
                domain = allowed_hosts.split(',')[0].strip()
                
                if domain.startswith('www.'):
                    domain = domain[4:]
                
                Site.objects.create(
                    pk=site_id,
                    domain=domain,
                    name='U-Belt Student Marketplace'
                )
        except Exception:
            # Silently fail - migrations may not have run yet
            pass
