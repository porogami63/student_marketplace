import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from allauth.account.models import EmailAddress

from .models import EmailTwoFactorCode


auth_logger = logging.getLogger('authentication')

SESSION_2FA_PENDING_USER = 'email_2fa_pending_user_id'
SESSION_2FA_CHALLENGE = 'email_2fa_challenge_id'
SESSION_2FA_CHALLENGE_PURPOSE = 'email_2fa_challenge_purpose'
SESSION_2FA_VERIFIED_USER = 'email_2fa_verified_user_id'
SESSION_2FA_NEXT_URL = 'email_2fa_next_url'
SESSION_2FA_SENSITIVE_NEXT_URL = 'email_2fa_sensitive_next_url'
SESSION_2FA_SENSITIVE_VERIFIED_USER = 'email_2fa_sensitive_verified_user_id'
SESSION_2FA_SENSITIVE_VERIFIED_AT = 'email_2fa_sensitive_verified_at'


class Email2FADeliveryError(Exception):
    """Raised when an email 2FA challenge cannot be delivered."""


def _safe_positive_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def get_code_ttl_seconds():
    ttl_seconds = getattr(settings, 'EMAIL_2FA_CODE_TTL_SECONDS', None)
    if ttl_seconds is not None:
        return _safe_positive_int(ttl_seconds, 100)

    # Backward compatibility for old minute-based setting.
    ttl_minutes = _safe_positive_int(getattr(settings, 'EMAIL_2FA_CODE_TTL_MINUTES', 2), 2)
    return ttl_minutes * 60


def get_max_attempts():
    return _safe_positive_int(getattr(settings, 'EMAIL_2FA_MAX_ATTEMPTS', 5), 5)


def get_resend_cooldown_seconds():
    return _safe_positive_int(getattr(settings, 'EMAIL_2FA_RESEND_COOLDOWN_SECONDS', 60), 60)


def get_sensitive_window_seconds():
    return _safe_positive_int(getattr(settings, 'EMAIL_2FA_SENSITIVE_WINDOW_SECONDS', 600), 600)


def is_email_2fa_emergency_bypass_enabled():
    """Return True when emergency bypass mode is enabled for email 2FA."""
    raw_value = getattr(settings, 'EMAIL_2FA_EMERGENCY_BYPASS', False)
    if isinstance(raw_value, str):
        return raw_value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(raw_value)


def is_email_2fa_fail_open_enabled():
    """Return True when delivery failures should temporarily fail-open login 2FA."""
    raw_value = getattr(settings, 'EMAIL_2FA_FAIL_OPEN_ON_DELIVERY_FAILURE', False)
    if isinstance(raw_value, str):
        return raw_value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(raw_value)


def _format_ttl_text(ttl_seconds):
    if ttl_seconds < 60:
        return f"{ttl_seconds} seconds"

    minutes, seconds = divmod(ttl_seconds, 60)
    if seconds == 0:
        unit = 'minute' if minutes == 1 else 'minutes'
        return f"{minutes} {unit}"

    minute_unit = 'minute' if minutes == 1 else 'minutes'
    second_unit = 'second' if seconds == 1 else 'seconds'
    return f"{minutes} {minute_unit} and {seconds} {second_unit}"


def hash_code(raw_code):
    return hashlib.sha256(raw_code.encode('utf-8')).hexdigest()


def mask_email(email):
    if '@' not in email:
        return email

    local, domain = email.split('@', 1)
    if len(local) <= 2:
        local_masked = f"{local[0]}*" if local else '*'
    else:
        local_masked = f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}"
    return f"{local_masked}@{domain}"


def resolve_user_delivery_email(user):
    """Pick the best email destination for OTP delivery.

    Priority:
    1) allauth primary email
    2) allauth verified email
    3) user.email
    """
    preferred = EmailAddress.objects.filter(user=user).order_by('-primary', '-verified').first()
    if preferred and preferred.email:
        resolved = preferred.email.strip().lower()
        if resolved and user.email != resolved:
            user.email = resolved
            user.save(update_fields=['email'])
        return resolved

    fallback = (user.email or '').strip().lower()
    return fallback


def clear_pending_state(session):
    session.pop(SESSION_2FA_PENDING_USER, None)
    session.pop(SESSION_2FA_CHALLENGE, None)
    session.pop(SESSION_2FA_CHALLENGE_PURPOSE, None)


def clear_verified_state(session):
    session.pop(SESSION_2FA_VERIFIED_USER, None)
    session.pop(SESSION_2FA_SENSITIVE_VERIFIED_USER, None)
    session.pop(SESSION_2FA_SENSITIVE_VERIFIED_AT, None)


def set_pending_challenge(session, user, challenge, purpose='login'):
    session[SESSION_2FA_PENDING_USER] = user.pk
    session[SESSION_2FA_CHALLENGE] = challenge.pk
    session[SESSION_2FA_CHALLENGE_PURPOSE] = purpose


def is_verified_for_user(session, user):
    if getattr(user, 'is_superuser', False):
        return True
    return session.get(SESSION_2FA_VERIFIED_USER) == user.pk


def mark_verified(session, user):
    session[SESSION_2FA_VERIFIED_USER] = user.pk
    clear_pending_state(session)


def mark_sensitive_verified(session, user):
    session[SESSION_2FA_SENSITIVE_VERIFIED_USER] = user.pk
    session[SESSION_2FA_SENSITIVE_VERIFIED_AT] = int(timezone.now().timestamp())
    clear_pending_state(session)


