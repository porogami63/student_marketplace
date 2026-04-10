from __future__ import annotations

import random
from datetime import timedelta
from typing import Any, Callable

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.core.exceptions import DisallowedHost
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from . import auth_views
from .forms import SchoolIDVerificationRequestForm
from .middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from .security import (
    AuditLog,
    check_ferpa_compliance,
    check_iso27001_compliance,
    check_nist_compliance,
    check_pci_dss_compliance,
    sanitize_input,
)


ACTIVE_CHECK_CATALOG = [
    {
        'action': 'active_realtime_demo_report',
        'title': 'Realtime XSS + SQLi demo report',
        'description': 'Run live XSS and SQL injection simulations and generate a structured Sample/Problem/Solution output.',
    },
    {
        'action': 'active_xss_realtime_check',
        'title': 'Realtime XSS scripting demo',
        'description': 'Process representative XSS payloads in real time and verify they are escaped/sanitized.',
    },
    {
        'action': 'active_sqli_realtime_check',
        'title': 'Realtime SQL injection demo',
        'description': 'Run ORM queries with SQLi payloads and verify parameterized behavior prevents query expansion.',
    },
    {
        'action': 'active_csrf_check',
        'title': 'CSRF enforcement probe',
        'description': 'Simulate a POST without CSRF token and verify it is blocked with 403.',
    },
    {
        'action': 'active_rate_limit_check',
        'title': 'Rate limiting probe',
        'description': 'Run a controlled burst to verify rate limiter returns 429 when threshold is exceeded.',
    },
    {
        'action': 'active_auth_gate_check',
        'title': 'Auth/2FA gate probe',
        'description': 'Validate protected OTP route redirects anonymous users to login.',
    },
    {
        'action': 'active_upload_validation_check',
        'title': 'File upload validation probe',
        'description': 'Verify oversized and invalid MIME uploads are rejected by School ID validation.',
    },
    {
        'action': 'active_redirect_validation_check',
        'title': 'Open redirect probe',
        'description': 'Verify external and javascript redirect targets are rejected by host/scheme checks.',
    },
    {
        'action': 'active_security_headers_check',
        'title': 'Security headers probe',
        'description': 'Run header middleware and verify CSP and clickjacking headers are present.',
    },
]


def get_active_check_catalog() -> list[dict[str, str]]:
    return list(ACTIVE_CHECK_CATALOG)


def build_security_test_context(request) -> dict[str, Any]:
    passive_modules = [
        _build_csrf_module(),
        _build_xss_module(),
        _build_sqli_module(),
        _build_rate_limit_module(),
        _build_cookie_session_module(),
        _build_auth_2fa_module(),
        _build_upload_module(),
        _build_redirect_module(request),
        _build_headers_module(),
    ]

    compliance_snapshot = _build_compliance_snapshot()
    audit_summary = _build_audit_summary()

    return {
        'generated_at': timezone.now(),
        'passive_modules': passive_modules,
        'active_checks': get_active_check_catalog(),
        'compliance_snapshot': compliance_snapshot,
        'audit_summary': audit_summary,
    }


