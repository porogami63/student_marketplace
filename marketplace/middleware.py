# Security Middleware & Django Settings Configuration
# Implements FERPA, PCI DSS, NIST, and ISO/IEC 27001 compliance

from django.utils.deprecation import MiddlewareMixin
from django.http import HttpResponse
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from marketplace.security import AuditLog, get_client_ip
from marketplace.email_2fa import (
    SESSION_2FA_NEXT_URL,
    SESSION_2FA_PENDING_USER,
    clear_pending_state,
    get_active_session_challenge,
    is_verified_for_user,
    issue_login_challenge,
    set_pending_challenge,
)
import logging

security_logger = logging.getLogger('security')


class OAuthFlowDebugMiddleware(MiddlewareMixin):
    """DEBUG-only: log allauth Google OAuth flow requests/responses."""

    def process_request(self, request):
        if request.path.startswith('/accounts/google/'):
            try:
                has_session = 'sessionid' in request.COOKIES
                security_logger.warning(
                    "OAUTH google request %s %s has_session=%s query=%s",
                    request.method,
                    request.path,
                    has_session,
                    request.META.get('QUERY_STRING', ''),
                )
            except Exception:
                # Never block request handling due to debug logging.
                pass
        return None

    def process_response(self, request, response):
        if request.path.startswith('/accounts/google/'):
            try:
                location = response.get('Location', '')
                security_logger.warning(
                    "OAUTH google response %s %s status=%s location=%s",
                    request.method,
                    request.path,
                    getattr(response, 'status_code', 'unknown'),
                    location,
                )
            except Exception:
                pass
        return response


class EmailTwoFactorMiddleware(MiddlewareMixin):
    """Require email-based OTP verification after authentication."""

    EXEMPT_PREFIXES = (
        '/static/',
        '/media/',
        '/accounts/login/',
        '/accounts/logout/',
        '/accounts/email-2fa/',
        '/accounts/confirm-email/',
        '/accounts/password/reset/',
    )

    def _is_exempt_path(self, path):
        return any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES)

    def process_request(self, request):
        if not request.user.is_authenticated:
            return None

        if self._is_exempt_path(request.path):
            return None

        if is_verified_for_user(request.session, request.user):
            return None

        pending_user_id = request.session.get(SESSION_2FA_PENDING_USER)
        if pending_user_id not in (None, request.user.pk):
            clear_pending_state(request.session)

        try:
            challenge = get_active_session_challenge(request.session, request.user)
        except Exception:
            security_logger.exception(
                'Unable to load email 2FA challenge for user=%s path=%s',
                request.user.username,
                request.path,
            )
            clear_pending_state(request.session)
            logout(request)
            messages.error(request, 'Could not verify your session. Please sign in again.')
            return redirect('account_login')

        if challenge is None:
            try:
                challenge = issue_login_challenge(request.user, ip_address=get_client_ip(request))
            except Exception:
                security_logger.exception(
                    'Unable to send email 2FA challenge for user=%s path=%s',
                    request.user.username,
                    request.path,
                )
                clear_pending_state(request.session)
                logout(request)
                messages.error(request, 'Could not send your verification code. Please sign in again.')
                return redirect('account_login')

            set_pending_challenge(request.session, request.user, challenge)

        if request.method == 'GET':
            request.session[SESSION_2FA_NEXT_URL] = request.get_full_path()

        return redirect('account_email_2fa_verify')


