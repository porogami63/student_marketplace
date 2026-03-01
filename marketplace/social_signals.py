from allauth.account.signals import user_signed_up
from allauth.socialaccount.signals import social_account_added, social_account_updated
from django.dispatch import receiver

from .models import Profile


def _update_profile_from_google(user, extra_data):
    """Sync basic profile fields from Google account data."""
    name = extra_data.get('name')
    picture = extra_data.get('picture')
    given_name = extra_data.get('given_name')
    family_name = extra_data.get('family_name')

    profile, _ = Profile.objects.get_or_create(user=user)

    if name and not profile.full_name:
        profile.full_name = name

    if given_name and not user.first_name:
        user.first_name = given_name
    if family_name and not user.last_name:
        user.last_name = family_name

    if picture:
        profile.google_avatar_url = picture

    user.save()
    profile.save()


@receiver(user_signed_up)
def handle_user_signed_up(request, user, **kwargs):
    # Ensure a profile exists for all new users
    Profile.objects.get_or_create(user=user)


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

