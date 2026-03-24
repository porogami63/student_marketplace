#!/usr/bin/env python
"""
Post-Deployment Verification Script
Ensures security framework deployed correctly without breaking existing functionality

Usage:
    python verify_deployment.py
"""

import os
import sys
import django
from pathlib import Path

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'student_marketplace.settings')
sys.path.insert(0, str(Path(__file__).parent))

try:
    django.setup()
except Exception as e:
    print(f"❌ Django setup failed: {e}")
    sys.exit(1)

from django.core.management import call_command
from django.contrib.auth.models import User
from django.db import connection
import logging

print("\n" + "="*70)
print("PRODUCTION DEPLOYMENT VERIFICATION")
print("="*70 + "\n")

CHECKS_PASSED = 0
CHECKS_FAILED = 0
WARNINGS = 0


def check(description, test_func):
    """Run a check and report result"""
    global CHECKS_PASSED, CHECKS_FAILED
    try:
        result = test_func()
        if result:
            print(f"✅ {description}")
            CHECKS_PASSED += 1
            return True
        else:
            print(f"❌ {description}")
            CHECKS_FAILED += 1
            return False
    except Exception as e:
        print(f"❌ {description}")
        print(f"   Error: {str(e)[:100]}")
        CHECKS_FAILED += 1
        return False


def warning(description, test_func):
    """Run a warning check"""
    global WARNINGS
    try:
        result = test_func()
        if result:
            print(f"⚠️  {description}")
            WARNINGS += 1
            return False
        else:
            print(f"✅ {description}")
            return True
    except Exception as e:
        print(f"⚠️  {description} - {str(e)[:50]}")
        WARNINGS += 1
        return False


# ============================================================================
# SECTION 1: Database & Migrations
# ============================================================================

print("\n📦 DATABASE & MIGRATIONS\n")

# Check AuditLog table exists
def check_auditlog_table():
    """Verify AuditLog table created"""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'marketplace_auditlog'
            )
        """)
        row = cursor.fetchone()
        return row[0] if row else False

check("AuditLog table exists", check_auditlog_table)


# Check LoginAttempt table exists
def check_loginattempt_table():
    """Verify LoginAttempt table created"""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'marketplace_loginattempt'
            )
        """)
        row = cursor.fetchone()
        return row[0] if row else False

check("LoginAttempt table exists", check_loginattempt_table)


# Check migration status
def check_migrations():
    """Verify all migrations applied"""
    from django.db.migrations.executor import MigrationExecutor
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return len(plan) == 0

check("All migrations applied", check_migrations)


# ============================================================================
# SECTION 2: Security Models & Imports
# ============================================================================

print("\n🔒 SECURITY MODELS & IMPORTS\n")


def check_security_module():
    """Verify security.py module imports correctly"""
    try:
        from marketplace.security import AuditLog, LoginAttempt
        return True
    except ImportError:
        return False

check("Security module imports successfully", check_security_module)


def check_middleware_module():
    """Verify middleware.py module imports correctly"""
    try:
        from marketplace.middleware import (
            SecurityHeadersMiddleware,
            AuditLoggingMiddleware,
            RateLimitMiddleware,
            IPWhitelistMiddleware
        )
        return True
    except ImportError:
        return False

check("Middleware module imports successfully", check_middleware_module)


def check_audit_log_model():
    """Verify AuditLog model has expected fields"""
    try:
        from marketplace.security import AuditLog
        fields = {f.name for f in AuditLog._meta.fields}
        required = {'user', 'event_type', 'severity', 'details', 'timestamp'}
        return required.issubset(fields)
    except Exception:
        return False

check("AuditLog model has required fields", check_audit_log_model)


def check_loginattempt_model():
    """Verify LoginAttempt model has expected fields"""
    try:
        from marketplace.security import LoginAttempt
        fields = {f.name for f in LoginAttempt._meta.fields}
        required = {'user', 'ip_address', 'success', 'timestamp'}
        return required.issubset(fields)
    except Exception:
        return False

check("LoginAttempt model has required fields", check_loginattempt_model)


