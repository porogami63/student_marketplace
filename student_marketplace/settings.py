"""
Django settings for U-Belt Student Marketplace project.
"""

import os
from pathlib import Path
import dj_database_url

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use system env vars

BASE_DIR = Path(__file__).resolve().parent.parent

# Ensure log directory exists (Render build containers may not include it)
LOG_DIR = BASE_DIR / 'logs'
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # If the filesystem is read-only or otherwise restricted,
    # handlers will fall back to console-only where possible.
    pass

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY and not os.environ.get('DEBUG', 'True') == 'True':
    raise ValueError("DJANGO_SECRET_KEY environment variable is required in production")
if not SECRET_KEY:
    SECRET_KEY = 'dev-secret-key-change-in-production-needs-to-be-50-chars-long-1234567890'

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'crispy_forms',
    'crispy_bootstrap5',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'marketplace',
]

# Security & Compliance (Information Assurance)
INSTALLED_APPS += []  # AuditLog and LoginAttempt in marketplace app

MIDDLEWARE = [
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'marketplace.middleware.EmailTwoFactorMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Security & Compliance Middleware (Information Assurance)
    'marketplace.middleware.SecurityHeadersMiddleware',
    'marketplace.middleware.AuditLoggingMiddleware',
    'marketplace.middleware.RateLimitMiddleware',
    'marketplace.middleware.MaintenanceModeMiddleware',
    # 'marketplace.middleware.IPWhitelistMiddleware',  # Optional - uncomment to enable IP whitelisting
]

if DEBUG:
    MIDDLEWARE.append('marketplace.middleware.OAuthFlowDebugMiddleware')

ROOT_URLCONF = 'student_marketplace.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'marketplace.context_processors.categories_schools',
                'marketplace.context_processors.social_auth_status',
            ],
        },
    },
]

WSGI_APPLICATION = 'student_marketplace.wsgi.application'

# Database configuration
if os.environ.get('DATABASE_URL'):
    DATABASES = {
        'default': dj_database_url.config(
            default=os.environ.get('DATABASE_URL'),
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    sqlite_path = os.environ.get('SQLITE_PATH', '').strip()
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': sqlite_path or (BASE_DIR / 'db.sqlite3'),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-ph'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = 'media/'

# Render note: local filesystem is ephemeral unless you attach a Persistent Disk.
# Set MEDIA_ROOT to the mounted disk path (e.g., /var/data/media) in production.
_media_root_env = os.environ.get('MEDIA_ROOT', '').strip()
MEDIA_ROOT = Path(_media_root_env) if _media_root_env else (BASE_DIR / 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = 'marketplace:home'
LOGOUT_REDIRECT_URL = 'marketplace:home'

ACCOUNT_ADAPTER = 'marketplace.adapters.CustomAccountAdapter'

CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

# django-allauth configuration
SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# Allauth configuration
# allauth v65+ expects required fields to be marked with '*'.
ACCOUNT_SIGNUP_FIELDS = ['email*', 'username*', 'password1*', 'password2*']
ACCOUNT_LOGIN_METHODS = {'email', 'username'}
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = 'mandatory'
ACCOUNT_CONFIRM_EMAIL_ON_GET = True
ACCOUNT_SIGNUP_REDIRECT_URL = LOGIN_REDIRECT_URL

# Accounts created before this timestamp are auto-whitelisted for allauth
# mandatory email verification during login. Set empty string to disable.
ACCOUNT_LEGACY_EMAIL_WHITELIST_CUTOFF = os.environ.get(
    'ACCOUNT_LEGACY_EMAIL_WHITELIST_CUTOFF',
    '2026-04-07T00:00:00+08:00',
)

# Email delivery settings (email verification + email-based 2FA)
if DEBUG:
    EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
else:
    EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')

DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'UBXchange Security <noreply@ubxchange.local>')
SERVER_EMAIL = os.environ.get('SERVER_EMAIL', DEFAULT_FROM_EMAIL)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'False').lower() == 'true'
# Bound SMTP operations so unavailable mail hosts do not block web workers.
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', '10'))

# Email 2FA behavior
EMAIL_2FA_CODE_TTL_SECONDS = int(os.environ.get('EMAIL_2FA_CODE_TTL_SECONDS', '100'))
EMAIL_2FA_MAX_ATTEMPTS = int(os.environ.get('EMAIL_2FA_MAX_ATTEMPTS', '5'))
EMAIL_2FA_RESEND_COOLDOWN_SECONDS = int(os.environ.get('EMAIL_2FA_RESEND_COOLDOWN_SECONDS', '60'))
EMAIL_2FA_SENSITIVE_WINDOW_SECONDS = int(os.environ.get('EMAIL_2FA_SENSITIVE_WINDOW_SECONDS', '600'))
# Emergency-only switch: bypass email 2FA challenge flows to preserve availability.
EMAIL_2FA_EMERGENCY_BYPASS = os.environ.get('EMAIL_2FA_EMERGENCY_BYPASS', 'False').lower() == 'true'

# Social account settings
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_QUERY_EMAIL = True
SOCIALACCOUNT_LOGIN_ON_GET = True

GOOGLE_OAUTH_CLIENT_ID = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', os.environ.get('GOOGLE_CLIENT_ID', '')).strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', os.environ.get('GOOGLE_CLIENT_SECRET', '')).strip()

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': [
            'profile',
            'email',
        ],
        'AUTH_PARAMS': {
            'access_type': 'online',
        },
    }
}