def is_sensitive_recent(session, user, max_age_seconds=None):
    if getattr(user, 'is_superuser', False):
        return True

    if session.get(SESSION_2FA_SENSITIVE_VERIFIED_USER) != user.pk:
        return False

    verified_at = session.get(SESSION_2FA_SENSITIVE_VERIFIED_AT)
    try:
        verified_at = int(verified_at)
    except (TypeError, ValueError):
        return False

    if max_age_seconds is None:
        max_age_seconds = get_sensitive_window_seconds()

    now_ts = int(timezone.now().timestamp())
    age_seconds = now_ts - verified_at
    return 0 <= age_seconds <= max_age_seconds


def set_next_url(session, url, purpose='login'):
    key = SESSION_2FA_NEXT_URL if purpose == 'login' else SESSION_2FA_SENSITIVE_NEXT_URL
    session[key] = url


def pop_next_url(session, purpose='login'):
    key = SESSION_2FA_NEXT_URL if purpose == 'login' else SESSION_2FA_SENSITIVE_NEXT_URL
    return session.pop(key, '')


def get_active_session_challenge(session, user, purpose='login'):
    challenge_id = session.get(SESSION_2FA_CHALLENGE)
    pending_user_id = session.get(SESSION_2FA_PENDING_USER)
    pending_purpose = session.get(SESSION_2FA_CHALLENGE_PURPOSE, 'login')
    if not challenge_id or pending_user_id != user.pk:
        return None
    if pending_purpose != purpose:
        return None

    challenge = EmailTwoFactorCode.objects.filter(
        pk=challenge_id,
        user=user,
        purpose=purpose,
        consumed_at__isnull=True,
    ).first()
    if challenge is None:
        return None

    if challenge.expires_at <= timezone.now() or challenge.attempts >= get_max_attempts():
        return None

    return challenge


def seconds_until_resend_allowed(user, purpose='login'):
    latest = EmailTwoFactorCode.objects.filter(
        user=user,
        purpose=purpose,
    ).order_by('-created_at').first()
    if latest is None:
        return 0

    cooldown_seconds = get_resend_cooldown_seconds()
    elapsed = (timezone.now() - latest.created_at).total_seconds()
    wait = int(cooldown_seconds - elapsed)
    return wait if wait > 0 else 0


def _send_code_email(user, raw_code, purpose='login'):
    recipient = resolve_user_delivery_email(user)
    if not recipient:
        raise ValueError('No valid email address available for OTP delivery.')

    ttl_seconds = get_code_ttl_seconds()
    ttl_display = _format_ttl_text(ttl_seconds)
    verification_context = 'login' if purpose == 'login' else 'security verification'
    try:
        send_mail(
            subject='Your UBXchange verification code',
            message=(
                f"Hi {user.username},\n\n"
                f"Your UBXchange {verification_context} code is: {raw_code}\n"
                f"This code will expire in {ttl_display}.\n\n"
                "If you did not try to sign in, reset your password right away."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
    except Exception:
        auth_logger.exception(
            'Email 2FA send failed for user=%s recipient=%s backend=%s host=%s port=%s tls=%s ssl=%s from_email_set=%s',
            user.username,
            recipient,
            getattr(settings, 'EMAIL_BACKEND', ''),
            getattr(settings, 'EMAIL_HOST', ''),
            getattr(settings, 'EMAIL_PORT', ''),
            getattr(settings, 'EMAIL_USE_TLS', ''),
            getattr(settings, 'EMAIL_USE_SSL', ''),
            bool(getattr(settings, 'DEFAULT_FROM_EMAIL', '')),
        )
        raise

    auth_logger.info('Email 2FA delivered for user=%s recipient=%s', user.username, recipient)


def issue_challenge(user, purpose='login', ip_address=''):
    recipient = resolve_user_delivery_email(user)
    if not recipient:
        raise Email2FADeliveryError('User does not have an email address for 2FA delivery.')

    raw_code = f"{secrets.randbelow(1000000):06d}"
    expires_at = timezone.now() + timedelta(seconds=get_code_ttl_seconds())

    challenge = EmailTwoFactorCode.objects.create(
        user=user,
        purpose=purpose,
        email=recipient,
        code_hash=hash_code(raw_code),
        expires_at=expires_at,
        ip_address=ip_address or None,
    )

    try:
        _send_code_email(user, raw_code, purpose=purpose)
    except Exception as exc:
        # Remove undelivered challenges so resend cooldown is not enforced after a failed send.
        try:
            challenge.delete()
        except Exception:
            auth_logger.exception(
                'Failed to cleanup undelivered email 2FA challenge user=%s purpose=%s challenge_id=%s',
                user.username,
                purpose,
                challenge.pk,
            )
        raise Email2FADeliveryError('Unable to deliver email 2FA challenge.') from exc

    auth_logger.info('Email 2FA code sent to user=%s purpose=%s', user.username, purpose)
    return challenge


def issue_login_challenge(user, ip_address=''):
    return issue_challenge(user=user, purpose='login', ip_address=ip_address)


def issue_sensitive_challenge(user, ip_address=''):
    return issue_challenge(user=user, purpose='sensitive_action', ip_address=ip_address)


def verify_code(challenge, raw_code):
    if challenge.consumed_at is not None:
        return False
    if challenge.expires_at <= timezone.now():
        return False
    if challenge.attempts >= get_max_attempts():
        return False

    incoming_hash = hash_code(raw_code)
    if hmac.compare_digest(challenge.code_hash, incoming_hash):
        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=['consumed_at'])
        return True

    challenge.attempts += 1
    challenge.save(update_fields=['attempts'])
    return False
