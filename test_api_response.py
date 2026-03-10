#!/usr/bin/env python
import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'student_marketplace.settings')
django.setup()

from django.contrib.auth.models import User
from marketplace.models import Notification
from django.http import JsonResponse

# Get first user with notifications
users_with_notifs = User.objects.filter(notifications__isnull=False).distinct()
if users_with_notifs.exists():
    user = users_with_notifs.first()
    notifications = list(Notification.objects.filter(user=user).order_by('-created_at')[:5])
    
    notifications_data = []
    for n in notifications:
        # Safely build related_user data
        related_user_data = None
        if n.related_user:
            avatar_url = None
            if hasattr(n.related_user, 'profile'):
                avatar_url = n.related_user.profile.get_avatar_url()
            
            related_user_data = {
                'username': n.related_user.username,
                'avatar_url': avatar_url,
            }
        
        notification_data = {
            'id': n.id,
            'message': n.message,
            'type': n.get_notification_type_display(),
            'type_key': n.notification_type,
            'url': n.url or '#',
            'is_read': n.is_read,
            'created_at': n.created_at.strftime('%I:%M %p'),
            'created_at_full': n.created_at.strftime('%b %d, %Y %I:%M %p'),
            'related_user': related_user_data,
        }
        notifications_data.append(notification_data)
    
    response_data = {
        'success': True,
        'notifications': notifications_data,
        'unread_count': sum(1 for n in notifications if not n.is_read),
    }
    
    print('\n' + '='*70)
    print(f'NOTIFICATION DROPDOWN API RESPONSE FOR USER: {user.username}')
    print('='*70)
    print(json.dumps(response_data, indent=2))
else:
    print('No users with notifications found')
