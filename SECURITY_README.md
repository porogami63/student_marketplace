# Security & Compliance (Production Hardening)

This document explains the security controls implemented in this project and how they map to common compliance expectations.

Important notes:
- This is a course/security-hardening project. The checklists here **do not constitute certification**.
- “COMPLIANT” on the admin screen means **technical signals are present** in the running configuration.

---

## Summary of Security Controls

### Authentication & Account Protection
- Django authentication + django-allauth (supports Google OAuth)
- Login telemetry recorded via signals (successful + failed attempts)
- Account lockout logic (based on failed attempts in a time window)
- Rate limiting middleware on sensitive endpoints (login, API, search)

### Session / CSRF
- Secure cookie settings are supported (`HttpOnly`, `Secure`, `SameSite`)
- CSRF protection on forms
- When `CSRF_COOKIE_HTTPONLY=True`, the frontend uses DOM-embedded CSRF tokens (not JS cookie reads)

### Security Headers + CSP
Applied globally via `SecurityHeadersMiddleware`:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy` locked down
- Content Security Policy (CSP) allowlisted for required third parties:
  - Stripe (`https://js.stripe.com`, `https://api.stripe.com`, etc.)
  - Chart.js CDN (jsdelivr)
  - Google Fonts

CSP is extendable via environment variables so future features don’t require code changes:
- `CSP_SCRIPT_SRC_EXTRA`
- `CSP_STYLE_SRC_EXTRA`
- `CSP_IMG_SRC_EXTRA`
- `CSP_CONNECT_SRC_EXTRA`
- `CSP_FRAME_SRC_EXTRA`

### Audit Logging & Evidence
- Security-relevant events are recorded to `AuditLog` (database-backed)
- Sensitive path access logging via `AuditLoggingMiddleware`
- Admin provides:
  - Audit logs view
  - Login attempts view
  - Downloadable JSON audit report

### Payments (PCI-oriented)
- Stripe PaymentIntents + Stripe.js tokenization
- No raw card data stored in the application
- CSP updated to permit Stripe scripts/frames/connect targets
- Webhook signature validation is treated as **required only if you enable webhooks**

Environment toggle:
- `STRIPE_WEBHOOK_REQUIRED=False` (default)
- Set `STRIPE_WEBHOOK_REQUIRED=True` in production once you add Stripe webhooks (refunds/payment lifecycle sync)

### AI (Gemini)
- Gemini key loaded from environment (`GEMINI_API_KEY`)
- Prompt/role formatting validated (Gemini requires roles `user` and `model`)

---

## Compliance Alignment (Technical Signals)

These checks are implemented in `marketplace/security.py` and are visible in the Security Admin compliance page.

### FERPA (privacy / auditability)
Signals include:
- Audit logging exists (evidence trail)
- Access controls (Django auth gates)
- Data retention policy hooks (project-level)

### PCI DSS (payments)
Signals include:
- No raw card storage (Stripe tokenization)
- Stripe integration enabled
- HTTPS enforcement (required in production)
- Webhook validation (required only when webhooks are enabled)

### NIST-oriented controls (lightweight)
Signals include:
- HTTPS enforcement
- Secure cookies
- HttpOnly cookies
- Rate limiting
- Audit logging

### ISO/IEC 27001 (technical snapshot)
Signals include:
- Audit trail availability
- Security headers
- Admin access control
- Retention policy signal
- HTTPS enforcement

#### Dev vs Production
To avoid breaking developer UX, the compliance screen may ignore some checks when `DEBUG=True` (e.g., HTTPS redirects/secure cookies). In production (`DEBUG=False`) those signals are enforced by configuration.

---

## Where to View Security Evidence (Admin)

- Default admin: `/admin/`
- Security dashboards (custom admin site):
  - Dashboard: `/admin/security/`
  - Compliance: `/admin/security/compliance/`
  - Audit report download: `/admin/security/audit-report.json`

---

## Production Checklist (Non-Disruptive)

### Required
- `DEBUG=False`
- `DJANGO_SECRET_KEY` set
- `ALLOWED_HOSTS` set
- `CSRF_TRUSTED_ORIGINS` set
- `SECURE_SSL_REDIRECT=True`
- `SESSION_COOKIE_SECURE=True`
- `CSRF_COOKIE_SECURE=True`

### Payments
- `STRIPE_PUBLIC_KEY`, `STRIPE_SECRET_KEY` set
- If webhooks/refunds are enabled:
  - `STRIPE_WEBHOOK_REQUIRED=True`
  - `STRIPE_WEBHOOK_SECRET=whsec_...`

### Google Maps (future)
When adding Maps, prefer a locked-down key (HTTP referrer restrictions) and only then extend CSP using the `CSP_*_SRC_EXTRA` variables.

---

## Quick Verification Commands

Run from the project root:

```bash
python manage.py check
```

Optional (shell):

```bash
python manage.py shell
```

```python
from marketplace.security import (
    check_ferpa_compliance,
    check_pci_dss_compliance,
    check_nist_compliance,
    check_iso27001_compliance,
    generate_security_audit_report,
)

print(check_ferpa_compliance())
print(check_pci_dss_compliance())
print(check_nist_compliance())
print(check_iso27001_compliance())
print(generate_security_audit_report())
```
