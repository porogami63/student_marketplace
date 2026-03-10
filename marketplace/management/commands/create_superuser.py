from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
import os

class Command(BaseCommand):
    help = 'Create a superuser from environment variables'

    def handle(self, *args, **options):
        # Get credentials from environment variables
        username = os.environ.get('ADMIN_USERNAME', 'admin')
        password = os.environ.get('ADMIN_PASSWORD', 'admin')
        email = os.environ.get('ADMIN_EMAIL', 'admin@ubxchange.com')

        # Check if superuser already exists
        if User.objects.filter(username=username).exists():
            self.stdout.write(
                self.style.WARNING(f'Superuser "{username}" already exists. Skipping creation.')
            )
            return

        # Create superuser
        try:
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created superuser "{username}"')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creating superuser: {str(e)}')
            )
