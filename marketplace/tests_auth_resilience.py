from typing import cast
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse, HttpResponseRedirect
from django.test import RequestFactory, TestCase

from marketplace import auth_views, context_processors
from marketplace.middleware import EmailTwoFactorMiddleware


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
