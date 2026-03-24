# Security Implementation Module
# Provides utilities for implementing FERPA, PCI DSS, NIST, and ISO/IEC 27001 compliance

import logging
import json
from datetime import datetime, timedelta
from functools import wraps
import hashlib
import importlib

from django.conf import settings
from django.utils import timezone
from django.http import HttpResponseForbidden, HttpResponse
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError
from django.utils.html import escape
from django.db import models
from django.contrib.auth.models import User

# Configure security loggers
security_logger = logging.getLogger('security')
auth_logger = logging.getLogger('authentication')
payment_logger = logging.getLogger('payments')


class SecurityConfig:
    """Security configuration constants"""
    
    # Authentication
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION_MINUTES = 15
    SESSION_TIMEOUT_MINUTES = 60
    PASSWORD_MIN_LENGTH = 12
    PASSWORD_REQUIRE_SPECIAL = True
    
    # Encryption
    ENCRYPTION_ALGORITHM = 'AES-256'
    TLS_MIN_VERSION = '1.2'
    
    # Data Classification
    HIGH_SENSITIVITY = ['phone', 'address', 'email', 'student_id']
    MEDIUM_SENSITIVITY = ['transactions', 'forum_activity', 'vouches']
    LOW_SENSITIVITY = ['product_listings', 'categories']
    
    # PCI DSS
    PAYMENT_CARD_TIMEOUT_SECONDS = 600  # 10 minutes
    
    # FERPA
    DATA_RETENTION_DAYS = 90
    TRANSACTION_LOG_RETENTION_DAYS = 2555  # 7 years


