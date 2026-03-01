from .models import Category, School, Notification


def categories_schools(request):
    """Make categories and schools available in all templates."""
    data = {
        'categories': Category.objects.all(),
        'schools': School.objects.all(),
    }
    user = getattr(request, 'user', None)
    if user and user.is_authenticated:
        data['unread_notifications_count'] = Notification.objects.filter(user=user, is_read=False).count()
    else:
        data['unread_notifications_count'] = 0
    return data
