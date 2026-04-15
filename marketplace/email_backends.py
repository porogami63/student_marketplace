"""Custom email backends used by the marketplace app."""

from __future__ import annotations

import logging
import base64
from email.message import EmailMessage
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


logger = logging.getLogger(__name__)


class SendGridAPIBackend(BaseEmailBackend):
    """Send mail through the SendGrid v3 HTTP API.

    This avoids outbound SMTP connectivity, which is often unavailable on
    free-tier hosting platforms such as Render.
    """

    def __init__(self, fail_silently=False, api_key=None, api_url=None, timeout=None, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self.api_key = (api_key or getattr(settings, 'SENDGRID_API_KEY', '') or '').strip()
        self.api_url = (api_url or getattr(settings, 'SENDGRID_API_URL', 'https://api.sendgrid.com/v3/mail/send') or '').strip()
        self.timeout = timeout if timeout is not None else getattr(settings, 'EMAIL_TIMEOUT', 10)

    def open(self):
        return False

    def close(self):
        return None

    def _parse_sender(self, from_email):
        raw_sender = (from_email or getattr(settings, 'DEFAULT_FROM_EMAIL', '') or '').strip()
        display_name, email_address = parseaddr(raw_sender)
        email_address = email_address.strip()
        display_name = display_name.strip()
        if not email_address:
            raise ValueError('A valid sender email address is required for SendGrid delivery.')
        return display_name, email_address

    def _build_payload(self, message):
        display_name, sender_email = self._parse_sender(message.from_email)
        recipients = [address for address in message.recipients() if address]
        if not recipients:
            raise ValueError('Email message has no recipients.')

        personalization = {'to': [{'email': recipient} for recipient in recipients]}
        if message.cc:
            personalization['cc'] = [{'email': recipient} for recipient in message.cc if recipient]
        if message.bcc:
            personalization['bcc'] = [{'email': recipient} for recipient in message.bcc if recipient]

        payload = {
            'personalizations': [personalization],
            'from': {'email': sender_email},
            'subject': message.subject or '',
            'content': [
                {'type': 'text/plain', 'value': message.body or ''},
            ],
        }

        if display_name:
            payload['from']['name'] = display_name

        if getattr(message, 'alternatives', None):
            for body, mimetype in message.alternatives:
                payload['content'].append({'type': mimetype, 'value': body})

        if getattr(message, 'reply_to', None):
            payload['reply_to'] = {'email': message.reply_to[0]}

        return payload

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        if not self.api_key:
            error = ValueError('SENDGRID_API_KEY is not configured.')
            if self.fail_silently:
                logger.exception('SendGrid backend is missing an API key')
                return 0
            raise error

        sent_count = 0
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        for message in email_messages:
            payload = self._build_payload(message)
            try:
                response = requests.post(self.api_url, json=payload, headers=headers, timeout=self.timeout)
                if 200 <= response.status_code < 300:
                    sent_count += 1
                    continue

                error_message = (
                    f'SendGrid API returned HTTP {response.status_code}: '
                    f'{response.text[:500]}'
                )
                if self.fail_silently:
                    logger.error(error_message)
                    continue
                raise RuntimeError(error_message)
            except Exception:
                logger.exception('SendGrid delivery failed')
                if self.fail_silently:
                    continue
                raise

        return sent_count


class GmailAPIBackend(BaseEmailBackend):
    """Send mail through the Gmail API using an OAuth refresh token.

    This avoids outbound SMTP connectivity and works over HTTPS.
    """

    def __init__(self, fail_silently=False, client_id=None, client_secret=None, refresh_token=None, sender_email=None, timeout=None, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self.client_id = (client_id or getattr(settings, 'GMAIL_CLIENT_ID', '') or '').strip()
        self.client_secret = (client_secret or getattr(settings, 'GMAIL_CLIENT_SECRET', '') or '').strip()
        self.refresh_token = (refresh_token or getattr(settings, 'GMAIL_REFRESH_TOKEN', '') or '').strip()
        self.sender_email = (sender_email or getattr(settings, 'GMAIL_SENDER_EMAIL', '') or getattr(settings, 'DEFAULT_FROM_EMAIL', '') or '').strip()
        self.timeout = timeout if timeout is not None else getattr(settings, 'EMAIL_TIMEOUT', 10)

    def open(self):
        return False

    def close(self):
        return None

    def _get_access_token(self):
        if not self.client_id or not self.client_secret or not self.refresh_token:
            raise ValueError('GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN are required.')

        response = requests.post(
            'https://oauth2.googleapis.com/token',
            data={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'refresh_token': self.refresh_token,
                'grant_type': 'refresh_token',
            },
            timeout=self.timeout,
        )
        if not response.ok:
            raise RuntimeError(f'Gmail OAuth token request failed: HTTP {response.status_code} {response.text[:500]}')

        payload = response.json()
        token = payload.get('access_token')
        if not token:
            raise RuntimeError('Gmail OAuth token response did not include an access token.')
        return token

    def _build_raw_message(self, message):
        sender_display_name, sender_email = parseaddr(self.sender_email)
        if not sender_email:
            raise ValueError('A valid Gmail sender email address is required.')

        recipients = [address for address in message.recipients() if address]
        if not recipients:
            raise ValueError('Email message has no recipients.')

        email_message = EmailMessage()
        email_message['To'] = ', '.join(recipients)
        email_message['From'] = f'{sender_display_name} <{sender_email}>' if sender_display_name else sender_email
        email_message['Subject'] = message.subject or ''

        if getattr(message, 'reply_to', None):
            email_message['Reply-To'] = ', '.join([address for address in message.reply_to if address])
        if getattr(message, 'cc', None):
            cc_recipients = [address for address in message.cc if address]
            if cc_recipients:
                email_message['Cc'] = ', '.join(cc_recipients)

        email_message.set_content(message.body or '')
        if getattr(message, 'alternatives', None):
            for body, mimetype in message.alternatives:
                if mimetype == 'text/html':
                    email_message.add_alternative(body, subtype='html')

        raw_bytes = email_message.as_bytes()
        return base64.urlsafe_b64encode(raw_bytes).decode('ascii').rstrip('=')

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        access_token = self._get_access_token()
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }

        sent_count = 0
        for message in email_messages:
            raw_message = self._build_raw_message(message)
            try:
                response = requests.post(
                    'https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
                    json={'raw': raw_message},
                    headers=headers,
                    timeout=self.timeout,
                )
                if 200 <= response.status_code < 300:
                    sent_count += 1
                    continue

                error_message = f'Gmail API returned HTTP {response.status_code}: {response.text[:500]}'
                if self.fail_silently:
                    logger.error(error_message)
                    continue
                raise RuntimeError(error_message)
            except Exception:
                logger.exception('Gmail API delivery failed')
                if self.fail_silently:
                    continue
                raise

        return sent_count