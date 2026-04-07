"""Custom allauth adapters."""
from datetime import datetime

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.models import EmailAddress
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime


class CustomAccountAdapter(DefaultAccountAdapter):
    """Redirect superusers to Mod UI, others to profile completion if needed."""

    def _has_email_identity(self, user):
        email_value = (getattr(user, 'email', '') or '').strip()
        if email_value:
            return True
        return EmailAddress.objects.filter(user=user).exclude(email='').exists()

    def _legacy_whitelist_cutoff(self):
        raw_value = getattr(settings, 'ACCOUNT_LEGACY_EMAIL_WHITELIST_CUTOFF', None)
        if raw_value in (None, ''):
            return None

        cutoff = None
        if isinstance(raw_value, datetime):
            cutoff = raw_value
        elif isinstance(raw_value, str):
            cutoff = parse_datetime(raw_value.strip())

        if cutoff is None:
            return None

        if timezone.is_naive(cutoff):
            cutoff = timezone.make_aware(cutoff, timezone.get_current_timezone())
        return cutoff

    def _is_legacy_account(self, user):
        cutoff = self._legacy_whitelist_cutoff()
        if cutoff is None:
            return False

        joined_at = getattr(user, 'date_joined', None)
        if joined_at is None:
            return False

        if timezone.is_naive(joined_at):
            joined_at = timezone.make_aware(joined_at, timezone.get_current_timezone())

        return joined_at < cutoff

    def is_email_verification_bypassed(self, user):
        """Bypass mandatory allauth email verification for trusted account cohorts."""
        if not user:
            return False
        if getattr(user, 'is_superuser', False):
            return True
        if not self._has_email_identity(user):
            return False
        return self._is_legacy_account(user)

    def get_login_stages(self):
        stages = super().get_login_stages()
        default_stage = 'allauth.account.stages.EmailVerificationStage'
        custom_stage = 'marketplace.login_stages.LegacyAwareEmailVerificationStage'
        try:
            index = stages.index(default_stage)
            stages[index] = custom_stage
        except ValueError:
            stages.append(custom_stage)
        return stages

    def _redirect_for_superuser(self, request):
        if request.user.is_authenticated and request.user.is_superuser:
            return reverse('marketplace:mod_dashboard')
        return None

    def _profile_completion_needed(self, request):
        """Check if user needs to complete their profile."""
        if request.user.is_authenticated:
            try:
                profile = request.user.profile
                # Check if required fields are missing
                if not profile.full_name or not profile.school or not profile.year_level:
                    return True
            except:
                pass
        return False

    def get_login_redirect_url(self, request):
        url = self._redirect_for_superuser(request)
        if url:
            return url
        
        # Redirect to profile completion if needed
        if self._profile_completion_needed(request):
            return reverse('marketplace:complete_profile')
        
        return super().get_login_redirect_url(request)

    def get_signup_redirect_url(self, request):
        url = self._redirect_for_superuser(request)
        if url:
            return url
        
        # Redirect to profile completion if needed
        if self._profile_completion_needed(request):
            return reverse('marketplace:complete_profile')
        
        return super().get_signup_redirect_url(request)
