#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'student_marketplace.settings')
django.setup()

from django.contrib.auth.models import User
from marketplace.models import Notification

# Get first user with notifications
users_with_notifs = User.objects.filter(notifications__isnull=False).distinct()
if users_with_notifs.exists():
    user = users_with_notifs.first()
    notifs = Notification.objects.filter(user=user)[:5]
    print(f'\nTotal notifications for {user.username}: {notifs.count()}')
    print('='*70)
    for n in notifs:
        avatar_url = None
        if n.related_user and hasattr(n.related_user, 'profile'):
            avatar_url = n.related_user.profile.get_avatar_url()
        print(f'Message: {n.message[:60]}...')
        print(f'  Type: {n.get_notification_type_display()}')
        print(f'  Related User: {n.related_user}')
        print(f'  Avatar URL: {avatar_url}')
        print()
else:
    print('No users with notifications found')
