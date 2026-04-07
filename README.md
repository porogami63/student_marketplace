# UBXchange (Student Marketplace)

A Django marketplace for students in Manila’s University Belt (U‑Belt): buy/sell textbooks, supplies, electronics, dorm items, and more across UST, FEU, UE, San Beda, UP Manila, DLSU, TIP Manila, CEU, LCCM, NTC, and other nearby schools.

This repo includes a security-focused admin experience and production hardening aligned with FERPA, PCI DSS, NIST guidance, and ISO/IEC 27001 (technical signals). For the detailed security/compliance write‑up, see `SECURITY_README.md`.

## Features

- Listings (create/edit/sell) with images
- Search + favorites + view counts
- Messaging between buyers/sellers
- Forum posts and replies
- Vouch + tier verification system (Grey → Yellow → Green → Blue)
- AI recommendations and chat (Google Gemini)
- Stripe checkout and transaction tracking
- Security admin dashboards (audit logs, login telemetry, compliance snapshot)

## Tech Stack

- Django 5.x, SQLite (dev), PostgreSQL (prod)
- Bootstrap 5 + vanilla JS
- django-allauth (Google OAuth)
- Stripe (PaymentIntents + Stripe.js)
- google-generativeai (Gemini)

## Quickstart (Development)

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

New-Item -Path . -Name ".env" -ItemType "file" -Force
python manage.py migrate
python manage.py setup_ubelt
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/.

## Environment Variables

Create a `.env` file next to `manage.py`.

Minimum for development (Gemini features):

```env
DEBUG=True
GEMINI_API_KEY=AIza_...
```

Stripe (payments):

```env
STRIPE_PUBLIC_KEY=pk_test_...
STRIPE_SECRET_KEY=sk_test_...

# Only set these once you enable Stripe webhooks (refunds/payment lifecycle sync)
STRIPE_WEBHOOK_REQUIRED=False
STRIPE_WEBHOOK_SECRET=whsec_...
```

Production hardening (recommended):

```env
DEBUG=False
DJANGO_SECRET_KEY=...
ALLOWED_HOSTS=your-app.onrender.com,www.your-app.onrender.com
CSRF_TRUSTED_ORIGINS=https://your-app.onrender.com,https://www.your-app.onrender.com

SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

# Media uploads on Render (attach a Persistent Disk and use its mount path)
MEDIA_ROOT=/var/data/media
# Optional compatibility mode if you do not have a separate media server/CDN yet
SERVE_MEDIA_IN_PRODUCTION=True
```

Optional CSP extensions (only set when adding integrations like Google Maps):

```env
CSP_SCRIPT_SRC_EXTRA=https://maps.googleapis.com,https://maps.gstatic.com
CSP_STYLE_SRC_EXTRA=
CSP_IMG_SRC_EXTRA=https://maps.gstatic.com,https://maps.googleapis.com
CSP_CONNECT_SRC_EXTRA=https://maps.googleapis.com
CSP_FRAME_SRC_EXTRA=
```

## Google OAuth (allauth)

1. Create Google OAuth credentials in Google Cloud Console.
2. In Django Admin, configure **Sites** and **Social Applications**.
3. Use these callback URLs:
   - Dev: `http://localhost:8000/accounts/google/login/callback/`
   - Prod: `https://yourdomain.com/accounts/google/login/callback/`

## Admin

- Default admin: `/admin/`
- Security dashboards are available under the custom security admin site routes (see `marketplace/admin_site.py`).

## Deployment (Render)

1. Set `DEBUG=False`, `DJANGO_SECRET_KEY`, `ALLOWED_HOSTS`, `DATABASE_URL`.
2. Ensure `build.sh` is used (installs deps, collects static, migrates, seeds schools).
3. Set Stripe/Gemini environment variables.
4. Deploy and run `python manage.py check`.

## Vouch + Verification (How tiers work)

- Grey: default / incomplete profile
- Yellow: complete profile
- Green: at least 1 completed transaction and (forum activity or vouches)
- Blue: admin ID verified and 20+ completed transactions

## Troubleshooting

- Gemini not working: verify `GEMINI_API_KEY` is set and restart server.
- Stripe UI not loading: verify CSP allows Stripe (already configured) and keys exist.
- OAuth redirect mismatch: check Google Console redirect URI + Django **Sites** domain.

## Security & Compliance

See `SECURITY_README.md` for a detailed description of the security features, auditability, and the compliance signals implemented.
# Run security tests
python manage.py test marketplace.tests.test_security -v 2
```

### Required Environment Variables (Security)

```env
# Django Security
DJANGO_SECRET_KEY=<secure-key>
DEBUG=False

# HTTPS Enforcement
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

# Payment Processing (PCI DSS)
STRIPE_PUBLIC_KEY=pk_live_...
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_WEBHOOK_REQUIRED=False

# CSP extensions (for future integrations like Google Maps)
# Comma-separated list of origins, e.g. "https://maps.googleapis.com,https://maps.gstatic.com"
CSP_SCRIPT_SRC_EXTRA=
CSP_STYLE_SRC_EXTRA=
CSP_IMG_SRC_EXTRA=
CSP_CONNECT_SRC_EXTRA=
CSP_FRAME_SRC_EXTRA=

# AI API (Secured)
GEMINI_API_KEY=AIza_...
```

---

## Google OAuth Setup

### 1. Create Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Navigate to "APIs & Services" > "Credentials"
4. Click "Create Credentials" > "OAuth client ID"
5. Choose "Web application"
6. Add authorized redirect URIs:
   - Development: `http://localhost:8000/accounts/google/login/callback/`
   - Production: `https://yourdomain.com/accounts/google/login/callback/`
7. Copy your **Client ID** and **Client Secret**

