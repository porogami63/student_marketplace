import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .email_2fa import (
    clear_pending_state,
    get_active_session_challenge,
    get_max_attempts,
    is_sensitive_recent,
    is_verified_for_user,
    issue_login_challenge,
    issue_sensitive_challenge,
    mark_verified,
    mark_sensitive_verified,
    mask_email,
    pop_next_url,
    seconds_until_resend_allowed,
    set_pending_challenge,
    verify_code,
)
from .forms import EmailTwoFactorVerifyForm
from .security import get_client_ip


auth_logger = logging.getLogger('authentication')


def _safe_next_redirect(request, purpose='login'):
    next_url = pop_next_url(request.session, purpose=purpose)
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    if purpose == 'sensitive_action':
        return redirect('marketplace:home')
    return redirect(settings.LOGIN_REDIRECT_URL)


def _otp_page_context(challenge, form, verify_post_url, resend_post_url, kicker, title, subtitle):
    expires_in_seconds = max(0, int((challenge.expires_at - timezone.now()).total_seconds()))
    return {
        'form': form,
        'masked_email': mask_email(challenge.email),
        'expires_in_seconds': expires_in_seconds,
        'verify_post_url': verify_post_url,
        'resend_post_url': resend_post_url,
        'otp_kicker': kicker,
        'otp_title': title,
        'otp_subtitle': subtitle,
    }


@login_required
def email_2fa_verify(request):
    if is_verified_for_user(request.session, request.user):
        return _safe_next_redirect(request, purpose='login')

    challenge = get_active_session_challenge(request.session, request.user, purpose='login')
    if challenge is None:
        try:
            challenge = issue_login_challenge(request.user, ip_address=get_client_ip(request))
        except Exception:
            auth_logger.exception('Failed to issue email 2FA challenge for user=%s', request.user.username)
            clear_pending_state(request.session)
            logout(request)
            messages.error(request, 'Unable to deliver your verification code. Please sign in again.')
            return redirect('account_login')

        set_pending_challenge(request.session, request.user, challenge, purpose='login')
        messages.info(request, 'A verification code was sent to your email address.')

    if request.method == 'POST':
        form = EmailTwoFactorVerifyForm(request.POST)
        if form.is_valid():
            submitted_code = form.cleaned_data['code']
            if verify_code(challenge, submitted_code):
                mark_verified(request.session, request.user)
                messages.success(request, 'Two-factor verification complete.')
                return _safe_next_redirect(request, purpose='login')

            if challenge.attempts >= get_max_attempts():
                clear_pending_state(request.session)
                logout(request)
                messages.error(request, 'Too many invalid codes. Please sign in again.')
                return redirect('account_login')

            messages.error(request, 'Invalid verification code. Please try again.')
    else:
        form = EmailTwoFactorVerifyForm()

    context = _otp_page_context(
        challenge=challenge,
        form=form,
        verify_post_url=reverse('account_email_2fa_verify'),
        resend_post_url=reverse('account_email_2fa_resend'),
        kicker='Account Security Check',
        title='Verify your sign in',
        subtitle='Enter the 6-digit code we sent to',
    )
    return render(request, 'account/email_2fa_verify.html', context)


@login_required
@require_POST
def email_2fa_resend(request):
    if is_verified_for_user(request.session, request.user):
        return redirect(settings.LOGIN_REDIRECT_URL)

    wait_seconds = seconds_until_resend_allowed(request.user, purpose='login')
    if wait_seconds > 0:
        messages.info(request, f'Please wait {wait_seconds} seconds before requesting another code.')
        return redirect('account_email_2fa_verify')

    try:
        challenge = issue_login_challenge(request.user, ip_address=get_client_ip(request))
    except Exception:
        auth_logger.exception('Failed to resend email 2FA challenge for user=%s', request.user.username)
        clear_pending_state(request.session)
        logout(request)
        messages.error(request, 'Unable to send a new code. Please sign in again.')
        return redirect('account_login')

    set_pending_challenge(request.session, request.user, challenge, purpose='login')
    messages.success(request, 'A new verification code was sent to your email.')
    return redirect('account_email_2fa_verify')


@login_required
def email_2fa_sensitive_verify(request):
    if is_sensitive_recent(request.session, request.user):
        return _safe_next_redirect(request, purpose='sensitive_action')

    challenge = get_active_session_challenge(request.session, request.user, purpose='sensitive_action')
    if challenge is None:
        try:
            challenge = issue_sensitive_challenge(request.user, ip_address=get_client_ip(request))
        except Exception:
            auth_logger.exception('Failed to issue sensitive email 2FA challenge for user=%s', request.user.username)
            clear_pending_state(request.session)
            messages.error(request, 'Unable to deliver your verification code right now. Please try again.')
            return redirect('marketplace:home')

        set_pending_challenge(request.session, request.user, challenge, purpose='sensitive_action')
        messages.info(request, 'A security verification code was sent to your email address.')

    if request.method == 'POST':
        form = EmailTwoFactorVerifyForm(request.POST)
        if form.is_valid():
            submitted_code = form.cleaned_data['code']
            if verify_code(challenge, submitted_code):
                mark_sensitive_verified(request.session, request.user)
                messages.success(request, 'Security verification complete.')
                return _safe_next_redirect(request, purpose='sensitive_action')

            if challenge.attempts >= get_max_attempts():
                clear_pending_state(request.session)
                messages.error(request, 'Too many invalid codes. Please request a new verification code.')
                return redirect('account_email_2fa_sensitive_verify')

            messages.error(request, 'Invalid verification code. Please try again.')
    else:
        form = EmailTwoFactorVerifyForm()

    context = _otp_page_context(
        challenge=challenge,
        form=form,
        verify_post_url=reverse('account_email_2fa_sensitive_verify'),
        resend_post_url=reverse('account_email_2fa_sensitive_resend'),
        kicker='Step-up Verification',
        title='Confirm sensitive action',
        subtitle='Enter the 6-digit code we sent to',
    )
    return render(request, 'account/email_2fa_verify.html', context)


@login_required
@require_POST
def email_2fa_sensitive_resend(request):
    if is_sensitive_recent(request.session, request.user):
        return _safe_next_redirect(request, purpose='sensitive_action')

    wait_seconds = seconds_until_resend_allowed(request.user, purpose='sensitive_action')
    if wait_seconds > 0:
        messages.info(request, f'Please wait {wait_seconds} seconds before requesting another code.')
        return redirect('account_email_2fa_sensitive_verify')

    try:
        challenge = issue_sensitive_challenge(request.user, ip_address=get_client_ip(request))
    except Exception:
        auth_logger.exception('Failed to resend sensitive email 2FA challenge for user=%s', request.user.username)
        clear_pending_state(request.session)
        messages.error(request, 'Unable to send a new code right now. Please try again.')
        return redirect('account_email_2fa_sensitive_verify')

    set_pending_challenge(request.session, request.user, challenge, purpose='sensitive_action')
    messages.success(request, 'A new security verification code was sent to your email.')
    return redirect('account_email_2fa_sensitive_verify')
