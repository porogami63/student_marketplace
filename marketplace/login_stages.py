"""Custom allauth login stages."""

from allauth.account.adapter import get_adapter
from allauth.account.app_settings import EmailVerificationMethod
from allauth.account.internal.flows.email_verification import (
    send_verification_email_at_login,
)
from allauth.account.stages import EmailVerificationStage
from allauth.account.utils import has_verified_email


class LegacyAwareEmailVerificationStage(EmailVerificationStage):
    """Skip mandatory verification for legacy and admin users only."""

    def _is_bypassed(self, user):
        adapter = get_adapter(self.request)
        bypass_check = getattr(adapter, 'is_email_verification_bypassed', None)
        if callable(bypass_check):
            return bool(bypass_check(user))
        return False

    def handle(self):
        response, cont = None, True
        login = self.login
        email_verification = login.email_verification

        if email_verification == EmailVerificationMethod.NONE:
            pass
        elif email_verification == EmailVerificationMethod.OPTIONAL:
            if not has_verified_email(login.user, login.email) and login.signup:
                send_verification_email_at_login(self.request, login)
        elif email_verification == EmailVerificationMethod.MANDATORY:
            email_is_verified = has_verified_email(login.user, login.email)
            if not email_is_verified and not self._is_bypassed(login.user):
                send_verification_email_at_login(self.request, login)
                response = get_adapter(self.request).respond_email_verification_sent(
                    self.request,
                    login.user,
                )

        return response, cont
