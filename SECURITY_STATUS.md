# Security Status and Compliance Snapshot

Last updated: 2026-03-30
Project: UBXchange Student Marketplace

## Scope and Disclaimer

This document summarizes the current security posture based on implemented code and runtime checks.
It is a technical status report, not a formal certification or legal compliance attestation.

## Executive Status

Current runtime profile: Development mode (DEBUG=True).

### Deployment Security Check Result

Command run:

```bash
python manage.py check --deploy
```

Current warnings (5):

- security.W004: SECURE_HSTS_SECONDS not set in current runtime profile.
- security.W008: SECURE_SSL_REDIRECT is not True in current runtime profile.
- security.W012: SESSION_COOKIE_SECURE is not True in current runtime profile.
- security.W016: CSRF_COOKIE_SECURE is not True in current runtime profile.
- security.W018: DEBUG is True.

Important context:

- In `student_marketplace/settings.py`, HTTPS redirect and secure cookie settings are enabled when `DEBUG=False`.
- The warnings above reflect the current local/dev runtime configuration, not necessarily production configuration.

### In-App Compliance Check Snapshot

Command run:

```bash
python manage.py shell -c "from marketplace.security import check_ferpa_compliance, check_pci_dss_compliance, check_nist_compliance, check_iso27001_compliance; print(check_ferpa_compliance().get('overall_status')); print(check_pci_dss_compliance().get('overall_status')); print(check_nist_compliance().get('overall_status')); print(check_iso27001_compliance().get('overall_status'))"
```

Reported statuses in current environment:

- FERPA: COMPLIANT
- PCI DSS: COMPLIANT
- NIST: COMPLIANT
- ISO 27001: COMPLIANT

Note:

- These are lightweight, code-level self-checks in `marketplace/security.py`.
- Some helper checks are placeholders returning `True` and should not be treated as external audit evidence.

## Implemented Security Features

## 1. Core Django Security Controls

Implemented in `student_marketplace/settings.py` and middleware stack:

- `SecurityMiddleware` enabled.
- `CsrfViewMiddleware` enabled.
- `XFrameOptionsMiddleware` enabled.
- Password validators enabled (`UserAttributeSimilarity`, `MinimumLength`, `CommonPassword`, `NumericPassword`).
- `X_FRAME_OPTIONS = 'DENY'`.
- Session and CSRF cookie hardening options configured (`HttpOnly`, `SameSite`), with `Secure` flags enabled in non-debug mode.

## 2. Security Headers and Browser Hardening

Implemented by `marketplace/middleware.py` (`SecurityHeadersMiddleware`):

- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection: 1; mode=block`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy` with restrictive defaults
- Content-Security-Policy with controlled sources, including Stripe and CDN/font endpoints used by the app

Also configurable CSP extension points via environment variables:

- `CSP_SCRIPT_SRC_EXTRA`
- `CSP_STYLE_SRC_EXTRA`
- `CSP_IMG_SRC_EXTRA`
- `CSP_CONNECT_SRC_EXTRA`
- `CSP_FRAME_SRC_EXTRA`

## 3. Authentication and Account Telemetry

Implemented in `marketplace/signals.py` and `marketplace/security.py`:

- Successful and failed login attempts are recorded.
- Audit events are persisted in `AuditLog`.
- Login attempts are persisted in `LoginAttempt`.
- Google OAuth is implemented via django-allauth.

## 4. Rate Limiting and Abuse Protection

Implemented by `RateLimitMiddleware` in `marketplace/middleware.py`:

- Endpoint-scoped rate limiting for:
  - `/accounts/login/`
  - `/api/`
  - `/marketplace/search/`
- Returns HTTP 429 on limit exceed.
- Writes security alert audit entries for exceed events.

Configured thresholds in `student_marketplace/settings.py`:

- `RATE_LIMIT_LOGIN_ATTEMPTS`, `RATE_LIMIT_LOGIN_WINDOW`
- `RATE_LIMIT_API_REQUESTS`, `RATE_LIMIT_API_WINDOW`
- `RATE_LIMIT_SEARCH_REQUESTS`, `RATE_LIMIT_SEARCH_WINDOW`