### 2. Configure in Django Admin

1. Run `python manage.py runserver`
2. Go to `http://localhost:8000/admin/` and login
3. Navigate to **Sites** and ensure domain matches (e.g., `localhost:8000`)
4. Go to **Social applications** and click "Add"
5. Fill in:
   - **Provider:** Google
   - **Name:** Google
   - **Client id:** Your Client ID
   - **Secret key:** Your Client Secret
   - **Sites:** Select your site
6. Click Save

### 3. Test Google Login

Visit `http://localhost:8000/accounts/login/` and click "Sign in with Google".

---

## Stripe Payment Integration

For payment functionality:

1. Visit [Stripe Dashboard](https://dashboard.stripe.com/apikeys)
2. Copy your **Publishable Key** (pk_test_...)
3. Copy your **Secret Key** (sk_test_...)
4. Set up webhook endpoint for transaction confirmations

---

## Deployment to Render

### 1. Prepare Your Code

Ensure `requirements.txt` includes production dependencies:
```
Django>=5.0,<6.0
psycopg2-binary>=2.9.0
gunicorn>=21.0.0
whitenoise>=6.6.0
```

### 2. Create Build Script

Create `build.sh` in project root:

```bash
#!/bin/bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
python manage.py setup_ubelt
```

### 3. Set Production Environment Variables

| Variable | Value |
|----------|-------|
| `DJANGO_SECRET_KEY` | Generate with: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `your-app-name.onrender.com,www.your-app-name.onrender.com` |
| `DATABASE_URL` | Provided by Render PostgreSQL |
| `GEMINI_API_KEY` | Your Google Gemini API key |
| `STRIPE_PUBLIC_KEY` | From Stripe dashboard |
| `STRIPE_SECRET_KEY` | From Stripe dashboard |
| `STRIPE_WEBHOOK_SECRET` | From Stripe webhooks |
| `STRIPE_WEBHOOK_REQUIRED` | `True` if you enable Stripe webhooks/refunds |
| `SECURE_SSL_REDIRECT` | `True` |
| `SESSION_COOKIE_SECURE` | `True` |
| `CSRF_COOKIE_SECURE` | `True` |
| `CSRF_TRUSTED_ORIGINS` | `https://your-app-name.onrender.com` |

Optional CSP extension vars (only set when needed): `CSP_SCRIPT_SRC_EXTRA`, `CSP_STYLE_SRC_EXTRA`, `CSP_IMG_SRC_EXTRA`, `CSP_CONNECT_SRC_EXTRA`, `CSP_FRAME_SRC_EXTRA`.

### 4. Create Services on Render

1. **Web Service:**
   - Runtime: Python 3
   - Build Command: `./build.sh`
   - Start Command: `gunicorn student_marketplace.wsgi:application`

2. **PostgreSQL Database:**
   - Name: `student-marketplace-db`
   - Database: `marketplace`
   - Region: Same as web service

### 5. Deploy

Push code to GitHub and Render will auto-deploy on push to main branch.

---

## Key Features Documentation

### Verification System (Vouch/Tier)

The vouch and verification system has four tiers:

| Tier | Color | Requirements |
|------|-------|--------------|
| Grey | ⚪ | New/inactive users |
| Yellow | 🟡 | Complete profile |
| Green | 🟢 | Transactions + Forum activity OR Vouches |
| Blue | 🔵 | 20+ Transactions + ID verified |

**How Vouches Work:**
- Users can leave vouches on seller profiles after transactions
- Vouches increment the seller's vouch count
- Tier updates automatically based on activity and verification status
- Notifications alert sellers when they receive vouches

**Data Model:**
```python
class Review:
    reviewer → User who gave the vouch
    seller → User who received it
    is_vouch → True for vouch, False for feedback
    created_at → When created
```

**Profile Fields:**
```python
class Profile:
    vouch_count → Total vouches received
    verification_tier → Current tier (grey/yellow/green/blue)
    forum_posts_count → Community activity
    total_sold / total_bought → Transaction history
    id_verified → Admin verification status
```

### AI Recommendations

The marketplace uses Google Gemini API to provide personalized recommendations:

- Analyzes user's favorite items
- Considers item categories and descriptions
- Takes into account user's school and profile
- Tracks browsing patterns
- Results are cached for 1 hour to respect rate limits

**Access:** Login and visit `/marketplace/recommended/`

---

## Troubleshooting

### Gemini API Issues

**"GEMINI_API_KEY not set"**
- Verify `.env` file exists in project root
- Check format: `GEMINI_API_KEY=AIza_your_key_here` (no quotes)
- Restart Django: `python manage.py runserver`

**"HTTP 403 - Invalid API Key"**
- Verify key is correct (copy again from Google AI Studio)
- Key may have been revoked—generate a new one
- Ensure key has access to Generative AI API

**"HTTP 429 - Rate Limited"**
- Check usage in [Google Cloud Console](https://console.cloud.google.com/billing)
- Set up billing alert
- Upgrade account tier if needed

### Database Issues

**Migration errors:**
```bash
python manage.py makemigrations
python manage.py migrate
```

**Reset database (development only):**
```bash
rm db.sqlite3
python manage.py migrate
python manage.py setup_ubelt
```

### Static Files Issues (Production)

If static files aren't loading on Render:
```bash
python manage.py collectstatic --noinput --clear
```

---

## Additional Resources

- [Django Documentation](https://docs.djangoproject.com/)
- [Google Generative AI API](https://ai.google.dev/)
- [Stripe Documentation](https://stripe.com/docs)
- [Render Deployment Docs](https://render.com/docs)
- [Bootstrap 5 Documentation](https://getbootstrap.com/docs/5.0/)
