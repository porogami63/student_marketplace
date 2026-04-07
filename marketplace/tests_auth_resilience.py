from typing import cast
from types import SimpleNamespace
from unittest.mock import patch

from allauth.account.app_settings import EmailVerificationMethod
from allauth.account.models import EmailAddress
from allauth.account.models import Login
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse, HttpResponseRedirect
from django.test import RequestFactory, TestCase, override_settings

from marketplace import auth_views, context_processors
from marketplace.adapters import CustomAccountAdapter
from marketplace.email_2fa import is_sensitive_recent, is_verified_for_user, issue_login_challenge
from marketplace.login_stages import LegacyAwareEmailVerificationStage
from marketplace.middleware import EmailTwoFactorMiddleware
from marketplace.models import EmailTwoFactorCode, Profile
from marketplace import signals, social_signals


class AuthenticatedPathResilienceTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_user(
            username='resilience_user',
            email='resilience@example.com',
            password='pass12345',
        )

    def _build_request(self, path='/', method='get'):
        if method.lower() == 'post':
            request = self.factory.post(path, {})
        else:
            request = self.factory.get(path)

        request.user = self.user

        session_middleware = SessionMiddleware(lambda req: HttpResponse())
        session_middleware.process_request(request)
        request.session.save()

        setattr(request, '_messages', FallbackStorage(request))
        return request

    @patch('marketplace.middleware.messages.error')
    @patch('marketplace.middleware.logout')
    @patch('marketplace.middleware.get_active_session_challenge', side_effect=RuntimeError('challenge lookup failed'))
    @patch('marketplace.middleware.is_verified_for_user', return_value=False)
    def test_middleware_handles_challenge_lookup_error(
        self,
        _mock_is_verified,
        _mock_get_challenge,
        mock_logout,
        _mock_message_error,
    ):
        request = self._build_request('/')
        middleware = EmailTwoFactorMiddleware(lambda req: HttpResponse('ok'))

        response = middleware.process_request(request)

        self.assertIsNotNone(response)
        response = cast(HttpResponseRedirect, response)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        mock_logout.assert_called_once()

    @patch('marketplace.middleware.messages.error')
    @patch('marketplace.middleware.logout')
    @patch('marketplace.middleware.issue_login_challenge', side_effect=TimeoutError('smtp timeout'))
    @patch('marketplace.middleware.get_active_session_challenge', return_value=None)
    @patch('marketplace.middleware.is_verified_for_user', return_value=False)
    def test_middleware_handles_challenge_issue_error(
        self,
        _mock_is_verified,
        _mock_get_challenge,
        _mock_issue,
        mock_logout,
        _mock_message_error,
    ):
        request = self._build_request('/')
        middleware = EmailTwoFactorMiddleware(lambda req: HttpResponse('ok'))

        response = middleware.process_request(request)

        self.assertIsNotNone(response)
        response = cast(HttpResponseRedirect, response)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        mock_logout.assert_called_once()

    @patch('marketplace.email_2fa._send_code_email', side_effect=TimeoutError('smtp timeout'))
    def test_issue_challenge_cleanup_on_send_failure(self, _mock_send_email):
        with self.assertRaises(TimeoutError):
            issue_login_challenge(self.user, ip_address='127.0.0.1')

        self.assertFalse(
            EmailTwoFactorCode.objects.filter(user=self.user, purpose='login').exists()
        )

    @patch('marketplace.auth_views.messages.error')
    @patch('marketplace.auth_views.logout')
    @patch('marketplace.auth_views.get_active_session_challenge', side_effect=RuntimeError('challenge lookup failed'))
    @patch('marketplace.auth_views.is_verified_for_user', return_value=False)
    def test_email_2fa_verify_handles_challenge_lookup_error(
        self,
        _mock_is_verified,
        _mock_get_challenge,
        mock_logout,
        _mock_message_error,
    ):
        request = self._build_request('/accounts/email-2fa/')

        response = auth_views.email_2fa_verify(request)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        mock_logout.assert_called_once()

    @patch('marketplace.auth_views.messages.error')
    @patch('marketplace.auth_views.get_active_session_challenge', side_effect=RuntimeError('challenge lookup failed'))
    @patch('marketplace.auth_views.is_sensitive_recent', return_value=False)
    def test_email_2fa_sensitive_verify_handles_challenge_lookup_error(
        self,
        _mock_sensitive_recent,
        _mock_get_challenge,
        _mock_message_error,
    ):
        request = self._build_request('/accounts/email-2fa/sensitive/')

        response = auth_views.email_2fa_sensitive_verify(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/')

    @patch('marketplace.auth_views.messages.error')
    @patch('marketplace.auth_views.logout')
    @patch('marketplace.auth_views.seconds_until_resend_allowed', side_effect=RuntimeError('cooldown lookup failed'))
    @patch('marketplace.auth_views.is_verified_for_user', return_value=False)
    def test_email_2fa_resend_handles_cooldown_lookup_error(
        self,
        _mock_is_verified,
        _mock_cooldown,
        mock_logout,
        _mock_message_error,
    ):
        request = self._build_request('/accounts/email-2fa/resend/', method='post')

        response = auth_views.email_2fa_resend(request)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        mock_logout.assert_called_once()

    @patch('marketplace.context_processors.Category.objects.all', side_effect=RuntimeError('category query failed'))
    def test_categories_schools_handles_category_query_failure(self, _mock_categories):
        request = self._build_request('/')

        context = context_processors.categories_schools(request)

        self.assertEqual(context['categories'], [])
        self.assertEqual(context['schools'], [])
        self.assertIn('unread_notifications_count', context)

    @patch('marketplace.context_processors.Notification.objects.filter', side_effect=RuntimeError('notification query failed'))
    def test_categories_schools_handles_notification_count_failure(self, _mock_notifications):
        request = self._build_request('/')

        context = context_processors.categories_schools(request)

        self.assertEqual(context['unread_notifications_count'], 0)
        self.assertIn('categories', context)
        self.assertIn('schools', context)

    def test_superuser_bypasses_login_email_2fa_gate(self):
        superuser = get_user_model().objects.create_superuser(
            username='admin_login_bypass',
            email='admin_login_bypass@example.com',
            password='pass12345',
        )
        request = self._build_request('/')
        request.user = superuser

        self.assertTrue(is_verified_for_user(request.session, request.user))

    def test_superuser_bypasses_sensitive_email_2fa_gate(self):
        superuser = get_user_model().objects.create_superuser(
            username='admin_sensitive_bypass',
            email='admin_sensitive_bypass@example.com',
            password='pass12345',
        )
        request = self._build_request('/')
        request.user = superuser

        self.assertTrue(is_sensitive_recent(request.session, request.user))

    def test_adapter_uses_legacy_aware_email_verification_stage(self):
        adapter = CustomAccountAdapter()

        stages = adapter.get_login_stages()

        self.assertIn('marketplace.login_stages.LegacyAwareEmailVerificationStage', stages)
        self.assertNotIn('allauth.account.stages.EmailVerificationStage', stages)

    def test_superuser_bypasses_mandatory_email_stage_without_db_verification_write(self):
        superuser = get_user_model().objects.create_superuser(
            username='admin_prelogin_bypass',
            email='Admin.PreLogin@example.com',
            password='pass12345',
        )
        request = self._build_request('/accounts/login/')
        login = Login(
            user=superuser,
            email=superuser.email,
            signup=False,
            email_verification=EmailVerificationMethod.MANDATORY,
        )
        stage = LegacyAwareEmailVerificationStage(None, request, login)

        response, cont = stage.handle()

        self.assertIsNone(response)
        self.assertTrue(cont)
        self.assertFalse(EmailAddress.objects.filter(user=superuser, verified=True).exists())

    @override_settings(ACCOUNT_LEGACY_EMAIL_WHITELIST_CUTOFF='2100-01-01T00:00:00+00:00')
    @patch('marketplace.login_stages.send_verification_email_at_login')
    def test_legacy_whitelist_bypasses_mandatory_email_stage(self, mock_send_verification):
        user = get_user_model().objects.create_user(
            username='legacy_whitelist_user',
            email='legacy.whitelist@example.com',
            password='pass12345',
        )
        EmailAddress.objects.create(
            user=user,
            email='legacy.whitelist@example.com',
            verified=False,
            primary=True,
        )
        request = self._build_request('/accounts/login/')
        login = Login(
            user=user,
            email=user.email,
            signup=False,
            email_verification=EmailVerificationMethod.MANDATORY,
        )
        stage = LegacyAwareEmailVerificationStage(None, request, login)

        response, cont = stage.handle()

        self.assertIsNone(response)
        self.assertTrue(cont)
        mock_send_verification.assert_not_called()
        email_address = EmailAddress.objects.get(user=user, email='legacy.whitelist@example.com')
        self.assertFalse(email_address.verified)

    @override_settings(ACCOUNT_LEGACY_EMAIL_WHITELIST_CUTOFF='2000-01-01T00:00:00+00:00')
    @patch('marketplace.login_stages.send_verification_email_at_login')
    def test_non_legacy_mandatory_stage_still_requires_verification(self, mock_send_verification):
        user = get_user_model().objects.create_user(
            username='recent_nonlegacy_user',
            email='recent.nonlegacy@example.com',
            password='pass12345',
        )
        EmailAddress.objects.create(
            user=user,
            email='recent.nonlegacy@example.com',
            verified=False,
            primary=True,
        )
        request = self._build_request('/accounts/login/')
        login = Login(
            user=user,
            email=user.email,
            signup=False,
            email_verification=EmailVerificationMethod.MANDATORY,
        )
        stage = LegacyAwareEmailVerificationStage(None, request, login)

        response, cont = stage.handle()

        self.assertIsNotNone(response)
        response = cast(HttpResponseRedirect, response)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(cont)
        mock_send_verification.assert_called_once()

    @override_settings(ACCOUNT_LEGACY_EMAIL_WHITELIST_CUTOFF='2100-01-01T00:00:00+00:00')
    @patch('marketplace.login_stages.send_verification_email_at_login')
    def test_legacy_user_without_email_is_not_whitelisted(self, mock_send_verification):
        user = get_user_model().objects.create_user(
            username='legacy_no_email_user',
            email='',
            password='pass12345',
        )
        request = self._build_request('/accounts/login/')
        login = Login(
            user=user,
            email='',
            signup=False,
            email_verification=EmailVerificationMethod.MANDATORY,
        )
        stage = LegacyAwareEmailVerificationStage(None, request, login)

        response, cont = stage.handle()

        self.assertIsNotNone(response)
        response = cast(HttpResponseRedirect, response)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(cont)
        mock_send_verification.assert_called_once()


class SocialOAuthResilienceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='social_resilience_user',
            email='social.resilience@example.com',
            password='pass12345',
        )
        self.factory = RequestFactory()

    @override_settings(GOOGLE_OAUTH_CLIENT_ID='id-from-env', GOOGLE_OAUTH_CLIENT_SECRET='secret-from-env')
    def test_social_auth_status_uses_env_fallback(self):
        request = self.factory.get('/')

        context = context_processors.social_auth_status(request)

        self.assertTrue(context['google_oauth_enabled'])

    def test_social_signal_sync_truncates_google_payload_fields(self):
        long_name = 'N' * 320
        long_picture = 'https://example.com/' + ('p' * 420)
        long_given_name = 'G' * 220
        long_family_name = 'F' * 220

        social_signals._update_profile_from_google(
            self.user,
            {
                'name': long_name,
                'picture': long_picture,
                'given_name': long_given_name,
                'family_name': long_family_name,
            },
        )

        self.user.refresh_from_db()
        profile = Profile.objects.get(user=self.user)

        self.assertLessEqual(len(profile.full_name), 120)
        self.assertLessEqual(len(profile.google_avatar_url), 200)
        self.assertLessEqual(len(self.user.first_name), 150)
        self.assertLessEqual(len(self.user.last_name), 150)

    def test_signal_handler_swallow_profile_save_errors(self):
        sociallogin = SimpleNamespace(
            user=self.user,
            account=SimpleNamespace(
                extra_data={
                    'given_name': 'Test',
                    'family_name': 'User',
                    'picture': 'https://example.com/avatar.png',
                }
            ),
        )

        with patch('marketplace.signals.Profile.save', side_effect=RuntimeError('simulated save error')):
            # The handler should log and continue without raising.
            signals.update_profile_from_google(sender=None, request=None, sociallogin=sociallogin)