## 5. Audit Trail and Security Logging

Implemented controls:

- DB audit model: `AuditLog` in `marketplace/security.py`.
- Failed/success login tracking: `LoginAttempt` in `marketplace/security.py`.
- Sensitive-path logging via `AuditLoggingMiddleware`.
- Rotating file logs configured in `student_marketplace/settings.py`:
  - `logs/security.log`
  - `logs/authentication.log`
  - `logs/payments.log`
- Custom admin security dashboard and downloadable JSON audit report in `marketplace/admin_site.py`.

## 6. Payment Security Controls

Implemented:

- Stripe integration keys loaded from environment.
- Payment model stores provider IDs/metadata (for example, `stripe_charge_id`) and not raw card PAN/CVV.
- CSP includes Stripe script/connect/frame endpoints.
- Optional webhook enforcement switch:
  - `STRIPE_WEBHOOK_REQUIRED`
  - `STRIPE_WEBHOOK_SECRET`

## 7. Operational Safety Controls

Implemented:

- `MAINTENANCE_MODE` write-freeze middleware blocks non-safe methods for non-superusers.
- Optional `IPWhitelistMiddleware` exists for admin route restriction (currently optional and not enabled by default).

## 8. Trust and Safety Features

Implemented in `marketplace/models.py` and admin:

- User reporting workflow (`UserReport`) with reason/status/appeal fields.
- Support ticket workflow (`SupportTicket`) for report handling.
- Moderation log model (`ModerationLog`) for administrative actions.

## Compliance Alignment Used in This Project

The project includes technical controls and internal checks aligned to these frameworks:

- FERPA: auditability and access monitoring signals.
- PCI DSS: payment-tokenization model and HTTPS/webhook checks.
- NIST (selected controls): lockout/rate limit/session hardening style controls.
- ISO/IEC 27001 (technical subset): audit trail, security headers, configuration controls.

These mappings are implementation-oriented and educational; they are not third-party certification artifacts.

## Current Gaps and Follow-Up Items

1. Runtime hardening mode
- Current status is DEBUG mode, so deploy-level protections are not fully active in this environment.

2. Lockout enforcement path
- Lockout utility exists (`check_account_lockout`) but is not currently invoked in the login flow.

3. Compliance helper depth
- Several helper functions in `marketplace/security.py` are placeholders returning `True`.

4. Rate-limit backend reliability
- Rate limiting uses Django cache. For multi-instance production, use shared cache (for example, Redis).

5. Search limiter route
- Rate limiter includes `/marketplace/search/`, but this route is not currently present in `marketplace/urls.py`.

## Production Hardening Checklist

Set and verify at deploy time:

- `DEBUG=False`
- Strong `DJANGO_SECRET_KEY`
- Correct `ALLOWED_HOSTS`
- Correct `CSRF_TRUSTED_ORIGINS`
- `SECURE_SSL_REDIRECT=True`
- `SESSION_COOKIE_SECURE=True`
- `CSRF_COOKIE_SECURE=True`
- `SECURE_HSTS_SECONDS` set to an appropriate value
- `SECURE_HSTS_INCLUDE_SUBDOMAINS` and `SECURE_HSTS_PRELOAD` reviewed before enabling

Payments:

- Set `STRIPE_PUBLIC_KEY` and `STRIPE_SECRET_KEY`
- If webhooks are enabled, set:
  - `STRIPE_WEBHOOK_REQUIRED=True`
  - `STRIPE_WEBHOOK_SECRET`

Operations:

- Use a shared cache backend for rate limiting in production.
- Review and optionally enable admin IP allowlisting.
- Replace placeholder compliance checks with concrete evidence checks.

## Evidence Sources

- `student_marketplace/settings.py`
- `marketplace/middleware.py`
- `marketplace/security.py`
- `marketplace/signals.py`
- `marketplace/admin_site.py`
- `marketplace/models.py`
- `SECURITY_README.md`