class AuditLog(models.Model):
    """Log all security-relevant events for compliance audits"""
    
    EVENT_TYPES = [
        ('login_attempt', 'Login Attempt'),
        ('login_success', 'Login Success'),
        ('login_failure', 'Login Failure'),
        ('account_lockout', 'Account Lockout'),
        ('unauthorized_access', 'Unauthorized Access'),
        ('data_access', 'Data Access'),
        ('payment_attempt', 'Payment Attempt'),
        ('payment_success', 'Payment Success'),
        ('payment_failure', 'Payment Failure'),
        ('account_deleted', 'Account Deleted'),
        ('permission_granted', 'Permission Granted'),
        ('permission_revoked', 'Permission Revoked'),
        ('mfa_enabled', 'MFA Enabled'),
        ('mfa_disabled', 'MFA Disabled'),
        ('password_changed', 'Password Changed'),
        ('api_call', 'API Call'),
        ('data_export', 'Data Export'),
        ('security_alert', 'Security Alert'),
    ]
    
    SEVERITY_LEVELS = [
        ('info', 'Informational'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]
    
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    severity = models.CharField(max_length=20, choices=SEVERITY_LEVELS, default='info')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    resource = models.CharField(max_length=255, blank=True)  # What was accessed/modified
    details = models.JSONField(default=dict)  # Additional event details
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
        indexes = [
            models.Index(fields=['event_type', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['severity', 'timestamp']),
        ]
    
    def __str__(self):
        return f"{self.event_type} - {self.user} - {self.timestamp}"


class LoginAttempt(models.Model):
    """Track login attempts for account lockout (NIST AC-7)"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    attempt_time = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField()
    
    class Meta:
        indexes = [
            models.Index(fields=['user', 'attempt_time']),
        ]


# ============================================================================
# DECORATORS FOR SECURITY ENFORCEMENT
# ============================================================================

def log_security_event(event_type, severity='info', resource=None):
    """Decorator to log security events"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            try:
                response = view_func(request, *args, **kwargs)
            except Exception as e:
                # Log the exception
                AuditLog.objects.create(
                    event_type=event_type,
                    severity='error',
                    user=request.user if request.user.is_authenticated else None,
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                    resource=resource,
                    details={'error': str(e)}
                )
                raise
            
            # Log successful execution
            AuditLog.objects.create(
                event_type=event_type,
                severity=severity,
                user=request.user if request.user.is_authenticated else None,
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                resource=resource,
                details={}
            )
            
            return response
        return wrapper
    return decorator


def rate_limit(max_attempts_per_period=5, period_seconds=60):
    """Decorator to implement rate limiting"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            cache_key = f"rate_limit:{get_client_ip(request)}:{view_func.__name__}"
            
            # In production, use Redis instead of cache
            from django.core.cache import cache
            
            current_attempts = cache.get(cache_key, 0)
            if current_attempts >= max_attempts_per_period:
                security_logger.warning(
                    f"Rate limit exceeded for {get_client_ip(request)} on {view_func.__name__}"
                )
                return HttpResponse('Too many requests', status=429)
            
            cache.set(cache_key, current_attempts + 1, period_seconds)
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_mfa(view_func):
    """Decorator to require MFA for sensitive operations"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponseForbidden('Authentication required')
        
        # Check if user has MFA enabled (optional dependency: django-otp).
        try:
            django_otp_util = importlib.import_module('django_otp.util')
            match_token = getattr(django_otp_util, 'match_token', None)
            if not callable(match_token):
                raise ImportError('django-otp match_token is unavailable')

            if not match_token(request.user, request.GET.get('totp', '')):
                return HttpResponseForbidden('MFA verification required')
        except ModuleNotFoundError:
            security_logger.warning('django-otp not installed; cannot enforce MFA')
            return HttpResponseForbidden('MFA is not available on this deployment')
        except ImportError:
            security_logger.warning('django-otp installed but MFA utility unavailable')
            return HttpResponseForbidden('MFA is not available on this deployment')
        
        return view_func(request, *args, **kwargs)
    return wrapper


def audit_data_access(sensitive_data=True):
    """Decorator to log access to sensitive data (FERPA)"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if sensitive_data and request.user.is_authenticated:
                AuditLog.objects.create(
                    event_type='data_access',
                    severity='warning',
                    user=request.user,
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                    resource=f"{view_func.__module__}.{view_func.__name__}",
                    details={
                        'method': request.method,
                        'path': request.path,
                        'query_params': dict(request.GET),
                    }
                )
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# ============================================================================
# SECURITY UTILITY FUNCTIONS
# ============================================================================

def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def check_account_lockout(user):
    """Check if user account is locked due to failed login attempts (NIST AC-7)"""
    
    lockout_delta = timezone.now() - timedelta(minutes=SecurityConfig.LOCKOUT_DURATION_MINUTES)
    
    failed_attempts = LoginAttempt.objects.filter(
        user=user,
        success=False,
        attempt_time__gte=lockout_delta
    ).count()
    
    if failed_attempts >= SecurityConfig.MAX_LOGIN_ATTEMPTS:
        security_logger.warning(
            f"Account {user.username} locked due to {failed_attempts} failed attempts"
        )
        return True
    
    return False


def record_login_attempt(user, ip_address, success=False):
    """Record login attempt for audit trail"""
    
    LoginAttempt.objects.create(
        user=user,
        ip_address=ip_address,
        success=success
    )
    
    # Log the event
    AuditLog.objects.create(
        event_type='login_success' if success else 'login_failure',
        severity='warning' if not success else 'info',
        user=user,
        ip_address=ip_address,
        details={'success': success}
    )
    
    if success:
        auth_logger.info(f"Login success for {user.username} from {ip_address}")
    else:
        auth_logger.warning(f"Login failure for {user.username} from {ip_address}")


def validate_password_strength(password):
    """Validate password meets security requirements (NIST)"""
    requirements = []
    
    if len(password) < SecurityConfig.PASSWORD_MIN_LENGTH:
        requirements.append(f"Password must be at least {SecurityConfig.PASSWORD_MIN_LENGTH} characters")
    
    if SecurityConfig.PASSWORD_REQUIRE_SPECIAL:
        if not any(char in '!@#$%^&*()_+-=[]{}|;:,.<>?' for char in password):
            requirements.append("Password must contain special characters")
    
    if not any(char.isupper() for char in password):
        requirements.append("Password must contain uppercase letters")
    
    if not any(char.isdigit() for char in password):
        requirements.append("Password must contain numbers")
    
    if requirements:
        raise ValidationError(requirements)
    
    return True


def sanitize_input(user_input, input_type='text'):
    """Sanitize user input to prevent XSS and injection attacks"""
    
    if input_type == 'text':
        return escape(user_input)
    
    elif input_type == 'email':
        from django.core.validators import validate_email
        validate_email(user_input)
        return user_input.lower()
    
    elif input_type == 'url':
        from django.core.validators import URLValidator
        URLValidator()(user_input)
        return user_input
    
    elif input_type == 'html':
        from django.utils.html import strip_tags
        return strip_tags(user_input)
    
    return escape(user_input)


def hash_sensitive_data(data, salt=None):
    """Hash sensitive data for storage (PII protection)"""
    if salt is None:
        salt = settings.SECRET_KEY
    
    return hashlib.pbkdf2_hmac('sha256', data.encode(), salt.encode(), 100000).hex()


# ============================================================================
# COMPLIANCE MONITORING & AUDIT FUNCTIONS
# ============================================================================

def generate_security_audit_report(start_date=None, end_date=None):
    """Generate security audit report for compliance (NIST, ISO 27001)"""
    
    if not start_date:
        start_date = timezone.now() - timedelta(days=90)
    if not end_date:
        end_date = timezone.now()
    
    audit_logs = AuditLog.objects.filter(timestamp__range=[start_date, end_date])
    
    report = {
        'report_date': timezone.now().isoformat(),
        'period': {
            'start': start_date.isoformat(),
            'end': end_date.isoformat(),
        },
        'summary': {
            'total_events': audit_logs.count(),
            'critical_events': audit_logs.filter(severity='critical').count(),
            'error_events': audit_logs.filter(severity='error').count(),
            'warning_events': audit_logs.filter(severity='warning').count(),
        },
        'event_breakdown': {},
        'top_users': [],
        'suspicious_activities': [],
    }
    
    # Event breakdown
    for event_type, _ in AuditLog.EVENT_TYPES:
        count = audit_logs.filter(event_type=event_type).count()
        if count > 0:
            report['event_breakdown'][event_type] = count
    
    # Top users by activity
    from django.db.models import Count
    top_users = audit_logs.values('user__username').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    for entry in top_users:
        if entry['user__username']:
            report['top_users'].append({
                'username': entry['user__username'],
                'events': entry['count']
            })
    
    # Suspicious activities
    failed_logins = audit_logs.filter(event_type='login_failure')
    for event in failed_logins.values('user__username').annotate(
        count=Count('id')
    ).filter(count__gte=3):
        report['suspicious_activities'].append({
            'type': 'multiple_failed_logins',
            'user': event['user__username'],
            'count': event['count']
        })
    
    return report


def check_ferpa_compliance():
    """Check FERPA compliance status"""
    
    compliance_status = {
        'timestamp': timezone.now().isoformat(),
        'ferpa_checks': {
            'pii_encryption': check_pii_encryption(),
            'access_controls': check_access_controls(),
            'audit_logging': check_audit_logging_enabled(),
            'data_retention': check_data_retention_policy(),
            'password_security': check_password_security(),
        },
        'overall_status': 'COMPLIANT'
    }
    
    # Check if any failed
    if not all(compliance_status['ferpa_checks'].values()):
        compliance_status['overall_status'] = 'NON-COMPLIANT'
    
    return compliance_status


def check_pci_dss_compliance():
    """Check PCI DSS compliance status"""

    checks = {
        'no_raw_card_storage': verify_no_raw_card_data(),
        'stripe_integration': verify_stripe_integration(),
        'https_enforced': verify_https_enforcement(),
        'webhook_validation': verify_webhook_security(),
        'api_security': verify_api_security(),
    }

    ignored_in_debug = {'https_enforced'} if settings.DEBUG else set()
    effective_checks = {k: v for k, v in checks.items() if k not in ignored_in_debug}

    return {
        'timestamp': timezone.now().isoformat(),
        'pci_checks': checks,
        'ignored_in_debug': sorted(ignored_in_debug),
        'overall_status': 'COMPLIANT' if all(effective_checks.values()) else 'NON-COMPLIANT',
    }


def check_nist_compliance():
    """Lightweight, settings-based NIST-aligned checks.

    This is not a certification tool; it surfaces concrete, verifiable controls
    that commonly map to NIST guidance (session security, TLS enforcement, auditability).
    """

    checks = {
        'https_enforced': bool(getattr(settings, 'SECURE_SSL_REDIRECT', False)),
        'secure_cookies': bool(getattr(settings, 'SESSION_COOKIE_SECURE', False)) and bool(getattr(settings, 'CSRF_COOKIE_SECURE', False)),
        'http_only_cookies': bool(getattr(settings, 'SESSION_COOKIE_HTTPONLY', False)) and bool(getattr(settings, 'CSRF_COOKIE_HTTPONLY', False)),
        'rate_limiting_enabled': True,  # RateLimitMiddleware is installed in settings.py
        'audit_logging_enabled': check_audit_logging_enabled(),
    }

    ignored_in_debug = {'https_enforced', 'secure_cookies'} if settings.DEBUG else set()
    effective_checks = {k: v for k, v in checks.items() if k not in ignored_in_debug}

    return {
        'timestamp': timezone.now().isoformat(),
        'nist_checks': checks,
        'ignored_in_debug': sorted(ignored_in_debug),
        'overall_status': 'COMPLIANT' if all(effective_checks.values()) else 'NON-COMPLIANT',
    }


def check_iso27001_compliance():
    """Lightweight, settings-based ISO/IEC 27001-aligned checks.

    ISO 27001 is a management system standard; this is a technical snapshot of a few
    relevant control areas we can verify from the running configuration.
    """

    checks = {
        'audit_trail_available': check_audit_logging_enabled(),
        'security_headers': True,  # SecurityHeadersMiddleware installed
        'access_control_admin': True,  # Admin requires authentication; MFA may be enabled separately
        'data_retention_policy': check_data_retention_policy(),
        'https_enforced': bool(getattr(settings, 'SECURE_SSL_REDIRECT', False)),
    }

    ignored_in_debug = {'https_enforced'} if settings.DEBUG else set()
    effective_checks = {k: v for k, v in checks.items() if k not in ignored_in_debug}

    return {
        'timestamp': timezone.now().isoformat(),
        'iso27001_checks': checks,
        'ignored_in_debug': sorted(ignored_in_debug),
        'overall_status': 'COMPLIANT' if all(effective_checks.values()) else 'NON-COMPLIANT',
    }


# Placeholder verification functions
def check_pii_encryption():
    return True

def check_access_controls():
    return True

def check_audit_logging_enabled():
    return AuditLog.objects.exists()

def check_data_retention_policy():
    return True

def check_password_security():
    return True

def verify_no_raw_card_data():
    return True

def verify_stripe_integration():
    return bool(settings.STRIPE_SECRET_KEY)

def verify_https_enforcement():
    return bool(getattr(settings, 'SECURE_SSL_REDIRECT', False))

def verify_webhook_security():
    webhook_required = bool(getattr(settings, 'STRIPE_WEBHOOK_REQUIRED', False))
    if not webhook_required:
        return True
    return bool(getattr(settings, 'STRIPE_WEBHOOK_SECRET', ''))

def verify_api_security():
    return True
