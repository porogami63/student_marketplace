# Environment Variables Quick Reference for Render Deployment

## Required Variables (Critical)

```
DJANGO_SECRET_KEY=<generate-new-secure-key>
DEBUG=False
ALLOWED_HOSTS=your-app-name.onrender.com,www.your-app-name.onrender.com
DATABASE_URL=<auto-provided-by-render-postgres>
STRIPE_PUBLIC_KEY=pk_live_...
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
GEMINI_API_KEY=AIza_...
```

## Optional but Recommended

```
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
CSRF_TRUSTED_ORIGINS=https://your-app-name.onrender.com
```

## How to Get Each Variable

### 1. DJANGO_SECRET_KEY
Generate locally:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 2. STRIPE_PUBLIC_KEY & SECRET_KEY & WEBHOOK_SECRET
- Dashboard: https://dashboard.stripe.com/apikeys
- Webhooks: Create endpoint at `https://your-render-domain.onrender.com/payment/webhook/`

### 3. GEMINI_API_KEY
- Get free API key: https://makersuite.google.com/app/apikey

### 4. Google OAuth (configure in Django Admin after deploy)
- Cloud Console: https://console.cloud.google.com/
- Need: Client ID & Client Secret

### 5. DATABASE_URL
- Render creates this automatically when you add PostgreSQL

## Deployment Checklist

- [ ] Fork/push code to GitHub
- [ ] Create build.sh file in root
- [ ] Update requirements.txt with: psycopg2-binary, gunicorn, whitenoise
- [ ] Update settings.py (database, static files, middleware, security settings)
- [ ] Generate DJANGO_SECRET_KEY
- [ ] Create Render Web Service
- [ ] Create Render PostgreSQL database
- [ ] Set all environment variables in Render
- [ ] Deploy (trigger through GitHub or manual)
- [ ] Run migrations (automatic via build.sh)
- [ ] Configure Google OAuth in Django Admin
- [ ] Test payment webhook
- [ ] Test Google login

## Key Settings.py Changes Needed

```python
# Add these imports
import dj_database_url
from pathlib import Path

# Database
DATABASES = {
    'default': dj_database_url.config(
        default=os.environ.get('DATABASE_URL'),
        conn_max_age=600,
    )
}

# Static files
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Whitenoise (add to top of MIDDLEWARE list)
MIDDLEWARE = [
    'whitenoise.middleware.WhiteNoiseMiddleware',
    # ... rest
]

# Security
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```
