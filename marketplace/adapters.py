"""Custom allauth adapters."""
from allauth.account.adapter import DefaultAccountAdapter
from django.urls import reverse


class CustomAccountAdapter(DefaultAccountAdapter):
    """Redirect superusers to Mod UI, others to profile completion if needed."""

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
