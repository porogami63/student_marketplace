from django.core.management.base import BaseCommand
from marketplace.models import Notification
import re


class Command(BaseCommand):
    help = 'Auto-assign notification types based on message content'

    def handle(self, *args, **options):
        updated = 0
        
        for notification in Notification.objects.filter(notification_type='system'):
            message = notification.message.lower()
            new_type = 'system'

            # Determine type based on message content
            if 'transaction' in message or 'confirmed' in message or 'wants to buy' in message or 'paid' in message or 'payment' in message or 'cancelled the transaction' in message:
                new_type = 'transaction'
            elif 'message' in message or 'message about your transaction' in message:
                new_type = 'message'
            elif 'offer' in message and 'accepted' not in message:
                new_type = 'offer'
            elif 'offer' in message and 'accepted' in message:
                new_type = 'offer'
            elif 'review' in message or 'vouched' in message or 'feedback' in message:
                new_type = 'review'
            elif 'reply' in message or 'forum' in message:
                new_type = 'forum'
            elif 'listing' in message:
                new_type = 'listing'

            if new_type != notification.notification_type:
                notification.notification_type = new_type
                notification.save()
                updated += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Updated: {notification.message[:50]}... -> {new_type}')
                )

        self.stdout.write(
            self.style.SUCCESS(f'\nCompleted. Updated {updated} notifications.')
        )
