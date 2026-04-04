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


def social_auth_status(request):
    """Expose social auth availability flags for templates."""
    google_oauth_enabled = False
    try:
        from allauth.socialaccount.models import SocialApp
        from django.contrib.sites.models import Site

        site = Site.objects.get_current(request)
        google_oauth_enabled = SocialApp.objects.filter(provider='google', sites=site).exists()
    except Exception:
        google_oauth_enabled = False

    return {
        'google_oauth_enabled': google_oauth_enabled,
    }