# Fallback for environments where DB-backed SocialApp is not yet seeded.
if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:
    SOCIALACCOUNT_PROVIDERS['google']['APP'] = {
        'client_id': GOOGLE_OAUTH_CLIENT_ID,
        'secret': GOOGLE_OAUTH_CLIENT_SECRET,
        'key': '',
        # Keep fallback app hidden when a DB SocialApp also exists.
        'settings': {'hidden': True},
    }

# Stripe Configuration
# Store API keys in .env file for security
STRIPE_PUBLIC_KEY = os.environ.get('STRIPE_PUBLIC_KEY', '')
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

# If you add Stripe webhooks (refunds, payment status sync, disputes), set this to True in production.
STRIPE_WEBHOOK_REQUIRED = os.environ.get('STRIPE_WEBHOOK_REQUIRED', 'False').lower() == 'true'

# Optional CSP extension points for future integrations (e.g., Google Maps).
# Use full origins like "https://maps.googleapis.com".
CSP_SCRIPT_SRC_EXTRA = [v.strip() for v in os.environ.get('CSP_SCRIPT_SRC_EXTRA', '').split(',') if v.strip()]
CSP_STYLE_SRC_EXTRA = [v.strip() for v in os.environ.get('CSP_STYLE_SRC_EXTRA', '').split(',') if v.strip()]
CSP_IMG_SRC_EXTRA = [v.strip() for v in os.environ.get('CSP_IMG_SRC_EXTRA', '').split(',') if v.strip()]
CSP_CONNECT_SRC_EXTRA = [v.strip() for v in os.environ.get('CSP_CONNECT_SRC_EXTRA', '').split(',') if v.strip()]
CSP_FRAME_SRC_EXTRA = [v.strip() for v in os.environ.get('CSP_FRAME_SRC_EXTRA', '').split(',') if v.strip()]

# Security Settings for Production
if not DEBUG:
    # When behind a reverse proxy (Render, nginx), honor forwarded HTTPS.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    USE_X_FORWARDED_HOST = True
    ACCOUNT_DEFAULT_HTTP_PROTOCOL = 'https'

    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True') == 'True'
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # HSTS (enable only when you are confident HTTPS is always used).
    # Keep defaults conservative but present for `check --deploy`.
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '3600'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'False').lower() == 'true'
    SECURE_HSTS_PRELOAD = os.environ.get('SECURE_HSTS_PRELOAD', 'False').lower() == 'true'
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

# Enhanced Security Headers (NIST/ISO 27001)
SESSION_COOKIE_HTTPONLY = True
# OAuth (Google allauth) requires cookies on top-level cross-site redirects.
# SameSite=Strict breaks the callback flow (state/session mismatch).
SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = os.environ.get('CSRF_COOKIE_SAMESITE', 'Lax')
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_SECURITY_POLICY = {
    'default-src': ("'self'",),
    'script-src': ("'self'", "'unsafe-inline'"),
    'style-src': ("'self'", "'unsafe-inline'"),
    'img-src': ("'self'", "data:", "https:"),
}
X_FRAME_OPTIONS = 'DENY'

CSRF_TRUSTED_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',')
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in CSRF_TRUSTED_ORIGINS if origin.strip()]

# Compliance Settings (FERPA, PCI DSS, NIST, ISO 27001)
DATA_RETENTION_DAYS = 90

# Optional: enable a temporary write-freeze for safe database cutovers.
# When true, non-superusers cannot perform POST/PUT/PATCH/DELETE.
MAINTENANCE_MODE = os.environ.get('MAINTENANCE_MODE', 'False').lower() == 'true'

# Login & Account Lockout Settings (NIST AC-7)
# Adjust for testing: Set MAX_LOGIN_ATTEMPTS=20 and LOCKOUT_DURATION_MINUTES=5 in .env
MAX_LOGIN_ATTEMPTS = int(os.environ.get('MAX_LOGIN_ATTEMPTS', '20'))  # Increased for testing
LOCKOUT_DURATION_MINUTES = int(os.environ.get('LOCKOUT_DURATION_MINUTES', '5'))  # Reduced for testing

# Rate Limiting Thresholds (NIST AC-2)
# Environment variables for flexibility in testing/production
RATE_LIMIT_LOGIN_ATTEMPTS = int(os.environ.get('RATE_LIMIT_LOGIN_ATTEMPTS', '20'))  # 20 attempts
RATE_LIMIT_LOGIN_WINDOW = int(os.environ.get('RATE_LIMIT_LOGIN_WINDOW', '300'))  # per 5 minutes
RATE_LIMIT_API_REQUESTS = int(os.environ.get('RATE_LIMIT_API_REQUESTS', '100'))  # 100 requests
RATE_LIMIT_API_WINDOW = int(os.environ.get('RATE_LIMIT_API_WINDOW', '3600'))  # per hour
RATE_LIMIT_SEARCH_REQUESTS = int(os.environ.get('RATE_LIMIT_SEARCH_REQUESTS', '30'))  # 30 searches
RATE_LIMIT_SEARCH_WINDOW = int(os.environ.get('RATE_LIMIT_SEARCH_WINDOW', '60'))  # per minute

# Enhanced Logging Configuration (Security Audit Trail)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {name} {funcName}:{lineno} - {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'security_file': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'security.log'),
            'maxBytes': 10485760,  # 10MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        'auth_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'authentication.log'),
            'maxBytes': 10485760,  # 10MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
        'payment_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'payments.log'),
            'maxBytes': 10485760,  # 10MB
            'backupCount': 10,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'security': {
            'handlers': ['security_file', 'console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'authentication': {
            'handlers': ['auth_file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'payments': {
            'handlers': ['payment_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
