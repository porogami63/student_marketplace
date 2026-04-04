# UBXchange Security Assessment

Date: 2026-04-01
Scope: Current implementation in this repository

This document summarizes:
- Mitigation strategies currently implemented
- STRIDE threat analysis
- DREAD risk assessment
- Code snippets and file evidence

## 1. Security Mitigation Strategies In Place

### 1.1 Authentication and Identity Protection

Key controls:
- Mandatory email verification for accounts
- Unique email enforcement
- Login through username or email
- Email OTP challenge after authentication

Evidence:
- [student_marketplace/settings.py](student_marketplace/settings.py#L163)
- [student_marketplace/settings.py](student_marketplace/settings.py#L164)
- [student_marketplace/settings.py](student_marketplace/settings.py#L165)
- [student_marketplace/settings.py](student_marketplace/settings.py#L66)
- [marketplace/middleware.py](marketplace/middleware.py#L60)
- [student_marketplace/urls.py](student_marketplace/urls.py#L13)

Code snippet:

~~~python
ACCOUNT_LOGIN_METHODS = {'email', 'username'}
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = 'mandatory'
~~~

~~~python
class EmailTwoFactorMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if not request.user.is_authenticated:
            return None
        if is_verified_for_user(request.session, request.user):
            return None
        return redirect('account_email_2fa_verify')
~~~

### 1.2 OTP Hardening

Key controls:
- OTP code hashing at rest
- Constant-time hash comparison
- Expiration window
- Max attempts
- Resend cooldown
- Sensitive-action OTP window

Evidence:
- [marketplace/email_2fa.py](marketplace/email_2fa.py#L71)
- [marketplace/email_2fa.py](marketplace/email_2fa.py#L186)
- [marketplace/email_2fa.py](marketplace/email_2fa.py#L192)
- [marketplace/email_2fa.py](marketplace/email_2fa.py#L264)
- [marketplace/email_2fa.py](marketplace/email_2fa.py#L273)
- [student_marketplace/settings.py](student_marketplace/settings.py#L185)
- [.env.example](.env.example#L28)
- [.env.example](.env.example#L29)
- [.env.example](.env.example#L30)
- [.env.example](.env.example#L32)

Code snippet:

~~~python
def hash_code(raw_code):
    return hashlib.sha256(raw_code.encode('utf-8')).hexdigest()

def verify_code(challenge, raw_code):
    incoming_hash = hash_code(raw_code)
    if hmac.compare_digest(challenge.code_hash, incoming_hash):
        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=['consumed_at'])
        return True
~~~

### 1.3 Session, CSRF, and Browser Hardening

Key controls:
- CSRF middleware in global stack
- Secure cookies in non-debug mode
- HttpOnly cookies
- HSTS and HTTPS redirect controls in non-debug mode
- Security headers and CSP middleware

Evidence:
- [student_marketplace/settings.py](student_marketplace/settings.py#L62)
- [student_marketplace/settings.py](student_marketplace/settings.py#L231)
- [student_marketplace/settings.py](student_marketplace/settings.py#L232)
- [student_marketplace/settings.py](student_marketplace/settings.py#L233)
- [student_marketplace/settings.py](student_marketplace/settings.py#L237)
- [student_marketplace/settings.py](student_marketplace/settings.py#L246)
- [student_marketplace/settings.py](student_marketplace/settings.py#L250)
- [marketplace/middleware.py](marketplace/middleware.py#L112)
- [marketplace/middleware.py](marketplace/middleware.py#L181)

Code snippet:

~~~python
response['X-Content-Type-Options'] = 'nosniff'
response['X-Frame-Options'] = 'DENY'
response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
response['Content-Security-Policy'] = (
    "default-src 'self'; ... form-action 'self'"
)
~~~

### 1.4 Authorization and Access Control

Key controls:
- Transaction participants only
- Conversation participants only
- Receipt viewers limited to buyer/seller
- Superuser checks for moderation routes

Evidence:
- [marketplace/views.py](marketplace/views.py#L1226)
- [marketplace/views.py](marketplace/views.py#L1374)
- [marketplace/views.py](marketplace/views.py#L1666)
- [marketplace/views.py](marketplace/views.py#L2908)
- [marketplace/views.py](marketplace/views.py#L1869)

Code snippet:

~~~python
if request.user not in [transaction.buyer, transaction.seller]:
    messages.error(request, "You don't have access to this transaction.")
    return redirect('marketplace:inbox')
~~~

### 1.5 Abuse Resistance and Availability

Key controls:
- Path-based global rate limiting middleware
- Rate-limit thresholds from environment
- Additional endpoint throttling on report creation
- Maintenance mode write freeze

Evidence:
- [marketplace/middleware.py](marketplace/middleware.py#L232)
- [marketplace/middleware.py](marketplace/middleware.py#L239)
- [marketplace/middleware.py](marketplace/middleware.py#L243)
- [marketplace/middleware.py](marketplace/middleware.py#L254)
- [student_marketplace/settings.py](student_marketplace/settings.py#L278)
- [student_marketplace/settings.py](student_marketplace/settings.py#L280)
- [marketplace/views.py](marketplace/views.py#L94)
- [marketplace/middleware.py](marketplace/middleware.py#L294)
- [student_marketplace/settings.py](student_marketplace/settings.py#L269)

Code snippet:

~~~python
if request_count >= limit_count:
    return HttpResponse('Too many requests. Please try again later.', status=429)
~~~

### 1.6 Audit Logging and Monitoring

Key controls:
- AuditLog and LoginAttempt models
- Login success/failure signal handlers
- Sensitive path audit middleware
- Rotating security/auth/payment log files
- Admin security dashboard and JSON audit export

Evidence:
- [marketplace/security.py](marketplace/security.py#L53)
- [marketplace/security.py](marketplace/security.py#L106)
- [marketplace/signals.py](marketplace/signals.py#L78)
- [marketplace/signals.py](marketplace/signals.py#L89)
- [marketplace/middleware.py](marketplace/middleware.py#L197)
- [student_marketplace/settings.py](student_marketplace/settings.py#L286)
- [student_marketplace/settings.py](student_marketplace/settings.py#L305)
- [marketplace/admin_site.py](marketplace/admin_site.py#L50)
- [marketplace/admin_site.py](marketplace/admin_site.py#L128)

Code snippet:

~~~python
AuditLog.objects.create(
    event_type='login_failure',
    severity='warning',
    user=None,
    ip_address=ip_address,
    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
)
~~~

### 1.7 Payment Security Controls

Key controls:
- Stripe keys from environment
- PaymentIntent metadata and amount/currency verification
- Sensitive payment actions require recent OTP verification
- No raw card PAN/CVV storage in app models

Evidence:
- [student_marketplace/settings.py](student_marketplace/settings.py#L210)
- [marketplace/views.py](marketplace/views.py#L2302)
- [marketplace/views.py](marketplace/views.py#L2313)
- [marketplace/views.py](marketplace/views.py#L2325)
- [marketplace/views.py](marketplace/views.py#L2523)
- [marketplace/views.py](marketplace/views.py#L2588)
- [marketplace/models.py](marketplace/models.py#L708)
- [SECURITY_README.md](SECURITY_README.md#L52)

Code snippet:

~~~python
if tx_meta and tx_meta != str(transaction.id):
    messages.error(request, "Payment reference mismatch. Please contact support.")
    return redirect('marketplace:payment_checkout', transaction_id=transaction.id)

if expected_amount is None or intent_amount != expected_amount or intent_currency != 'php':
    messages.error(request, "Payment reference mismatch. Please contact support.")
~~~

## 2. STRIDE Analysis

### 2.1 Spoofing

Threats:
- Account impersonation
- Session misuse for sensitive payment actions

Mitigations:
- Mandatory email verification
- OTP after authentication
- Sensitive-action OTP gate

Residual risk: Medium

Evidence:
- [student_marketplace/settings.py](student_marketplace/settings.py#L165)
- [marketplace/middleware.py](marketplace/middleware.py#L60)
- [marketplace/views.py](marketplace/views.py#L2523)

### 2.2 Tampering

Threats:
- Unauthorized changes to offers/favorites
- Forged payment references

Mitigations:
- CSRF middleware in stack
- Authorization checks
- Payment metadata and amount checks

Residual risk: High

Main reason:
- State-changing behavior exists on GET-driven flow in offer response and favorite toggle.

Evidence:
- [marketplace/views.py](marketplace/views.py#L1763)
- [marketplace/views.py](marketplace/views.py#L1770)
- [marketplace/views.py](marketplace/views.py#L891)
- [marketplace/views.py](marketplace/views.py#L894)
- [marketplace/views.py](marketplace/views.py#L2313)

### 2.3 Repudiation

Threats:
- User or admin denies an action happened

Mitigations:
- AuditLog model and event types
- Login attempt telemetry
- Moderation log and admin exportable audit report

Residual risk: Medium

Evidence:
- [marketplace/security.py](marketplace/security.py#L53)
- [marketplace/signals.py](marketplace/signals.py#L89)
- [marketplace/admin_site.py](marketplace/admin_site.py#L50)

### 2.4 Information Disclosure

Threats:
- Data leakage via insecure runtime profile or weak browser policy

Mitigations:
- Security headers and CSP
- Cookie hardening in non-debug mode
- Access restrictions on private resources

Residual risk: Medium

Main reasons:
- Current status snapshot indicates debug profile warnings.
- CSP includes unsafe-inline entries.

Evidence:
- [SECURITY_STATUS.md](SECURITY_STATUS.md#L13)
- [SECURITY_STATUS.md](SECURITY_STATUS.md#L26)
- [SECURITY_STATUS.md](SECURITY_STATUS.md#L27)
- [SECURITY_STATUS.md](SECURITY_STATUS.md#L28)
- [marketplace/middleware.py](marketplace/middleware.py#L144)
- [marketplace/middleware.py](marketplace/middleware.py#L151)

### 2.5 Denial of Service

Threats:
- Login/API flood attempts
- OTP resend abuse

Mitigations:
- Path-based throttling
- OTP resend cooldown
- Maintenance-mode write freeze

Residual risk: Medium

Main reason:
- Rate limiting uses Django cache and may need distributed backend in multi-instance deployment.

Evidence:
- [marketplace/middleware.py](marketplace/middleware.py#L232)
- [marketplace/middleware.py](marketplace/middleware.py#L254)
- [marketplace/email_2fa.py](marketplace/email_2fa.py#L192)
- [SECURITY_STATUS.md](SECURITY_STATUS.md#L176)

### 2.6 Elevation of Privilege

Threats:
- Non-admin access to moderation and security surfaces

Mitigations:
- Repeated superuser checks
- Admin site protections
- Optional IP allowlist middleware available

Residual risk: Medium

Evidence:
- [marketplace/views.py](marketplace/views.py#L1869)
- [student_marketplace/urls.py](student_marketplace/urls.py#L11)
- [marketplace/middleware.py](marketplace/middleware.py#L316)
- [student_marketplace/settings.py](student_marketplace/settings.py#L73)

## 3. DREAD Risk Assessment

Scoring model:
- 0 to 10 for each factor
- Average score = (Damage + Reproducibility + Exploitability + Affected users + Discoverability) / 5

### 3.1 Risk Table

| Threat | Damage | Reproducibility | Exploitability | Affected users | Discoverability | Average |
|---|---:|---:|---:|---:|---:|---:|
| GET-based state changes (offer response, favorite toggle) | 6 | 9 | 8 | 5 | 8 | 7.2 |
| Account lockout utility not enforced in login flow | 8 | 8 | 7 | 7 | 8 | 7.6 |
| Production hardening drift when debug profile is active | 9 | 6 | 7 | 9 | 9 | 8.0 |
| Rate limiting on local cache in multi-instance setup | 7 | 7 | 6 | 8 | 6 | 6.8 |
| CSP allows unsafe-inline sources | 7 | 6 | 5 | 7 | 7 | 6.4 |
| Placeholder compliance checks returning true | 5 | 9 | 6 | 8 | 9 | 7.4 |

### 3.2 DREAD Evidence

GET-based state changes:
- [marketplace/views.py](marketplace/views.py#L1763)
- [marketplace/views.py](marketplace/views.py#L1770)
- [marketplace/views.py](marketplace/views.py#L891)
- [marketplace/views.py](marketplace/views.py#L894)

Lockout not currently wired into login path:
- [marketplace/security.py](marketplace/security.py#L249)
- [SECURITY_STATUS.md](SECURITY_STATUS.md#L170)

Debug/hardening drift indicators:
- [student_marketplace/settings.py](student_marketplace/settings.py#L33)
- [SECURITY_STATUS.md](SECURITY_STATUS.md#L26)
- [SECURITY_STATUS.md](SECURITY_STATUS.md#L27)
- [SECURITY_STATUS.md](SECURITY_STATUS.md#L28)

Distributed rate-limit backend recommendation:
- [marketplace/middleware.py](marketplace/middleware.py#L254)
- [SECURITY_STATUS.md](SECURITY_STATUS.md#L176)

Placeholder compliance checks:
- [marketplace/security.py](marketplace/security.py#L508)
- [marketplace/security.py](marketplace/security.py#L542)
- [SECURITY_STATUS.md](SECURITY_STATUS.md#L54)

## 4. Recommended Next Actions (Priority Order)

1. Convert state-changing GET flows to POST with CSRF token validation.
2. Enforce account lockout in the active login/authentication path.
3. Enforce production-safe runtime profile checks for DEBUG, HTTPS redirect, and secure cookies.
4. Use shared cache storage (for example Redis) for rate-limit counters in multi-instance deployment.
5. Tighten CSP by minimizing unsafe-inline dependencies.
6. Replace placeholder compliance helper checks with concrete, evidence-backed checks.

## 5. Environment Knobs Relevant to This Assessment

Evidence:
- [.env.example](.env.example#L28)
- [.env.example](.env.example#L29)
- [.env.example](.env.example#L30)
- [.env.example](.env.example#L32)

Snippet:

~~~dotenv
# EMAIL_2FA_CODE_TTL_SECONDS=100
# EMAIL_2FA_MAX_ATTEMPTS=5
# EMAIL_2FA_RESEND_COOLDOWN_SECONDS=60
# EMAIL_2FA_SENSITIVE_WINDOW_SECONDS=600
~~~