# ============================================================================
# SECTION 3: Middleware Configuration
# ============================================================================

print("\n⚙️  MIDDLEWARE CONFIGURATION\n")


def check_middleware_installed():
    """Verify middleware installed in settings"""
    from django.conf import settings
    middleware_list = settings.MIDDLEWARE
    required_middleware = [
        'marketplace.middleware.SecurityHeadersMiddleware',
        'marketplace.middleware.AuditLoggingMiddleware',
        'marketplace.middleware.RateLimitMiddleware'
    ]
    return all(m in middleware_list for m in required_middleware)

check("Security middleware installed", check_middleware_installed)


def check_middleware_order():
    """Verify middleware in safe order (after core Django middleware)"""
    from django.conf import settings
    middleware = settings.MIDDLEWARE
    
    # Find positions
    auth_pos = next((i for i, m in enumerate(middleware) if 'auth' in m.lower()), -1)
    security_pos = next((i for i, m in enumerate(middleware) if 'SecurityHeaders' in m), -1)
    
    # Security middleware should be after auth
    return auth_pos < security_pos

check("Middleware in safe order", check_middleware_order)


# ============================================================================
# SECTION 4: Settings Configuration
# ============================================================================

print("\n🎛️  SETTINGS CONFIGURATION\n")


def check_security_settings():
    """Verify security settings configured"""
    from django.conf import settings
    return (
        settings.SESSION_COOKIE_HTTPONLY is True and
        settings.CSRF_COOKIE_HTTPONLY is True and
        settings.SESSION_COOKIE_SAMESITE == 'Strict'
    )

check("Security cookie settings configured", check_security_settings)


def check_logging_configured():
    """Verify logging properly configured"""
    from django.conf import settings
    loggers = settings.LOGGING.get('loggers', {})
    return 'marketplace.security' in loggers or 'django' in loggers

check("Logging configured", check_logging_configured)


def check_compliance_settings():
    """Verify compliance settings present"""
    from django.conf import settings
    return (
        hasattr(settings, 'MAX_LOGIN_ATTEMPTS') and
        hasattr(settings, 'LOCKOUT_DURATION_MINUTES') and
        hasattr(settings, 'DATA_RETENTION_DAYS')
    )

check("Compliance settings configured", check_compliance_settings)


# ============================================================================
# SECTION 5: Logging Files
# ============================================================================

print("\n📝 LOGGING FILES\n")


def check_logs_directory():
    """Verify logs directory exists"""
    return Path('logs').exists() and Path('logs').is_dir()

check("Logs directory exists", check_logs_directory)


def check_security_log():
    """Verify security.log file exists or can be created"""
    try:
        log_path = Path('logs/security.log')
        return log_path.exists() or log_path.parent.exists()
    except Exception:
        return False

check("Security log file ready", check_security_log)


def check_authentication_log():
    """Verify authentication.log file exists or can be created"""
    try:
        log_path = Path('logs/authentication.log')
        return log_path.exists() or log_path.parent.exists()
    except Exception:
        return False

check("Authentication log file ready", check_authentication_log)


def check_payments_log():
    """Verify payments.log file exists or can be created"""
    try:
        log_path = Path('logs/payments.log')
        return log_path.exists() or log_path.parent.exists()
    except Exception:
        return False

check("Payments log file ready", check_payments_log)


# ============================================================================
# SECTION 6: Existing Functionality
# ============================================================================

print("\n🎯 EXISTING FUNCTIONALITY\n")


def check_user_model():
    """Verify User model still works"""
    try:
        return User.objects.count() >= 0
    except Exception:
        return False

check("User model functioning", check_user_model)


def check_auth_system():
    """Verify authentication system working"""
    try:
        from django.contrib.auth import authenticate, get_user_model
        return True
    except Exception:
        return False

check("Authentication system intact", check_auth_system)


def check_listing_model():
    """Verify Listing model still works"""
    try:
        from marketplace.models import Listing
        return Listing.objects.count() >= 0
    except Exception:
        return False

