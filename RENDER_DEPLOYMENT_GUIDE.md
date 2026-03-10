# Deploying U-Belt Student Marketplace to Render

This guide walks you through deploying your Django marketplace to Render.com.

## Prerequisites

- Render account (https://render.com)
- GitHub repository with your code
- All environment variables prepared

## Step-by-Step Deployment

### 1. Prepare Your Code

Ensure these files exist in your project root:

**requirements.txt** - Already exists, but make sure it includes:
```
Django>=5.0,<6.0
Pillow>=10.0.0
django-crispy-forms>=2.1
crispy-bootstrap5>=2024.1
django-allauth>=0.61.0
requests>=2.0
PyJWT>=2.0
cryptography>=42.0
google-generativeai>=0.3.0
python-dotenv>=1.0.0
psycopg2-binary>=2.9.0
gunicorn>=21.0.0
whitenoise>=6.6.0
stripe>=7.0.0
```

You'll need to add:
- `psycopg2-binary` - PostgreSQL database driver
- `gunicorn` - Production WSGI server
- `whitenoise` - Static file serving

### 2. Update Django Settings for Production

Update `student_marketplace/settings.py`:

```python
import os
import dj_database_url
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Security Settings for Production
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("DJANGO_SECRET_KEY environment variable not set")

DEBUG = os.environ.get('DEBUG', 'False') == 'True'

# Add your Render domain here
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Whitenoise Middleware (add as first middleware)
MIDDLEWARE = [
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Add this line first
    'django.middleware.security.SecurityMiddleware',
    # ... rest of middleware
]

# Database configuration
if os.environ.get('DATABASE_URL'):
    DATABASES = {
        'default': dj_database_url.config(
            default=os.environ.get('DATABASE_URL'),
            conn_max_age=600,
            conn_health_checks=True
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# CSRF and CORS settings
CSRF_TRUSTED_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',')
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True') == 'True'
SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'True') == 'True'
CSRF_COOKIE_SECURE = os.environ.get('CSRF_COOKIE_SECURE', 'True') == 'True'

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
```

### 3. Create Build Script

Create `build.sh` in your project root:

```bash
#!/bin/bash
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate
python manage.py setup_ubelt
```

Make it executable:
```bash
chmod +x build.sh
```

### 4. Create Web Service on Render

1. Go to https://render.com/dashboard
2. Click "New +" → "Web Service"
3. Connect your GitHub repository
4. Fill in the configuration:

   **Name:** `student-marketplace` (or your preferred name)
   
   **Region:** Choose closest to your users
   
   **Branch:** `main` (or your main branch)
   
   **Runtime:** `Python 3`
   
   **Build Command:** `./build.sh`
   
   **Start Command:** `gunicorn student_marketplace.wsgi:application`

### 5. Set Environment Variables

In Render dashboard, go to **Environment** and add these variables:

```
DJANGO_SECRET_KEY=<generate-a-secure-random-key>
DEBUG=False
ALLOWED_HOSTS=your-app-name.onrender.com,www.your-app-name.onrender.com
DATABASE_URL=<provided by Render PostgreSQL add-on>

# Stripe Keys
STRIPE_PUBLIC_KEY=pk_live_xxxxxxxxxxxx
STRIPE_SECRET_KEY=sk_live_xxxxxxxxxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxx

# Google OAuth (from Google Cloud Console)
SOCIALACCOUNT_PROVIDERS and SITE_ID configured in Django Admin

# Gemini API Key
GEMINI_API_KEY=AIza_xxxxxxxxxxxx

# Security
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
CSRF_TRUSTED_ORIGINS=https://your-app-name.onrender.com,https://www.your-app-name.onrender.com
```

### 6. Add PostgreSQL Database

1. In Render dashboard, click "New +" → "PostgreSQL"
2. Fill in the configuration:
   - **Name:** `student-marketplace-db`
   - **Database:** `marketplace`
   - **User:** `marketplace`
   - **Region:** Same as web service
   - **Version:** Latest available

3. Render will automatically provide `DATABASE_URL` environment variable

### 7. Configure Google Settings in Admin

After first deployment:

1. Visit: `https://your-app-name.onrender.com/admin/`
2. Login with superuser credentials
3. Go to **Sites** and update:
   - Domain: `your-app-name.onrender.com`
   - Name: `U-Belt Student Marketplace`
4. For Google OAuth:
   - Go to Social Applications and add Google provider
   - Set Client ID and Secret from Google Cloud Console

### 8. Generate Django Secret Key

Run this command locally to generate a secure key:

```python
from django.core.management.utils import get_random_secret_key
print(get_random_secret_key())
```

Copy the output to `DJANGO_SECRET_KEY` in Render environment.

### 9. Configure Google OAuth for Production

Add to Google Cloud Console:
- Authorized JavaScript origins: `https://your-app-name.onrender.com`
- Authorized redirect URIs: `https://your-app-name.onrender.com/accounts/google/login/callback/`

---

## Complete Environment Variables Reference

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `DJANGO_SECRET_KEY` | ✓ | Django secret key (never commit!) | Random 50-char string |
| `DEBUG` | ✗ | Debug mode (set to False in production) | `False` |
| `ALLOWED_HOSTS` | ✓ | Comma-separated allowed domains | `my-app.onrender.com` |
| `DATABASE_URL` | ✓ | PostgreSQL connection string | `postgres://user:pwd@host/db` |
| `STRIPE_PUBLIC_KEY` | ✓ | Stripe publishable key | `pk_live_...` |
| `STRIPE_SECRET_KEY` | ✓ | Stripe secret key | `sk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | ✓ | Stripe webhook signing secret | `whsec_...` |
| `GEMINI_API_KEY` | ✓ | Google Gemini API key | `AIza_...` |
| `SECURE_SSL_REDIRECT` | ✗ | Force HTTPS | `True` |
| `SESSION_COOKIE_SECURE` | ✗ | Security cookie flag | `True` |
| `CSRF_COOKIE_SECURE` | ✗ | CSRF cookie security flag | `True` |
| `CSRF_TRUSTED_ORIGINS` | ✗ | Trusted origins for CSRF | `https://my-app.onrender.com` |

---

## Obtaining Each Environment Variable

### DJANGO_SECRET_KEY
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### STRIPE_PUBLIC_KEY & STRIPE_SECRET_KEY & STRIPE_WEBHOOK_SECRET
1. Go to https://dashboard.stripe.com/apikeys
2. Copy **Publishable Key** → `STRIPE_PUBLIC_KEY`
3. Copy **Secret Key** → `STRIPE_SECRET_KEY`
4. Go to Webhooks and create endpoint for `https://your-app-name.onrender.com/payment/webhook/`
5. Copy **Signing Secret** → `STRIPE_WEBHOOK_SECRET`

### GEMINI_API_KEY
1. Go to https://makersuite.google.com/app/apikey
2. Click "Create API Key"
3. Copy the key

### Google OAuth Credentials
1. Go to https://console.cloud.google.com/
2. Create or select project
3. APIs & Services → Credentials → Create OAuth 2.0 Client ID
4. Configure in Django Admin after deployment

---

## Troubleshooting

### Static Files Not Loading
- Run: `python manage.py collectstatic`
- Ensure `whitenoise` middleware is first in `MIDDLEWARE` list
- Check database has data with: `python manage.py shell`

### Database Migrations Failed
- SSH into Render service
- Manually run: `python manage.py migrate`

### Collectstatic Failing
- Ensure all static files are in `/static/` directory
- Check file permissions

### Google OAuth Not Working
- Verify domain in Google Cloud Console matches your Render URL
- Update Sites in Django Admin
- Clear browser cookies and try again

### Stripe Webhook Not Working
- Ensure webhook endpoint is: `https://yourdomain.com/payment/webhook/`
- Check webhook secret matches `STRIPE_WEBHOOK_SECRET`

---

## Next Steps

1. Set up custom domain (optional)
2. Configure email sending (SendGrid, Mailgun, etc.)
3. Set up monitoring and error tracking (Sentry recommended)
4. Regular database backups

## Resources

- Render Django Guide: https://render.com/docs/deploy-django
- Stripe Integration: https://stripe.com/docs
- Google Generative AI: https://ai.google.dev
- Django Deployment: https://docs.djangoproject.com/en/stable/howto/deployment/
