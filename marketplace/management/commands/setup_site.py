from django.core.management.base import BaseCommand
from django.contrib.sites.models import Site
import os

class Command(BaseCommand):
    help = 'Create or update the Django Site for the current domain'

    def handle(self, *args, **options):
        # Get the domain from environment variables or use default
        allowed_hosts = os.environ.get('ALLOWED_HOSTS', 'localhost:8000')
        # Take the first host from the list
        domain = allowed_hosts.split(',')[0].strip()
        
        # Remove www. prefix if it exists for the main Site domain
        if domain.startswith('www.'):
            domain = domain[4:]

        try:
            # Try to get the site with SITE_ID=1
            site = Site.objects.get(pk=1)
            # Update it
            if site.domain != domain:
                site.domain = domain
                site.name = 'U-Belt Student Marketplace'
                site.save()
                self.stdout.write(
                    self.style.SUCCESS(f'Updated Site to domain: {domain}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Site already configured with domain: {domain}')
                )
        except Site.DoesNotExist:
            # Create a new site
            Site.objects.create(
                pk=1,
                domain=domain,
                name='U-Belt Student Marketplace'
            )
            self.stdout.write(
                self.style.SUCCESS(f'Created Site with domain: {domain}')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error setting up Site: {str(e)}')
            )
