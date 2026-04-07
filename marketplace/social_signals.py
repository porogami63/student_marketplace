import logging

from allauth.account.signals import user_signed_up
from allauth.socialaccount.signals import social_account_added, social_account_updated
from django.dispatch import receiver

from .models import Profile


logger = logging.getLogger(__name__)


def _update_profile_from_google(user, extra_data):
    """Sync basic profile fields from Google account data."""
    try:
        extra_data = extra_data or {}
        name = (extra_data.get('name') or '').strip()
        picture = (extra_data.get('picture') or '').strip()
        given_name = (extra_data.get('given_name') or '').strip()
        family_name = (extra_data.get('family_name') or '').strip()

        profile, _ = Profile.objects.get_or_create(user=user)

        profile_updates = []
        user_updates = []

        if name and not profile.full_name:
            max_len = Profile._meta.get_field('full_name').max_length
            profile.full_name = name[:max_len] if max_len else name
            profile_updates.append('full_name')

        if given_name and not user.first_name:
            max_len = user._meta.get_field('first_name').max_length
            user.first_name = given_name[:max_len] if max_len else given_name
            user_updates.append('first_name')

        if family_name and not user.last_name:
            max_len = user._meta.get_field('last_name').max_length
            user.last_name = family_name[:max_len] if max_len else family_name
            user_updates.append('last_name')

        if picture:
            max_len = Profile._meta.get_field('google_avatar_url').max_length
            profile.google_avatar_url = picture[:max_len] if max_len else picture
            profile_updates.append('google_avatar_url')

        if user_updates:
            user.save(update_fields=user_updates)
        if profile_updates:
            profile.save(update_fields=profile_updates)
    except Exception:
        logger.exception(
            'Non-fatal Google social profile sync failure for user_id=%s',
            getattr(user, 'pk', None),
        )


@receiver(user_signed_up)
def handle_user_signed_up(request, user, **kwargs):
    # Ensure a profile exists for all new users
    try:
        Profile.objects.get_or_create(user=user)
    except Exception:
        logger.exception(
            'Non-fatal profile creation failure after user_signed_up for user_id=%s',
            getattr(user, 'pk', None),
        )


@receiver(social_account_added)
def handle_social_account_added(request, sociallogin, **kwargs):
    if sociallogin.account.provider != 'google':
        return
    _update_profile_from_google(sociallogin.user, sociallogin.account.extra_data)


@receiver(social_account_updated)
def handle_social_account_updated(request, sociallogin, **kwargs):
    if sociallogin.account.provider != 'google':
        return
    _update_profile_from_google(sociallogin.user, sociallogin.account.extra_data)