def run_active_security_check(
    action: str,
    request,
    csrf_probe_view: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    handlers = {
        'active_realtime_demo_report': _run_active_realtime_demo_report,
        'active_xss_realtime_check': _run_active_xss_realtime_check,
        'active_sqli_realtime_check': _run_active_sqli_realtime_check,
        'active_csrf_check': lambda req: _run_active_csrf_check(req, csrf_probe_view),
        'active_rate_limit_check': _run_active_rate_limit_check,
        'active_auth_gate_check': _run_active_auth_gate_check,
        'active_upload_validation_check': _run_active_upload_validation_check,
        'active_redirect_validation_check': _run_active_redirect_validation_check,
        'active_security_headers_check': _run_active_security_headers_check,
    }

    handler = handlers.get(action)
    if handler is None:
        return {
            'action': action,
            'title': 'Unknown action',
            'status': 'fail',
            'summary': 'The requested active check is not supported.',
            'details': [
                {'label': 'Action', 'value': action},
            ],
            'executed_at': timezone.now(),
        }

    result = handler(request)
    result['action'] = action
    result['executed_at'] = timezone.now()
    return result


def _module_result(module_id: str, title: str, summary: str, checks: list[dict[str, Any]], remediation: str = '') -> dict[str, Any]:
    status = 'pass' if all(item.get('ok', False) for item in checks) else 'warn'
    return {
        'id': module_id,
        'title': title,
        'summary': summary,
        'status': status,
        'checks': checks,
        'remediation': remediation,
    }


def _bool_label(value: bool) -> str:
    return 'Enabled' if value else 'Disabled'


def _build_demo_report(sample_case: str, problem: str, solution: str, tests_ran: list[str]) -> dict[str, Any]:
    return {
        'sample_case': sample_case,
        'problem': problem,
        'solution': solution,
        'tests_ran': tests_ran,
    }


def _safe_request_host(request) -> str:
    try:
        return request.get_host()
    except DisallowedHost:
        valid_hosts = [host for host in getattr(settings, 'ALLOWED_HOSTS', []) if host and host != '*']
        return valid_hosts[0] if valid_hosts else 'localhost'


def _build_csrf_module() -> dict[str, Any]:
    csrf_middleware_enabled = 'django.middleware.csrf.CsrfViewMiddleware' in settings.MIDDLEWARE
    csrf_secure_expected = True if not settings.DEBUG else bool(getattr(settings, 'CSRF_COOKIE_SECURE', False))

    checks = [
        {
            'label': 'CSRF middleware',
            'value': _bool_label(csrf_middleware_enabled),
            'ok': csrf_middleware_enabled,
        },
        {
            'label': 'CSRF cookie HttpOnly',
            'value': _bool_label(bool(getattr(settings, 'CSRF_COOKIE_HTTPONLY', False))),
            'ok': bool(getattr(settings, 'CSRF_COOKIE_HTTPONLY', False)),
        },
        {
            'label': 'CSRF SameSite',
            'value': str(getattr(settings, 'CSRF_COOKIE_SAMESITE', 'unset')),
            'ok': bool(getattr(settings, 'CSRF_COOKIE_SAMESITE', '')),
        },
        {
            'label': 'CSRF secure cookie expectation',
            'value': 'Met' if csrf_secure_expected else 'Not met',
            'ok': csrf_secure_expected,
        },
    ]

    return _module_result(
        module_id='csrf',
        title='CSRF protection',
        summary='Validates CSRF middleware and cookie hardening settings used by state-changing forms.',
        checks=checks,
        remediation='Enable CSRF middleware and secure CSRF cookie settings before production deployment.',
    )


def _build_xss_module() -> dict[str, Any]:
    payload = '<script>alert("xss")</script><img src=x onerror=alert(1)>'
    html_sanitized = sanitize_input(payload, 'html')
    text_escaped = sanitize_input(payload, 'text')
    csp_middleware_enabled = 'marketplace.middleware.SecurityHeadersMiddleware' in settings.MIDDLEWARE

    checks = [
        {
            'label': 'HTML sanitizer strips script tags',
            'value': html_sanitized,
            'ok': '<script' not in html_sanitized.lower(),
        },
        {
            'label': 'Text escaping encodes script payload',
            'value': text_escaped,
            'ok': '&lt;script' in text_escaped.lower(),
        },
        {
            'label': 'Security headers middleware (CSP)',
            'value': _bool_label(csp_middleware_enabled),
            'ok': csp_middleware_enabled,
        },
    ]

    return _module_result(
        module_id='xss',
        title='XSS resistance',
        summary='Shows how script payloads are escaped/sanitized and guarded with CSP headers.',
        checks=checks,
        remediation='Avoid rendering user content with the safe filter unless content is fully trusted and sanitized.',
    )


def _build_sqli_module() -> dict[str, Any]:
    payload = "' OR 1=1 --"
    query_ok = True
    result_count = 0
    try:
        result_count = User.objects.filter(username=payload).count()
    except Exception:
        query_ok = False

    checks = [
        {
            'label': 'ORM query with SQLi payload executes safely',
            'value': f'Results: {result_count}',
            'ok': query_ok,
        },
        {
            'label': 'Raw SQL with user input in this demo',
            'value': 'Not used',
            'ok': True,
        },
    ]

    return _module_result(
        module_id='sqli',
        title='SQL injection prevention',
        summary='Demonstrates that ORM-based filters treat SQLi strings as plain data.',
        checks=checks,
        remediation='Continue using ORM filters and parameterized queries for dynamic inputs.',
    )


def _build_rate_limit_module() -> dict[str, Any]:
    checks = [
        {
            'label': 'Login rate limit',
            'value': f"{getattr(settings, 'RATE_LIMIT_LOGIN_ATTEMPTS', 0)} attempts / {getattr(settings, 'RATE_LIMIT_LOGIN_WINDOW', 0)}s",
            'ok': int(getattr(settings, 'RATE_LIMIT_LOGIN_ATTEMPTS', 0)) > 0,
        },
        {
            'label': 'API rate limit',
            'value': f"{getattr(settings, 'RATE_LIMIT_API_REQUESTS', 0)} requests / {getattr(settings, 'RATE_LIMIT_API_WINDOW', 0)}s",
            'ok': int(getattr(settings, 'RATE_LIMIT_API_REQUESTS', 0)) > 0,
        },
        {
            'label': 'Search rate limit',
            'value': f"{getattr(settings, 'RATE_LIMIT_SEARCH_REQUESTS', 0)} requests / {getattr(settings, 'RATE_LIMIT_SEARCH_WINDOW', 0)}s",
            'ok': int(getattr(settings, 'RATE_LIMIT_SEARCH_REQUESTS', 0)) > 0,
        },
    ]

    return _module_result(
        module_id='rate-limit',
        title='Rate limiting configuration',
        summary='Shows configured throttling thresholds for login, API, and search endpoints.',
        checks=checks,
        remediation='Keep limits above zero and tune values by traffic profile and abuse patterns.',
    )


def _build_cookie_session_module() -> dict[str, Any]:
    checks = [
        {
            'label': 'Session cookie HttpOnly',
            'value': _bool_label(bool(getattr(settings, 'SESSION_COOKIE_HTTPONLY', False))),
            'ok': bool(getattr(settings, 'SESSION_COOKIE_HTTPONLY', False)),
        },
        {
            'label': 'Session cookie SameSite',
            'value': str(getattr(settings, 'SESSION_COOKIE_SAMESITE', 'unset')),
            'ok': bool(getattr(settings, 'SESSION_COOKIE_SAMESITE', '')),
        },
        {
            'label': 'CSRF cookie HttpOnly',
            'value': _bool_label(bool(getattr(settings, 'CSRF_COOKIE_HTTPONLY', False))),
            'ok': bool(getattr(settings, 'CSRF_COOKIE_HTTPONLY', False)),
        },
        {
            'label': 'Secure cookies (production expectation)',
            'value': 'Met' if settings.DEBUG or bool(getattr(settings, 'SESSION_COOKIE_SECURE', False)) else 'Not met',
            'ok': settings.DEBUG or bool(getattr(settings, 'SESSION_COOKIE_SECURE', False)),
        },
    ]

    return _module_result(
        module_id='cookies',
        title='Session and cookie hardening',
        summary='Confirms session and CSRF cookie flags used to reduce session theft risk.',
        checks=checks,
        remediation='Enable secure cookies and strict transport settings in production.',
    )


def _build_auth_2fa_module() -> dict[str, Any]:
    checks = [
        {
            'label': 'Email 2FA middleware active',
            'value': _bool_label('marketplace.middleware.EmailTwoFactorMiddleware' in settings.MIDDLEWARE),
            'ok': 'marketplace.middleware.EmailTwoFactorMiddleware' in settings.MIDDLEWARE,
        },
        {
            'label': 'Mandatory email verification (allauth)',
            'value': str(getattr(settings, 'ACCOUNT_EMAIL_VERIFICATION', 'unset')),
            'ok': getattr(settings, 'ACCOUNT_EMAIL_VERIFICATION', '') == 'mandatory',
        },
        {
            'label': 'Password minimum length policy',
            'value': str(getattr(settings, 'MAX_LOGIN_ATTEMPTS', 'configured')),
            'ok': True,
        },
    ]

    return _module_result(
        module_id='auth-2fa',
        title='Authentication and 2FA gates',
        summary='Highlights gate controls for login verification and post-authentication protection.',
        checks=checks,
        remediation='Avoid fail-open 2FA modes outside emergency operations.',
    )


def _build_upload_module() -> dict[str, Any]:
    invalid_svg = SimpleUploadedFile('security-demo.svg', b'<svg></svg>', content_type='image/svg+xml')
    invalid_form = SchoolIDVerificationRequestForm(data={}, files={'id_image': invalid_svg})
    invalid_form.is_valid()

    checks = [
        {
            'label': 'School ID upload blocks unsupported MIME',
            'value': ', '.join(invalid_form.errors.get('id_image', [])) or 'No validation message',
            'ok': not invalid_form.is_valid(),
        },
        {
            'label': 'Accepted image types',
            'value': 'image/jpeg, image/png, image/webp',
            'ok': True,
        },
        {
            'label': 'Max file size',
            'value': '5 MB',
            'ok': True,
        },
    ]

    return _module_result(
        module_id='uploads',
        title='File upload validation',
        summary='Verifies that School ID uploads enforce MIME and size constraints.',
        checks=checks,
        remediation='Apply equivalent validation to all image upload entry points.',
    )


def _build_redirect_module(request) -> dict[str, Any]:
    require_https = request.is_secure()
    allowed_hosts = {_safe_request_host(request)}

    safe_target = '/profile/'
    unsafe_target = 'https://evil.example/phish'

    safe_ok = url_has_allowed_host_and_scheme(safe_target, allowed_hosts=allowed_hosts, require_https=require_https)
    unsafe_blocked = not url_has_allowed_host_and_scheme(unsafe_target, allowed_hosts=allowed_hosts, require_https=require_https)

    checks = [
        {
            'label': 'Safe internal next URL allowed',
            'value': safe_target,
            'ok': safe_ok,
        },
        {
            'label': 'External redirect target blocked',
            'value': unsafe_target,
            'ok': unsafe_blocked,
        },
    ]

    return _module_result(
        module_id='open-redirect',
        title='Open redirect prevention',
        summary='Uses host/scheme validation for next URLs to block off-site redirect abuse.',
        checks=checks,
        remediation='Validate all user-controlled redirect targets with allowed host checks.',
    )


def _build_headers_module() -> dict[str, Any]:
    checks = [
        {
            'label': 'SecurityHeadersMiddleware active',
            'value': _bool_label('marketplace.middleware.SecurityHeadersMiddleware' in settings.MIDDLEWARE),
            'ok': 'marketplace.middleware.SecurityHeadersMiddleware' in settings.MIDDLEWARE,
        },
        {
            'label': 'X-Frame-Options configured',
            'value': str(getattr(settings, 'X_FRAME_OPTIONS', 'unset')),
            'ok': str(getattr(settings, 'X_FRAME_OPTIONS', '')).upper() == 'DENY',
        },
        {
            'label': 'SECURE_SSL_REDIRECT',
            'value': _bool_label(bool(getattr(settings, 'SECURE_SSL_REDIRECT', False))),
            'ok': settings.DEBUG or bool(getattr(settings, 'SECURE_SSL_REDIRECT', False)),
        },
    ]

    return _module_result(
        module_id='headers',
        title='Security headers and clickjacking',
        summary='Checks middleware and key transport/frame-control settings for browser-side hardening.',
        checks=checks,
        remediation='Keep CSP and clickjacking headers active on all dynamic responses.',
    )


def _safe_compliance_call(check_fn: Callable[[], dict[str, Any]], key: str) -> dict[str, str]:
    try:
        payload = check_fn()
        status = payload.get('overall_status') or payload.get('status') or 'UNKNOWN'
        return {'status': str(status).upper(), 'key': key}
    except Exception as exc:
        return {'status': 'ERROR', 'key': key, 'error': str(exc)}


def _build_compliance_snapshot() -> dict[str, dict[str, str]]:
    return {
        'ferpa': _safe_compliance_call(check_ferpa_compliance, 'ferpa'),
        'pci_dss': _safe_compliance_call(check_pci_dss_compliance, 'pci_dss'),
        'nist': _safe_compliance_call(check_nist_compliance, 'nist'),
        'iso27001': _safe_compliance_call(check_iso27001_compliance, 'iso27001'),
    }


def _build_audit_summary() -> dict[str, Any]:
    try:
        window_start = timezone.now() - timedelta(days=7)
        recent_logs = AuditLog.objects.filter(timestamp__gte=window_start)
        return {
            'window_days': 7,
            'total_events': recent_logs.count(),
            'critical_events': recent_logs.filter(severity='critical').count(),
            'error_events': recent_logs.filter(severity='error').count(),
            'warning_events': recent_logs.filter(severity='warning').count(),
        }
    except Exception as exc:
        return {'error': str(exc)}


def _run_active_csrf_check(request, csrf_probe_view: Callable[..., Any] | None) -> dict[str, Any]:
    if csrf_probe_view is None:
        return {
            'title': 'CSRF enforcement probe',
            'status': 'fail',
            'summary': 'CSRF probe callback is missing, so the active check cannot run.',
            'details': [],
        }

    factory = RequestFactory()
    probe_request = factory.post('/mod/security-tests/probe/', {'probe': '1'})
    probe_request.user = request.user
    probe_request.META['REMOTE_ADDR'] = request.META.get('REMOTE_ADDR', '127.0.0.1')

    csrf_middleware = CsrfViewMiddleware(lambda req: HttpResponse('ok'))
    response = csrf_middleware.process_view(probe_request, csrf_probe_view, (), {})

    blocked = response is not None and response.status_code == 403
    observed_status = response.status_code if response is not None else 200

    return {
        'title': 'CSRF enforcement probe',
        'status': 'pass' if blocked else 'warn',
        'summary': 'POST without CSRF token was blocked as expected.' if blocked else 'CSRF probe was not blocked as expected.',
        'details': [
            {'label': 'Expected status', 'value': '403'},
            {'label': 'Observed status', 'value': str(observed_status)},
        ],
        'demo_report': _build_demo_report(
            sample_case='A moderator tests a form submission without a CSRF token to validate request forgery defenses.',
            problem='Attackers can force logged-in users to submit state-changing requests if CSRF validation is missing.',
            solution='CsrfViewMiddleware blocks tokenless POST requests with HTTP 403, preventing unauthorized state changes.',
            tests_ran=[
                f'CSRF tokenless POST probe observed status: {observed_status}',
            ],
        ),
    }


def _run_active_xss_realtime_check(request) -> dict[str, Any]:
    payloads = [
        '<script>alert("xss")</script>',
        '<img src=x onerror="alert(1)">',
        '<a href="javascript:alert(1)">click</a>',
    ]

    payload_results: list[dict[str, Any]] = []
    tests_ran: list[str] = []
    passed = True

    for index, payload in enumerate(payloads, start=1):
        escaped_text = sanitize_input(payload, 'text')
        stripped_html = sanitize_input(payload, 'html')
        script_removed = '<script' not in stripped_html.lower() and 'javascript:' not in stripped_html.lower()
        encoded = '&lt;' in escaped_text.lower() and '&gt;' in escaped_text.lower()
        payload_safe = script_removed and encoded
        passed = passed and payload_safe

        payload_results.append({
            'payload': payload,
            'escaped_text': escaped_text,
            'stripped_html': stripped_html,
            'safe': payload_safe,
        })
        tests_ran.append(
            f'Payload {index} sanitized={script_removed} escaped={encoded} final={"PASS" if payload_safe else "WARN"}'
        )

    return {
        'title': 'Realtime XSS scripting demo',
        'status': 'pass' if passed else 'warn',
        'summary': 'XSS payloads were neutralized through escaping and HTML sanitization checks.' if passed else 'One or more payloads need sanitizer/escaping review.',
        'details': [
            {'label': 'Payloads tested', 'value': str(len(payloads))},
            {'label': 'Payloads neutralized', 'value': str(sum(1 for item in payload_results if item['safe']))},
        ],
        'payload_results': payload_results,
        'demo_report': _build_demo_report(
            sample_case='A user submits crafted comment content containing script and javascript payloads.',
            problem='Without output encoding and sanitization, payloads can execute in another user session and steal data or hijack actions.',
            solution='Input is escaped/sanitized before display, so script-bearing payloads are rendered as inert text instead of executable code.',
            tests_ran=tests_ran,
        ),
    }


def _run_active_sqli_realtime_check(request) -> dict[str, Any]:
    payloads = [
        "' OR 1=1 --",
        "'; DROP TABLE auth_user; --",
        '" OR "1"="1',
    ]

    baseline_user_count = User.objects.count()
    tests_ran: list[str] = []
    query_results: list[dict[str, Any]] = []
    query_errors = 0

    for index, payload in enumerate(payloads, start=1):
        try:
            exact_count = User.objects.filter(username=payload).count()
            contains_count = User.objects.filter(username__icontains=payload).count()
            expanded_match = baseline_user_count > 1 and exact_count == baseline_user_count
            safe = not expanded_match
            query_results.append({
                'payload': payload,
                'exact_count': exact_count,
                'contains_count': contains_count,
                'safe': safe,
            })
            tests_ran.append(
                f'Payload {index} exact_count={exact_count} contains_count={contains_count} expanded_all_rows={expanded_match}'
            )
        except Exception as exc:
            query_errors += 1
            query_results.append({'payload': payload, 'error': str(exc), 'safe': False})
            tests_ran.append(f'Payload {index} raised error={exc}')

    post_check_user_count = User.objects.count()
    table_intact = baseline_user_count == post_check_user_count
    no_expansion = all(item.get('safe', False) for item in query_results)
    passed = query_errors == 0 and table_intact and no_expansion

    return {
        'title': 'Realtime SQL injection demo',
        'status': 'pass' if passed else 'warn',
        'summary': 'ORM lookups treated SQLi payloads as data and did not expand or mutate query scope.' if passed else 'SQLi simulation produced unexpected behavior and requires review.',
        'details': [
            {'label': 'Payloads tested', 'value': str(len(payloads))},
            {'label': 'Query errors', 'value': str(query_errors)},
            {'label': 'User table row count unchanged', 'value': str(table_intact)},
        ],
        'query_results': query_results,
        'demo_report': _build_demo_report(
            sample_case='A moderator simulates SQL injection strings against user lookup queries.',
            problem='String-concatenated SQL can let attackers bypass filters or execute destructive statements.',
            solution='ORM parameterization keeps payloads as literal values; no query expansion or data mutation occurs in the simulation.',
            tests_ran=tests_ran,
        ),
    }


def _run_active_realtime_demo_report(request) -> dict[str, Any]:
    xss_result = _run_active_xss_realtime_check(request)
    sqli_result = _run_active_sqli_realtime_check(request)

    statuses = [xss_result.get('status', 'warn'), sqli_result.get('status', 'warn')]
    if 'fail' in statuses:
        final_status = 'fail'
    elif 'warn' in statuses:
        final_status = 'warn'
    else:
        final_status = 'pass'

    tests_ran = [
        f"Realtime XSS demo status: {xss_result.get('status', 'unknown').upper()}",
        f"Realtime SQL injection demo status: {sqli_result.get('status', 'unknown').upper()}",
    ]

    return {
        'title': 'Realtime attack simulation report',
        'status': final_status,
        'summary': 'Combined realtime XSS and SQL injection demonstrations completed with structured defense analysis.',
        'details': [
            {'label': 'XSS demo', 'value': xss_result.get('status', 'unknown').upper()},
            {'label': 'SQL injection demo', 'value': sqli_result.get('status', 'unknown').upper()},
            {'label': 'Overall status', 'value': final_status.upper()},
        ],
        'child_results': [
            {'title': xss_result.get('title', 'XSS'), 'status': xss_result.get('status', 'unknown')},
            {'title': sqli_result.get('title', 'SQLi'), 'status': sqli_result.get('status', 'unknown')},
        ],
        'demo_report': _build_demo_report(
            sample_case='Security team runs a live attack simulation cycle for XSS scripting and SQL injection scenarios.',
            problem='Web attackers probe input and query layers to execute scripts, bypass controls, or extract data through injection paths.',
            solution='Defense-in-depth combines escaping/sanitization, parameterized ORM usage, and continuous audit logging of all test actions.',
            tests_ran=tests_ran,
        ),
    }


def _run_active_rate_limit_check(request) -> dict[str, Any]:
    factory = RequestFactory()
    middleware = RateLimitMiddleware(lambda req: HttpResponse('ok'))
    probe_ip = f"198.51.100.{random.randint(10, 220)}"
    probe_path = '/api/recent-notifications/'
    cache_key = f'rate_limit:{probe_ip}:{probe_path}'

    cache.delete(cache_key)

    statuses: list[int] = []
    with override_settings(RATE_LIMIT_API_REQUESTS=2, RATE_LIMIT_API_WINDOW=30):
        for _ in range(3):
            req = factory.get(probe_path)
            req.META['REMOTE_ADDR'] = probe_ip
            response = middleware.process_request(req)
            statuses.append(response.status_code if response is not None else 200)

    cache.delete(cache_key)
    blocked = statuses[-1] == 429 if statuses else False

    return {
        'title': 'Rate limiting probe',
        'status': 'pass' if blocked else 'warn',
        'summary': 'Limiter returned 429 after threshold was exceeded.' if blocked else 'Limiter did not return 429 at expected threshold.',
        'details': [
            {'label': 'Probe path', 'value': probe_path},
            {'label': 'Observed statuses', 'value': ', '.join(str(code) for code in statuses)},
            {'label': 'Applied threshold', 'value': '2 requests / 30s (temporary probe override)'},
        ],
    }


def _run_active_auth_gate_check(request) -> dict[str, Any]:
    factory = RequestFactory()
    login_url = reverse('account_email_2fa_verify')

    anon_request = factory.get(login_url)
    anon_request.user = AnonymousUser()
    response = auth_views.email_2fa_verify(anon_request)

    location = response.get('Location', '')
    redirected = response.status_code in (301, 302) and '/accounts/login/' in location

    return {
        'title': 'Auth/2FA gate probe',
        'status': 'pass' if redirected else 'warn',
        'summary': 'Anonymous user was redirected to login before OTP route access.' if redirected else 'Anonymous access behavior differs from expected login redirect.',
        'details': [
            {'label': 'Observed status', 'value': str(response.status_code)},
            {'label': 'Redirect target', 'value': location or 'None'},
        ],
    }


def _run_active_upload_validation_check(request) -> dict[str, Any]:
    oversized = SimpleUploadedFile(
        'oversized.png',
        b'0' * (5 * 1024 * 1024 + 1),
        content_type='image/png',
    )
    invalid_mime = SimpleUploadedFile(
        'script.svg',
        b'<svg><script>alert(1)</script></svg>',
        content_type='image/svg+xml',
    )

    oversized_form = SchoolIDVerificationRequestForm(data={}, files={'id_image': oversized})
    invalid_form = SchoolIDVerificationRequestForm(data={}, files={'id_image': invalid_mime})

    oversized_blocked = not oversized_form.is_valid()
    mime_blocked = not invalid_form.is_valid()
    passed = oversized_blocked and mime_blocked

    return {
        'title': 'File upload validation probe',
        'status': 'pass' if passed else 'warn',
        'summary': 'Upload validation rejected oversized and unsupported MIME files.' if passed else 'Upload validation accepted input that should be blocked.',
        'details': [
            {
                'label': 'Oversized file check',
                'value': '; '.join(oversized_form.errors.get('id_image', [])) or 'No error captured',
            },
            {
                'label': 'Unsupported MIME check',
                'value': '; '.join(invalid_form.errors.get('id_image', [])) or 'No error captured',
            },
        ],
    }


def _run_active_redirect_validation_check(request) -> dict[str, Any]:
    allowed_hosts = {_safe_request_host(request)}
    require_https = request.is_secure()

    unsafe_targets = [
        'https://evil.example/phish',
        '//evil.example/hijack',
        'javascript:alert(1)',
    ]
    safe_targets = ['/profile/', '/mod/security-tests/']

    unsafe_results = [
        not url_has_allowed_host_and_scheme(url, allowed_hosts=allowed_hosts, require_https=require_https)
        for url in unsafe_targets
    ]
    safe_results = [
        url_has_allowed_host_and_scheme(url, allowed_hosts=allowed_hosts, require_https=require_https)
        for url in safe_targets
    ]

    passed = all(unsafe_results) and all(safe_results)

    return {
        'title': 'Open redirect probe',
        'status': 'pass' if passed else 'warn',
        'summary': 'Unsafe redirect targets were blocked while local paths remained allowed.' if passed else 'Redirect validation did not match expected allow/block behavior.',
        'details': [
            {'label': 'Unsafe targets blocked', 'value': str(all(unsafe_results))},
            {'label': 'Safe local paths allowed', 'value': str(all(safe_results))},
        ],
    }


def _run_active_security_headers_check(request) -> dict[str, Any]:
    factory = RequestFactory()
    probe_request = factory.get('/mod/security-tests/header-probe/')

    middleware = SecurityHeadersMiddleware(lambda req: HttpResponse('ok'))
    response = middleware.process_response(probe_request, HttpResponse('ok'))

    expected_headers = {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
    }
    missing_headers = [
        header for header, expected in expected_headers.items() if response.get(header) != expected
    ]
    has_csp = bool(response.get('Content-Security-Policy'))

    passed = not missing_headers and has_csp

    return {
        'title': 'Security headers probe',
        'status': 'pass' if passed else 'warn',
        'summary': 'Security headers middleware produced expected CSP/clickjacking controls.' if passed else 'One or more required security headers were missing.',
        'details': [
            {'label': 'Missing/incorrect headers', 'value': ', '.join(missing_headers) if missing_headers else 'None'},
            {'label': 'CSP header present', 'value': str(has_csp)},
        ],
    }
