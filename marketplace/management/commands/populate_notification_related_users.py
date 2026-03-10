from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from marketplace.models import Notification, Conversation, Transaction
import re


class Command(BaseCommand):
    help = 'Populate related_user field for existing notifications based on message content'

    def handle(self, *args, **options):
        updated = 0
        skipped = 0

        for notification in Notification.objects.filter(related_user__isnull=True):
            # Try to find the related user from the message
            related_user = None

            # Check if message contains a username in quotes or at the start
            message = notification.message
            
            # Extract username pattern - username usually comes after "from" or is at the beginning
            patterns = [
                r'from (\w+)',
                r'(\w+) wants to',
                r'(\w+) cancelled',
                r'(\w+) confirmed',
                r'(\w+) has ',
                r'(\w+) is ',
                r'(\w+) paid',
                r'New (message|offer|review) from (\w+)',
                r'^(\w+)',  # Start of string
            ]

            username = None
            for pattern in patterns:
                match = re.search(pattern, message, re.IGNORECASE)
                if match:
                    # Get the username group (last group if multiple)
                    groups = match.groups()
                    if groups:
                        candidate = groups[-1]
                        # Ignore common words
                        if candidate.lower() not in ['message', 'offer', 'review', 'from', 'to', 'for', 'the', 'an', 'a']:
                            username = candidate
                            break

            if username:
                try:
                    related_user = User.objects.get(username__iexact=username)
                except User.DoesNotExist:
                    skipped += 1
                    continue

            if related_user:
                notification.related_user = related_user
                notification.save()
                updated += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Updated notification: {notification.message[:50]} -> {related_user.username}')
                )
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(f'\nCompleted. Updated: {updated}, Skipped: {skipped}')
        )
