# Security Summary

## What we did to secure the website
- We use Django security controls, CSRF protection, secure session settings, rate limiting, security headers, and account verification checks.
- Sensitive actions are logged, and admin/security views are protected behind access control.
- Payment flows use Stripe tokenization and do not store raw card data.

## How we protect the data
- Data is protected with authentication, authorization, CSRF defenses, secure cookies, and restricted browser policies.
- Security events and login activity are recorded in audit logs for traceability.
- Secrets and email settings are read from environment variables instead of being hardcoded.

## What happens to the data
- User and transaction data are stored in the site database.
- Security and auth events are written to logs for monitoring and review.
- Email verification and 2FA messages are sent through configured email backends.

## Potential incident response if a breach happens
- We would isolate the affected system, review logs, rotate exposed secrets, disable suspicious access, and notify the right admins.
- We would then assess impact, restore safe services, and follow any required user or platform reporting steps.

## Compliance notes
- FERPA: We keep audit trails and access controls to support student-data privacy.
- PCI DSS: We use Stripe tokenization so the app does not store raw card data.
- NIST: We use secure cookies, rate limiting, and logging to reduce common security risks.
- ISO/IEC 27001: We apply security headers, access control, and audit logging as part of a technical security baseline.

> Note: these are technical controls and compliance signals, not a formal certification.