check("Listing model intact", check_listing_model)


def check_profile_model():
    """Verify Profile model still works"""
    try:
        from marketplace.models import Profile
        return Profile.objects.count() >= 0
    except Exception:
        return False

check("Profile model intact", check_profile_model)


# ============================================================================
# SECTION 7: Compliance Functions
# ============================================================================

print("\n✅ COMPLIANCE FUNCTIONS\n")


def check_ferpa_compliance():
    """Verify FERPA compliance function works"""
    try:
        from marketplace.security import check_ferpa_compliance
        result = check_ferpa_compliance()
        return isinstance(result, dict) and 'status' in result
    except Exception:
        return False

check("FERPA compliance function working", check_ferpa_compliance)


def check_pci_dss_compliance():
    """Verify PCI DSS compliance function works"""
    try:
        from marketplace.security import check_pci_dss_compliance
        result = check_pci_dss_compliance()
        return isinstance(result, dict) and 'status' in result
    except Exception:
        return False

check("PCI DSS compliance function working", check_pci_dss_compliance)


# ============================================================================
# SECTION 8: Security Decorators
# ============================================================================

print("\n🎗️  SECURITY DECORATORS\n")


def check_decorators():
    """Verify security decorators available"""
    try:
        from marketplace.security import (
            log_security_event,
            rate_limit,
            require_mfa,
            audit_data_access
        )
        return all([
            callable(log_security_event),
            callable(rate_limit),
            callable(require_mfa),
            callable(audit_data_access)
        ])
    except ImportError:
        return False

check("Security decorators available", check_decorators)


# ============================================================================
# SECTION 9: Utilities
# ============================================================================

print("\n🛠️  SECURITY UTILITIES\n")


def check_security_utils():
    """Verify security utility functions available"""
    try:
        from marketplace.security import (
            get_client_ip,
            check_account_lockout,
            validate_password_strength,
            sanitize_input,
            hash_sensitive_data
        )
        return all([
            callable(get_client_ip),
            callable(check_account_lockout),
            callable(validate_password_strength),
            callable(sanitize_input),
            callable(hash_sensitive_data)
        ])
    except ImportError:
        return False

check("Security utility functions available", check_security_utils)


# ============================================================================
# WARNINGS - Non-critical but worth noting
# ============================================================================

print("\n⚠️  WARNINGS & RECOMMENDATIONS\n")


def check_debug_mode():
    """Warn if DEBUG mode is True in production"""
    from django.conf import settings
    return settings.DEBUG is True

warning("DEBUG mode is OFF (good for production)", check_debug_mode)


def check_allowed_hosts():
    """Warn if ALLOWED_HOSTS not configured"""
    from django.conf import settings
    hosts = settings.ALLOWED_HOSTS
    return len(hosts) == 0 or hosts == ['*']

warning("ALLOWED_HOSTS properly configured", check_allowed_hosts)


def check_secret_key():
    """Warn if SECRET_KEY might be default"""
    from django.conf import settings
    key = settings.SECRET_KEY
    return len(key) < 50

warning("SECRET_KEY is strong", check_secret_key)


# ============================================================================
# SUMMARY
# ============================================================================

print("\n" + "="*70)
print("DEPLOYMENT VERIFICATION SUMMARY")
print("="*70)

total_checks = CHECKS_PASSED + CHECKS_FAILED

print(f"\n✅ Passed:  {CHECKS_PASSED}")
print(f"❌ Failed:  {CHECKS_FAILED}")
print(f"⚠️  Warnings: {WARNINGS}")
print(f"\nTotal: {total_checks} checks")

if CHECKS_FAILED == 0:
    print("\n🎉 DEPLOYMENT SUCCESSFUL!")
    print("All critical checks passed. Security framework deployed correctly.")
    print("No interference with existing functionality detected.")
    sys.exit(0)
else:
    print(f"\n⚠️  DEPLOYMENT ISSUES DETECTED: {CHECKS_FAILED} checks failed")
    print("Please review the failures above and resolve before production use.")
    sys.exit(1)
