# Cross-Method Anti-Scam Hardening: Additions Summary

This document summarizes all implemented additions for the cross-method anti-scam hardening pass across manual and card payment paths.

## Scope Completed

- Hardened manual payment verification rules and moderation gating.
- Added Stripe webhook endpoint with signature verification and idempotent handling.
- Added webhook-required credit-card completion mode with pending-first behavior.
- Strengthened method-specific input and evidence validation for GCash, bank transfer, and custom arrangements.
- Expanded risk and vigilance warnings across checkout and payment templates.
- Added focused regression coverage for hardening paths.

## Backend Changes

### marketplace/views.py

- Added stricter normalization and validation helpers for payment metadata:
  - `_normalize_whitespace`
  - `_validate_gcash_details`
  - `_validate_bank_details`
  - `_validate_other_arrangement_details`
- Added external-verification adapter stubs for manual methods:
  - `_external_verify_gcash_reference`
  - `_external_verify_bank_reference`
  - `_run_external_manual_verification`
- Refactored credit-card finalization to support webhook-required operation:
  - `_finalize_credit_card_payment` now validates amount/currency/metadata and supports pending-first behavior.
  - `_ensure_credit_card_pending_record` ensures a safe pending transaction record exists before webhook confirmation.
  - `_complete_credit_card_payment_record` finalizes only after validated completion conditions.
- Added Stripe webhook processing endpoint:
  - `stripe_webhook` verifies signatures, filters supported event types, enforces amount/currency checks, and applies atomic/idempotent updates.
  - `_stripe_event_already_processed` prevents duplicate processing.
  - `_transaction_amount_cents` centralizes amount conversion consistency.
- Hardened manual verification flow in `confirm_payment_received`:
  - Includes `other` method mapping to `chat_confirmation` evidence.
  - Rejects missing or weak references/notes for GCash, bank transfer, and custom arrangement flows.
  - Seller evidence submission routes to moderation review instead of direct completion.
- Hardened checkout-side validation for GCash and bank details before session persistence.
- Hardened `payment_other_arrangement` with stronger arrangement detail requirements.
- Updated pending card messaging for webhook-required mode.

### marketplace/urls.py

- Added Stripe webhook route:
  - `payments/webhooks/stripe/`

## Template and UX Changes

### templates/marketplace/payment_checkout.html

- Added method-specific risk badges and warning copy.
- Added webhook-aware card-payment notice text.
- Strengthened manual-method caution messaging.

### templates/marketplace/transaction_detail.html

- Updated seller action wording to evidence submission for moderator review.
- Added completion-stage vigilance/evidence-retention reminder for non-card flows.

### templates/marketplace/payment_cash_arrangement.html

- Added stronger high-risk warning content.
- Clarified that evidence still proceeds through moderator approval flow.

### templates/marketplace/payment_failure.html

- Fixed broken support reverse target by replacing it with a stable mailto support link.

## Regression Tests Added/Updated

### marketplace/tests_panel_fixes.py

- Added/updated tests covering:
  - Invalid GCash and bank checkout input rejection.
  - Required chat-confirmation evidence for `other` method.
  - Webhook-required card flow pending state and webhook completion behavior.
  - Webhook idempotency behavior.
  - Warning-copy rendering on checkout and method pages.
  - Completion-page vigilance reminder rendering.
  - High-value manual payment transition to moderator review.
  - Moderator approval path before transaction completion and audit-log transition coverage.

## Security and Policy Outcomes

- Seller-side manual verification no longer directly marks manual payments as paid.
- Manual methods now consistently produce moderation-review checkpoints.
- Credit-card completion can be constrained to signed webhook confirmation when enabled.
- Cross-method evidence requirements are stricter and method-aware.
- Customer-facing pages now communicate scam-risk and verification expectations more explicitly.

## Smoke Testing (Post-Changes)

This section records focused smoke-test execution after implementation and summary update.

- Status: Pending run in this log section.
- Target set: 8 focused hardening tests plus migration/system checks.