class SecurityHeadersMiddleware(MiddlewareMixin):
    """Add security headers to all responses (NIST, ISO 27001)"""
    
    def process_response(self, request, response):
        # Prevent MIME type sniffing
        response['X-Content-Type-Options'] = 'nosniff'
        
        # Enable XSS protection (browser-level)
        response['X-XSS-Protection'] = '1; mode=block'
        
        # Prevent clickjacking
        response['X-Frame-Options'] = 'DENY'
        
        # Referrer policy
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Permissions policy (formerly Feature-Policy)
        response['Permissions-Policy'] = (
            'accelerometer=(), '
            'camera=(), '
            'geolocation=(), '
            'gyroscope=(), '
            'magnetometer=(), '
            'microphone=(), '
            'payment=(), '
            'usb=()'
        )
        
        # Content Security Policy (CSP) - prevent XSS
        # Extend safely via settings.CSP_*_SRC_EXTRA (comma-separated env vars).
        script_src = [
            "'self'",
            "'unsafe-inline'",
            "https://cdn.jsdelivr.net",
            "https://js.stripe.com",
        ] + list(getattr(settings, 'CSP_SCRIPT_SRC_EXTRA', []) or [])

        style_src = [
            "'self'",
            "'unsafe-inline'",
            "https://cdn.jsdelivr.net",
            "https://fonts.googleapis.com",
        ] + list(getattr(settings, 'CSP_STYLE_SRC_EXTRA', []) or [])

        img_src = [
            "'self'",
            "data:",
            "https:",
        ] + list(getattr(settings, 'CSP_IMG_SRC_EXTRA', []) or [])

        font_src = [
            "'self'",
            "https://cdn.jsdelivr.net",
            "https://fonts.gstatic.com",
        ]

        connect_src = [
            "'self'",
            "https://api.stripe.com",
            "https://m.stripe.network",
            "https://r.stripe.com",
        ] + list(getattr(settings, 'CSP_CONNECT_SRC_EXTRA', []) or [])

        frame_src = [
            "'self'",
            "https://js.stripe.com",
            "https://hooks.stripe.com",
        ] + list(getattr(settings, 'CSP_FRAME_SRC_EXTRA', []) or [])

        response['Content-Security-Policy'] = (
            f"default-src 'self'; "
            f"script-src {' '.join(script_src)}; "
            f"style-src {' '.join(style_src)}; "
            f"img-src {' '.join(img_src)}; "
            f"font-src {' '.join(font_src)}; "
            f"connect-src {' '.join(connect_src)}; "
            f"frame-src {' '.join(frame_src)}; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        
        return response


class AuditLoggingMiddleware(MiddlewareMixin):
    """Log security-relevant activities (FERPA audit trail)"""
    
    SENSITIVE_PATHS = [
        '/admin/',
        '/accounts/login/',
        '/accounts/logout/',
        '/accounts/signup/',
        '/marketplace/profile/',
        '/payment/',
        '/api/auth/',
    ]
    
    def process_request(self, request):
        # Check if path is sensitive
        for path in self.SENSITIVE_PATHS:
            if request.path.startswith(path):
                # Log the access
                if request.user.is_authenticated:
                    AuditLog.objects.create(
                        event_type='api_call' if request.path.startswith('/api/') else 'data_access',
                        severity='warning',
                        user=request.user,
                        ip_address=get_client_ip(request),
                        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                        resource=request.path,
                        details={
                            'method': request.method,
                            'query_string': request.META.get('QUERY_STRING', '')[:255],
                        }
                    )
        
        return None


class RateLimitMiddleware(MiddlewareMixin):
    """Implement rate limiting (NIST, PCI DSS)"""
    
    def get_rate_limits(self):
        """Get rate limits from Django settings for flexibility in testing/production"""
        from django.conf import settings
        return {
            '/accounts/login/': (
                settings.RATE_LIMIT_LOGIN_ATTEMPTS,
                settings.RATE_LIMIT_LOGIN_WINDOW
            ),
            '/api/': (
                settings.RATE_LIMIT_API_REQUESTS,
                settings.RATE_LIMIT_API_WINDOW
            ),
            '/marketplace/search/': (
                settings.RATE_LIMIT_SEARCH_REQUESTS,
                settings.RATE_LIMIT_SEARCH_WINDOW
            ),
        }
    
    def process_request(self, request):
        from django.core.cache import cache
        import time
        
        rate_limits = self.get_rate_limits()
        
        # Determine rate limit for this path
        limit_info = None
        for path, (limit, window) in rate_limits.items():
            if request.path.startswith(path):
                limit_info = (limit, window)
                break
        
        if not limit_info:
            return None
        
        limit_count, limit_window = limit_info
        client_ip = get_client_ip(request)
        cache_key = f"rate_limit:{client_ip}:{request.path}"
        
        request_count = cache.get(cache_key, 0)
        
        if request_count >= limit_count:
            security_logger.warning(
                f"Rate limit exceeded for {client_ip} on {request.path}"
            )
            AuditLog.objects.create(
                event_type='security_alert',
                severity='warning',
                user=request.user if request.user.is_authenticated else None,
                ip_address=client_ip,
                resource=request.path,
                details={'alert_type': 'rate_limit_exceeded', 'count': request_count, 'limit': limit_count}
            )
            return HttpResponse('Too many requests. Please try again later.', status=429)
        
        cache.set(cache_key, request_count + 1, limit_window)
        
        return None


class MaintenanceModeMiddleware(MiddlewareMixin):
    """Optional write-freeze mode for safe migrations/cutovers.

    When settings.MAINTENANCE_MODE is True, this blocks non-idempotent requests
    (POST/PUT/PATCH/DELETE) for non-superusers, while still allowing GET/HEAD.
    """

    SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}

    def process_request(self, request):
        if not getattr(settings, 'MAINTENANCE_MODE', False):
            return None

        if request.method in self.SAFE_METHODS:
            return None

        if request.user.is_authenticated and request.user.is_superuser:
            return None

        return HttpResponse('Maintenance in progress. Please try again shortly.', status=503)


class IPWhitelistMiddleware(MiddlewareMixin):
    """Optional: Whitelist admin paths to specific IPs"""
    
    ADMIN_IP_WHITELIST = []  # Set in settings.py
    
    def process_request(self, request):
        # Only check admin paths
        if not request.path.startswith('/admin/'):
            return None
        
        # Get whitelisted IPs from settings
        from django.conf import settings
        admin_ips = getattr(settings, 'ADMIN_IP_WHITELIST', [])

        if not admin_ips:  # If empty, allow all (no restriction)
            return None

        client_ip = get_client_ip(request)

        if client_ip not in admin_ips:
            security_logger.critical(
                f"Unauthorized admin access attempt from {client_ip}"
            )
            AuditLog.objects.create(
                event_type='unauthorized_access',
                severity='critical',
                user=request.user if request.user.is_authenticated else None,
                ip_address=client_ip,
                resource='/admin/',
                details={'alert_type': 'unauthorized_admin_access'}
            )
            return HttpResponse('Access denied', status=403)

        return None
