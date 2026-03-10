from django.apps import AppConfig


class MarketplaceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'marketplace'
    verbose_name = 'U-Belt Student Marketplace'

    def ready(self):
        import marketplace.signals  # noqa: F401
        import marketplace.social_signals  # noqa: F401
