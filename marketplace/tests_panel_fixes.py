import io
import json
from decimal import Decimal
import tempfile
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
import stripe

from marketplace.admin import SchoolIDVerificationRequestAdmin
from marketplace.email_2fa import (
    SESSION_2FA_VERIFIED_USER,
    SESSION_2FA_SENSITIVE_VERIFIED_AT,
    SESSION_2FA_SENSITIVE_VERIFIED_USER,
)
from marketplace.security import AuditLog
from marketplace.models import (
    Listing,
    ModerationLog,
    Payment,
    Receipt,
    Review,
    School,
    SchoolIDVerificationRequest,
    StateTransitionAuditLog,
    Transaction,
)

class PanelFixRegressionTests(TestCase):
    def setUp(self):
        self._temp_media_root = tempfile.TemporaryDirectory()
        self._media_override = override_settings(MEDIA_ROOT=self._temp_media_root.name)
        self._media_override.enable()
        self.addCleanup(self._media_override.disable)
        self.addCleanup(self._temp_media_root.cleanup)

        self.buyer = User.objects.create_user(
            username='buyer_panel',
            email='buyer_panel@example.com',
            password='pass12345',
        )
        self.seller = User.objects.create_user(
            username='seller_panel',
            email='seller_panel@example.com',
            password='pass12345',
        )
        self.admin_user = User.objects.create_superuser(
            username='admin_panel',
            email='admin_panel@example.com',
            password='pass12345',
        )
        self.staff_user = User.objects.create_user(
            username='staff_panel',
            email='staff_panel@example.com',
            password='pass12345',
            is_staff=True,
        )
        self.request_factory = RequestFactory()

    def _login_verified(self, user):
        # Force-login triggers user_logged_in; patch audit write to avoid unrelated IP constraints.
        with patch('marketplace.signals.record_login_attempt'):
            self.client.force_login(user)
        session = self.client.session
        session[SESSION_2FA_VERIFIED_USER] = user.pk
        session[SESSION_2FA_SENSITIVE_VERIFIED_USER] = user.pk
        session[SESSION_2FA_SENSITIVE_VERIFIED_AT] = int(timezone.now().timestamp())
        session.save()

    def _create_listing(self, **kwargs):
        defaults = {
            'seller': self.seller,
            'title': 'Panel Fix Listing',
            'description': 'A listing used for regression tests.',
            'price': Decimal('100.00'),
            'listing_type': 'wts',
            'quantity_total': 5,
            'quantity_available': 5,
            'preferred_payment_methods': ['in_person'],
        }
        defaults.update(kwargs)
        return Listing.objects.create(**defaults)

    def _create_transaction(self, listing, **kwargs):
        defaults = {
            'buyer': self.buyer,
            'seller': self.seller,
            'listing': listing,
            'quantity': 1,
            'unit_price': listing.price,
            'price': listing.price,
            'status': 'pending',
            'exchange_method': 'in_person',
        }
        defaults.update(kwargs)
        return Transaction.objects.create(**defaults)

    def _valid_png_upload(self, name):
        buffer = io.BytesIO()
        Image.new('RGB', (1, 1), color='white').save(buffer, format='PNG')
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

    def _upload_meetup_photo(self, transaction, user, filename):
        self._login_verified(user)
        return self.client.post(
            reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
            {
                'action': 'upload_meetup_proof',
                'meetup_photo': self._valid_png_upload(filename),
            },
        )

    def _submit_delivery_tracking(self, transaction, user, provider='lalamove'):
        self._login_verified(user)
        return self.client.post(
            reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
            {
                'action': 'submit_delivery_tracking',
                'tracking_provider': provider,
                'tracking_link': f'https://www.{provider}.com/tracking/route-{transaction.pk}-abc123',
            },
        )

    def _ack_delivery_tracking(self, transaction, user):
        self._login_verified(user)
        return self.client.post(
            reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
            {
                'action': 'ack_delivery_tracking',
            },
        )

    def test_quantity_reserve_on_confirm_and_restore_on_cancel(self):
        listing = self._create_listing(price=Decimal('150.00'), quantity_total=5, quantity_available=5)

        self._login_verified(self.buyer)
        response = self.client.post(
            reverse('marketplace:initiate_purchase', kwargs={'pk': listing.pk}),
            {
                'quantity': '3',
                'exchange_method': 'in_person',
                'notes': 'Can meet after class.',
            },
        )
        self.assertEqual(response.status_code, 302)

        txn = Transaction.objects.get(buyer=self.buyer, seller=self.seller, listing=listing)
        self.assertEqual(txn.status, 'pending')
        self.assertEqual(txn.quantity, 3)
        self.assertEqual(txn.unit_price, Decimal('150.00'))
        self.assertEqual(txn.price, Decimal('450.00'))

        self._login_verified(self.seller)
        response = self.client.post(
            reverse('marketplace:confirm_transaction', kwargs={'transaction_id': txn.pk}),
            {'seller_notes': 'Confirmed.'},
        )
        self.assertEqual(response.status_code, 302)

        txn.refresh_from_db()
        listing.refresh_from_db()
        self.assertEqual(txn.status, 'confirmed')
        self.assertEqual(listing.quantity_available, 2)
        self.assertFalse(listing.is_sold)

        response = self.client.post(
            reverse('marketplace:cancel_transaction', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 302)

        txn.refresh_from_db()
        listing.refresh_from_db()
        self.assertEqual(txn.status, 'cancelled')
        self.assertEqual(listing.quantity_available, 5)
        self.assertFalse(listing.is_sold)

    @override_settings(
        MANUAL_PAYMENT_ALWAYS_REQUIRE_MOD_REVIEW=False,
        MANUAL_PAYMENT_MOD_REVIEW_THRESHOLD='5000.00',
    )
    def test_checkout_requires_meeting_and_rejects_forged_method(self):
        listing = self._create_listing(preferred_payment_methods=['in_person'])
        txn = self._create_transaction(
            listing,
            status='confirmed',
            buyer_confirmed_meeting=False,
            seller_confirmed_meeting=False,
        )

        self._login_verified(self.buyer)

        response = self.client.get(
            reverse('marketplace:payment_checkout', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse('marketplace:transaction_detail', kwargs={'transaction_id': txn.pk}),
            response['Location'],
        )

        txn.buyer_confirmed_meeting = True
        txn.seller_confirmed_meeting = True
        txn.save(update_fields=['buyer_confirmed_meeting', 'seller_confirmed_meeting'])

        response = self.client.post(
            reverse('marketplace:payment_checkout', kwargs={'transaction_id': txn.pk}),
            {
                'exchange_method': 'gcash',
                'confirm_item': ['1', '2', '3', '4', '5'],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse('marketplace:payment_checkout', kwargs={'transaction_id': txn.pk}),
            response['Location'],
        )
        self.assertFalse(Payment.objects.filter(transaction=txn).exists())

        response = self.client.post(
            reverse('marketplace:payment_checkout', kwargs={'transaction_id': txn.pk}),
            {
                'exchange_method': 'in_person',
                'confirm_item': ['a', 'b', 'c', 'd', 'e'],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse('marketplace:payment_cash_arrangement', kwargs={'transaction_id': txn.pk}),
            response['Location'],
        )

        response = self.client.post(
            reverse('marketplace:payment_cash_arrangement', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get(transaction=txn)
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.payment_method, 'in_person')
        self.assertEqual(payment.manual_verification_status, 'submitted')
        self.assertFalse(Receipt.objects.filter(transaction=txn).exists())

        self._login_verified(self.seller)
        response = self.client.post(
            reverse('marketplace:confirm_payment_received', kwargs={'transaction_id': txn.pk}),
            {'verification_action': 'acknowledge'},
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.manual_verification_status, 'seller_acknowledged')

        response = self.client.post(
            reverse('marketplace:confirm_payment_received', kwargs={'transaction_id': txn.pk}),
            {
                'verification_action': 'verify',
                'evidence_type': 'cash_receipt',
                'evidence_reference': 'CASH-RCP-123456',
                'evidence_notes': 'Verified in person with receipt and meetup witness.',
            },
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.manual_verification_status, 'seller_acknowledged')
        self.assertFalse(Receipt.objects.filter(transaction=txn).exists())

        response = self._upload_meetup_photo(txn, self.buyer, 'buyer-proof-checkout.png')
        self.assertEqual(response.status_code, 302)
        response = self._upload_meetup_photo(txn, self.seller, 'seller-proof-checkout.png')
        self.assertEqual(response.status_code, 302)

        self._login_verified(self.seller)
        response = self.client.post(
            reverse('marketplace:confirm_payment_received', kwargs={'transaction_id': txn.pk}),
            {
                'verification_action': 'verify',
                'evidence_type': 'cash_receipt',
                'evidence_reference': 'CASH-RCP-123456',
                'evidence_notes': 'Verified in person with receipt and meetup witness.',
            },
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.manual_verification_status, 'awaiting_moderator_review')
        self.assertTrue(payment.manual_evidence_hash)
        self.assertFalse(Receipt.objects.filter(transaction=txn, status='confirmed').exists())

    def test_direct_manual_payment_endpoints_require_meeting_confirmation(self):
        listing = self._create_listing(
            preferred_payment_methods=['gcash', 'bank_transfer', 'in_person', 'other']
        )
        txn = self._create_transaction(
            listing,
            status='confirmed',
            buyer_confirmed_meeting=False,
            seller_confirmed_meeting=False,
        )

        self._login_verified(self.buyer)

        endpoint_payloads = [
            ('marketplace:payment_gcash', {}),
            ('marketplace:payment_bank_transfer', {}),
            ('marketplace:payment_cash_arrangement', {}),
            (
                'marketplace:payment_third_party_delivery',
                {
                    'tracking_provider': 'grab',
                    'tracking_link': 'https://www.grab.com/ph/tracking/route-abc123',
                    'delivery_notes': 'Continuous route updates every 10 minutes until handoff.',
                },
            ),
            ('marketplace:payment_other_arrangement', {'arrangement_details': 'Manual meetup agreement'}),
        ]

        for url_name, payload in endpoint_payloads:
            response = self.client.post(
                reverse(url_name, kwargs={'transaction_id': txn.pk}),
                payload,
            )
            self.assertEqual(response.status_code, 302)
            self.assertIn(
                reverse('marketplace:transaction_detail', kwargs={'transaction_id': txn.pk}),
                response['Location'],
            )

        self.assertFalse(Payment.objects.filter(transaction=txn).exists())

    def test_third_party_delivery_requires_tracking_ack_before_verify(self):
        listing = self._create_listing(preferred_payment_methods=['third_party_delivery'])
        txn = self._create_transaction(
            listing,
            status='confirmed',
            exchange_method='third_party_delivery',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )

        self._login_verified(self.buyer)
        response = self.client.post(
            reverse('marketplace:payment_checkout', kwargs={'transaction_id': txn.pk}),
            {
                'exchange_method': 'third_party_delivery',
                'confirm_item': ['1', '2', '3', '4', '5'],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse('marketplace:payment_third_party_delivery', kwargs={'transaction_id': txn.pk}),
            response['Location'],
        )

        response = self.client.post(
            reverse('marketplace:payment_third_party_delivery', kwargs={'transaction_id': txn.pk}),
            {
                'tracking_provider': 'lalamove',
                'tracking_link': 'https://www.lalamove.com/tracking/route-demo-12345',
                'delivery_notes': 'Rider will send route updates every 10 minutes until final handoff.',
            },
        )
        self.assertEqual(response.status_code, 302)

        payment = Payment.objects.get(transaction=txn)
        self.assertEqual(payment.payment_method, 'third_party_delivery')
        self.assertTrue(payment.third_party_tracking_link)
        self.assertEqual(payment.manual_verification_status, 'submitted')

        self._login_verified(self.seller)
        response = self.client.post(
            reverse('marketplace:confirm_payment_received', kwargs={'transaction_id': txn.pk}),
            {
                'verification_action': 'verify',
                'evidence_type': 'delivery_tracking',
                'evidence_reference': 'LLM-TRACK-001',
                'evidence_notes': 'Courier updates monitored and linked to transaction records.',
            },
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.manual_verification_status, 'submitted')

        response = self._ack_delivery_tracking(txn, self.buyer)
        self.assertEqual(response.status_code, 302)
        response = self._ack_delivery_tracking(txn, self.seller)
        self.assertEqual(response.status_code, 302)

        self._login_verified(self.seller)
        response = self.client.post(
            reverse('marketplace:confirm_payment_received', kwargs={'transaction_id': txn.pk}),
            {
                'verification_action': 'verify',
                'evidence_type': 'delivery_tracking',
                'evidence_reference': 'LLM-TRACK-001',
                'evidence_notes': 'Courier updates monitored and linked to transaction records.',
            },
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.manual_verification_status, 'awaiting_moderator_review')

    def test_third_party_delivery_rejects_invalid_tracking_link(self):
        listing = self._create_listing(preferred_payment_methods=['third_party_delivery'])
        txn = self._create_transaction(
            listing,
            status='confirmed',
            exchange_method='third_party_delivery',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )

        self._login_verified(self.buyer)
        response = self.client.post(
            reverse('marketplace:payment_third_party_delivery', kwargs={'transaction_id': txn.pk}),
            {
                'tracking_provider': 'lalamove',
                'tracking_link': 'not-a-valid-link',
                'delivery_notes': 'Courier updates monitored and linked to transaction records.',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Payment.objects.filter(transaction=txn).exists())

    def test_checkout_rejects_invalid_gcash_and_bank_inputs(self):
        listing = self._create_listing(preferred_payment_methods=['gcash', 'bank_transfer'])
        txn = self._create_transaction(
            listing,
            status='confirmed',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )

        self._login_verified(self.buyer)

        response = self.client.post(
            reverse('marketplace:payment_checkout', kwargs={'transaction_id': txn.pk}),
            {
                'exchange_method': 'gcash',
                'gcash_number': '12345',
                'gcash_name': 'X',
                'confirm_item': ['1', '2', '3', '4', '5'],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('marketplace:payment_checkout', kwargs={'transaction_id': txn.pk}), response['Location'])

        response = self.client.post(
            reverse('marketplace:payment_checkout', kwargs={'transaction_id': txn.pk}),
            {
                'exchange_method': 'bank_transfer',
                'bank_name': 'B',
                'bank_account_name': 'Y',
                'bank_account_last4': '12AB',
                'confirm_item': ['1', '2', '3', '4', '5'],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('marketplace:payment_checkout', kwargs={'transaction_id': txn.pk}), response['Location'])

        self.assertFalse(Payment.objects.filter(transaction=txn).exists())

    def test_custom_arrangement_requires_minimum_detail_quality(self):
        listing = self._create_listing(preferred_payment_methods=['other'])
        txn = self._create_transaction(
            listing,
            status='confirmed',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )

        self._login_verified(self.buyer)

        response = self.client.post(
            reverse('marketplace:payment_other_arrangement', kwargs={'transaction_id': txn.pk}),
            {'arrangement_details': 'Meet soon'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse('marketplace:payment_other_arrangement', kwargs={'transaction_id': txn.pk}),
            response['Location'],
        )
        self.assertFalse(Payment.objects.filter(transaction=txn).exists())

        response = self.client.post(
            reverse('marketplace:payment_other_arrangement', kwargs={'transaction_id': txn.pk}),
            {
                'arrangement_details': (
                    'Buyer and seller agreed on staged handoff, chat confirmation IDs, '
                    'and documented receipt snapshots after item inspection.'
                ),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Payment.objects.filter(transaction=txn, payment_method='other').exists())

    def test_other_method_requires_chat_confirmation_evidence(self):
        listing = self._create_listing(preferred_payment_methods=['other'])
        txn = self._create_transaction(
            listing,
            status='confirmed',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )

        payment = Payment.objects.create(
            transaction=txn,
            stripe_charge_id=f'test_other_pending_{txn.pk}',
            amount=txn.price,
            status='pending',
            payment_method='other',
            manual_verification_status='submitted',
        )

        self._login_verified(self.seller)

        response = self.client.post(
            reverse('marketplace:confirm_payment_received', kwargs={'transaction_id': txn.pk}),
            {
                'verification_action': 'verify',
                'evidence_type': 'other',
                'evidence_reference': 'OTHER-REF-00123',
                'evidence_notes': 'Seller claims manual proof exists but no chat confirmation reference provided.',
            },
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.manual_verification_status, 'submitted')

        response = self.client.post(
            reverse('marketplace:confirm_payment_received', kwargs={'transaction_id': txn.pk}),
            {
                'verification_action': 'verify',
                'evidence_type': 'chat_confirmation',
                'evidence_reference': 'CHATCONF-778899',
                'evidence_notes': (
                    'Confirmed buyer and seller agreement using chat transcript IDs '
                    'with timestamped screenshots and shared references.'
                ),
            },
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.manual_verification_status, 'awaiting_moderator_review')

    @override_settings(STRIPE_WEBHOOK_REQUIRED=True, STRIPE_WEBHOOK_SECRET='whsec_test_secret')
    def test_credit_card_webhook_required_keeps_pending_until_webhook(self):
        listing = self._create_listing(preferred_payment_methods=['credit_card'])
        txn = self._create_transaction(
            listing,
            status='confirmed',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )

        self._login_verified(self.buyer)

        with patch(
            'marketplace.views.stripe.PaymentIntent.retrieve',
            return_value=SimpleNamespace(
                id='pi_test_pending_flow',
                status='succeeded',
                metadata={'transaction_id': str(txn.pk)},
                amount=int(Decimal(txn.price) * 100),
                currency='php',
            ),
        ):
            response = self.client.post(
                reverse('marketplace:payment_checkout', kwargs={'transaction_id': txn.pk}),
                {
                    'exchange_method': 'credit_card',
                    'payment_intent_id': 'pi_test_pending_flow',
                    'confirm_item': ['1', '2', '3', '4', '5'],
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse('marketplace:transaction_detail', kwargs={'transaction_id': txn.pk}),
            response['Location'],
        )

        payment = Payment.objects.get(transaction=txn)
        receipt = Receipt.objects.get(transaction=txn)
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.payment_method, 'credit_card')
        self.assertEqual(receipt.status, 'pending')

        webhook_event = {
            'id': 'evt_test_pending_flow',
            'type': 'payment_intent.succeeded',
            'data': {
                'object': {
                    'id': 'pi_test_pending_flow',
                    'amount': int(Decimal(txn.price) * 100),
                    'currency': 'php',
                    'metadata': {'transaction_id': str(txn.pk)},
                }
            },
        }

        with patch('marketplace.views.stripe.Webhook.construct_event', return_value=webhook_event):
            response = self.client.post(
                reverse('marketplace:stripe_webhook'),
                data=json.dumps({'test': True}),
                content_type='application/json',
                HTTP_STRIPE_SIGNATURE='t=1,v1=testsig',
            )

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        receipt.refresh_from_db()
        self.assertEqual(payment.status, 'completed')
        self.assertEqual(receipt.status, 'confirmed')

        with patch('marketplace.views.stripe.Webhook.construct_event', return_value=webhook_event):
            response = self.client.post(
                reverse('marketplace:stripe_webhook'),
                data=json.dumps({'test': True}),
                content_type='application/json',
                HTTP_STRIPE_SIGNATURE='t=1,v1=testsig',
            )

        self.assertEqual(response.status_code, 200)
        matching_logs = [
            log
            for log in StateTransitionAuditLog.objects.filter(
                reason='stripe_webhook_payment_intent_succeeded'
            )
            if (log.details or {}).get('stripe_event_id') == 'evt_test_pending_flow'
        ]
        self.assertEqual(len(matching_logs), 1)

    def test_warning_notices_render_on_checkout_and_method_pages(self):
        listing = self._create_listing(
            preferred_payment_methods=['in_person', 'gcash', 'bank_transfer', 'third_party_delivery', 'other']
        )
        txn = self._create_transaction(
            listing,
            status='confirmed',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )

        self._login_verified(self.buyer)

        response = self.client.get(
            reverse('marketplace:payment_checkout', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'GCash: Manual proof + moderator approval')
        self.assertContains(response, 'Courier: Tracking gate + moderator approval')
        self.assertContains(response, 'Third-party delivery risk:')

        response = self.client.get(
            reverse('marketplace:payment_gcash', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Scam-Prevention Reminder')

        response = self.client.get(
            reverse('marketplace:payment_bank_transfer', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bank transfers may not be easily reversible')

        response = self.client.get(
            reverse('marketplace:payment_cash_arrangement', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'High-Risk Cash Reminder')

        response = self.client.get(
            reverse('marketplace:payment_other_arrangement', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'higher scam risk')

    def test_completion_pages_include_vigilance_reminders(self):
        listing = self._create_listing(preferred_payment_methods=['third_party_delivery'])
        txn = self._create_transaction(
            listing,
            status='confirmed',
            exchange_method='third_party_delivery',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )

        Payment.objects.create(
            transaction=txn,
            stripe_charge_id=f'test_completion_warn_{txn.pk}',
            amount=txn.price,
            status='completed',
            payment_method='third_party_delivery',
        )

        self._login_verified(self.buyer)

        response = self.client.get(
            reverse('marketplace:payment_success', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'keep your tracking link open and record delays or route anomalies')

        response = self.client.get(
            reverse('marketplace:payment_cancel', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'verify all recipient/tracking details in chat before proceeding')

    def test_manual_payment_verification_rejects_missing_evidence(self):
        listing = self._create_listing(preferred_payment_methods=['in_person'])
        txn = self._create_transaction(
            listing,
            status='confirmed',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )

        payment = Payment.objects.create(
            transaction=txn,
            stripe_charge_id=f'test_manual_pending_{txn.pk}',
            amount=txn.price,
            status='pending',
            payment_method='in_person',
            manual_verification_status='submitted',
        )

        payment.buyer_meetup_photo = self._valid_png_upload('buyer-proof-missing-evidence.png')
        payment.seller_meetup_photo = self._valid_png_upload('seller-proof-missing-evidence.png')
        payment.buyer_meetup_photo_uploaded_at = timezone.now()
        payment.seller_meetup_photo_uploaded_at = timezone.now()
        payment.save(
            update_fields=[
                'buyer_meetup_photo',
                'seller_meetup_photo',
                'buyer_meetup_photo_uploaded_at',
                'seller_meetup_photo_uploaded_at',
            ]
        )

        self._login_verified(self.seller)
        response = self.client.post(
            reverse('marketplace:confirm_payment_received', kwargs={'transaction_id': txn.pk}),
            {
                'verification_action': 'verify',
                'evidence_type': 'cash_receipt',
                'evidence_reference': '123',
                'evidence_notes': 'too short',
            },
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.manual_verification_status, 'submitted')
        self.assertFalse(
            StateTransitionAuditLog.objects.filter(
                payment=payment,
                entity_type='payment',
                transition_kind='payment_status',
                to_state='completed',
            ).exists()
        )

    @override_settings(MANUAL_PAYMENT_MOD_REVIEW_ENABLED=True, MANUAL_PAYMENT_MOD_REVIEW_THRESHOLD='50.00')
    def test_high_value_manual_payment_moves_to_moderator_review(self):
        listing = self._create_listing(preferred_payment_methods=['in_person'])
        txn = self._create_transaction(
            listing,
            status='confirmed',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )

        self._login_verified(self.buyer)
        response = self.client.post(
            reverse('marketplace:payment_cash_arrangement', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 302)

        self._login_verified(self.seller)
        response = self.client.post(
            reverse('marketplace:confirm_payment_received', kwargs={'transaction_id': txn.pk}),
            {'verification_action': 'acknowledge'},
        )
        self.assertEqual(response.status_code, 302)

        response = self._upload_meetup_photo(txn, self.buyer, 'buyer-proof-high-value.png')
        self.assertEqual(response.status_code, 302)
        response = self._upload_meetup_photo(txn, self.seller, 'seller-proof-high-value.png')
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            reverse('marketplace:confirm_payment_received', kwargs={'transaction_id': txn.pk}),
            {
                'verification_action': 'verify',
                'evidence_type': 'cash_receipt',
                'evidence_reference': 'HV-RCP-123456',
                'evidence_notes': 'High value cash meetup receipt with witness details.',
            },
        )
        self.assertEqual(response.status_code, 302)

        payment = Payment.objects.get(transaction=txn)
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.manual_verification_status, 'awaiting_moderator_review')

        self._login_verified(self.buyer)
        response = self.client.post(
            reverse('marketplace:complete_transaction', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 302)
        txn.refresh_from_db()
        self.assertEqual(txn.status, 'confirmed')

    @override_settings(MANUAL_PAYMENT_MOD_REVIEW_ENABLED=True, MANUAL_PAYMENT_MOD_REVIEW_THRESHOLD='50.00')
    def test_moderator_can_approve_high_value_manual_payment(self):
        listing = self._create_listing(preferred_payment_methods=['in_person'])
        txn = self._create_transaction(
            listing,
            status='confirmed',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )
        payment = Payment.objects.create(
            transaction=txn,
            stripe_charge_id=f'test_waiting_review_{txn.pk}',
            amount=txn.price,
            status='pending',
            payment_method='in_person',
            manual_verification_status='awaiting_moderator_review',
            manual_evidence_type='cash_receipt',
            manual_evidence_reference='MOD-RCP-778899',
            manual_evidence_notes='Seller submitted meetup receipt for moderator review.',
            manual_evidence_hash='abc123',
            seller_acknowledged_by=self.seller,
            seller_acknowledged_at=timezone.now(),
            buyer_meetup_photo=self._valid_png_upload('buyer-proof-mod-approve.png'),
            seller_meetup_photo=self._valid_png_upload('seller-proof-mod-approve.png'),
            buyer_meetup_photo_uploaded_at=timezone.now(),
            seller_meetup_photo_uploaded_at=timezone.now(),
        )

        self._login_verified(self.admin_user)
        response = self.client.post(
            reverse('marketplace:mod_transaction_detail', kwargs={'transaction_id': txn.pk}),
            {
                'action': 'approve_manual_payment',
                'manual_review_reason': 'Verified evidence and approved.',
            },
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'completed')
        self.assertEqual(payment.manual_verification_status, 'verified')
        self.assertEqual(payment.verified_by, self.admin_user)

        self.assertTrue(
            ModerationLog.objects.filter(
                actor=self.admin_user,
                action='approve_manual_payment',
                target_model='payment',
                target_id=payment.pk,
            ).exists()
        )
        self.assertTrue(
            StateTransitionAuditLog.objects.filter(
                payment=payment,
                transition_kind='payment_status',
                from_state='pending',
                to_state='completed',
            ).exists()
        )

    @override_settings(MANUAL_PAYMENT_MOD_REVIEW_ENABLED=True, MANUAL_PAYMENT_MOD_REVIEW_THRESHOLD='50.00')
    def test_moderator_can_reject_high_value_manual_payment(self):
        listing = self._create_listing(preferred_payment_methods=['in_person'])
        txn = self._create_transaction(
            listing,
            status='confirmed',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )
        payment = Payment.objects.create(
            transaction=txn,
            stripe_charge_id=f'test_waiting_review_reject_{txn.pk}',
            amount=txn.price,
            status='pending',
            payment_method='in_person',
            manual_verification_status='awaiting_moderator_review',
            manual_evidence_type='cash_receipt',
            manual_evidence_reference='MOD-RCP-000111',
            manual_evidence_notes='Seller submitted meetup receipt for moderator review.',
            manual_evidence_hash='def456',
            seller_acknowledged_by=self.seller,
            seller_acknowledged_at=timezone.now(),
            buyer_meetup_photo=self._valid_png_upload('buyer-proof-mod-reject.png'),
            seller_meetup_photo=self._valid_png_upload('seller-proof-mod-reject.png'),
            buyer_meetup_photo_uploaded_at=timezone.now(),
            seller_meetup_photo_uploaded_at=timezone.now(),
        )

        self._login_verified(self.admin_user)
        response = self.client.post(
            reverse('marketplace:mod_transaction_detail', kwargs={'transaction_id': txn.pk}),
            {
                'action': 'reject_manual_payment',
                'manual_review_reason': 'Evidence reference does not match reported transfer details.',
            },
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'failed')
        self.assertEqual(payment.manual_verification_status, 'rejected')
        self.assertEqual(payment.verified_by, self.admin_user)

        self.assertTrue(
            ModerationLog.objects.filter(
                actor=self.admin_user,
                action='reject_manual_payment',
                target_model='payment',
                target_id=payment.pk,
            ).exists()
        )
        self.assertTrue(
            StateTransitionAuditLog.objects.filter(
                payment=payment,
                transition_kind='payment_status',
                from_state='pending',
                to_state='failed',
            ).exists()
        )

    def test_completion_requires_payment_then_updates_quantity_totals(self):
        listing = self._create_listing(quantity_total=10, quantity_available=8)
        txn = self._create_transaction(
            listing,
            status='confirmed',
            quantity=2,
            unit_price=Decimal('50.00'),
            price=Decimal('100.00'),
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )

        self._login_verified(self.buyer)
        response = self.client.post(
            reverse('marketplace:complete_transaction', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 302)

        txn.refresh_from_db()
        self.assertEqual(txn.status, 'confirmed')
        self.assertFalse(txn.buyer_completed)

        Payment.objects.create(
            transaction=txn,
            stripe_charge_id=f'test_paid_{txn.pk}',
            amount=txn.price,
            status='completed',
            payment_method='in_person',
        )

        response = self.client.post(
            reverse('marketplace:complete_transaction', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 302)

        txn.refresh_from_db()
        self.assertTrue(txn.buyer_completed)
        self.assertFalse(txn.seller_completed)
        self.assertEqual(txn.status, 'confirmed')

        self._login_verified(self.seller)
        response = self.client.post(
            reverse('marketplace:complete_transaction', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 302)

        txn.refresh_from_db()
        listing.refresh_from_db()
        self.buyer.profile.refresh_from_db()
        self.seller.profile.refresh_from_db()

        self.assertEqual(txn.status, 'completed')
        self.assertTrue(txn.buyer_completed)
        self.assertTrue(txn.seller_completed)
        self.assertEqual(self.buyer.profile.total_bought, 2)
        self.assertEqual(self.seller.profile.total_sold, 2)
        self.assertFalse(listing.is_sold)

    @override_settings(
        MANUAL_PAYMENT_ALWAYS_REQUIRE_MOD_REVIEW=False,
        MANUAL_PAYMENT_MOD_REVIEW_THRESHOLD='5000.00',
    )
    def test_state_transition_logs_cover_manual_payment_and_completion(self):
        listing = self._create_listing(preferred_payment_methods=['in_person'])
        txn = self._create_transaction(
            listing,
            status='confirmed',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )

        self._login_verified(self.buyer)
        response = self.client.post(
            reverse('marketplace:payment_cash_arrangement', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 302)

        payment = Payment.objects.get(transaction=txn)

        self._login_verified(self.seller)
        response = self.client.post(
            reverse('marketplace:confirm_payment_received', kwargs={'transaction_id': txn.pk}),
            {'verification_action': 'acknowledge'},
        )
        self.assertEqual(response.status_code, 302)

        response = self._upload_meetup_photo(txn, self.buyer, 'buyer-proof-transition.png')
        self.assertEqual(response.status_code, 302)
        response = self._upload_meetup_photo(txn, self.seller, 'seller-proof-transition.png')
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            reverse('marketplace:confirm_payment_received', kwargs={'transaction_id': txn.pk}),
            {
                'verification_action': 'verify',
                'evidence_type': 'cash_receipt',
                'evidence_reference': 'RCP-LOG-778899',
                'evidence_notes': 'Verified cash handoff with signed receipt evidence.',
            },
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.manual_verification_status, 'awaiting_moderator_review')

        self._login_verified(self.admin_user)
        response = self.client.post(
            reverse('marketplace:mod_transaction_detail', kwargs={'transaction_id': txn.pk}),
            {
                'action': 'approve_manual_payment',
                'manual_review_reason': 'Approved for transition-log completion flow.',
            },
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'completed')
        self.assertEqual(payment.manual_verification_status, 'verified')

        self._login_verified(self.buyer)
        response = self.client.post(
            reverse('marketplace:complete_transaction', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 302)

        self._login_verified(self.seller)
        response = self.client.post(
            reverse('marketplace:complete_transaction', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            StateTransitionAuditLog.objects.filter(
                transaction=txn,
                payment=payment,
                entity_type='payment',
                transition_kind='payment_status',
                to_state='pending',
            ).exists()
        )
        self.assertTrue(
            StateTransitionAuditLog.objects.filter(
                transaction=txn,
                payment=payment,
                entity_type='payment',
                transition_kind='manual_verification',
                to_state='seller_acknowledged',
            ).exists()
        )
        self.assertTrue(
            StateTransitionAuditLog.objects.filter(
                transaction=txn,
                payment=payment,
                entity_type='payment',
                transition_kind='manual_verification',
                to_state='awaiting_moderator_review',
            ).exists()
        )
        self.assertTrue(
            StateTransitionAuditLog.objects.filter(
                transaction=txn,
                payment=payment,
                entity_type='payment',
                transition_kind='manual_verification',
                to_state='verified',
            ).exists()
        )
        self.assertTrue(
            StateTransitionAuditLog.objects.filter(
                transaction=txn,
                payment=payment,
                entity_type='payment',
                transition_kind='payment_status',
                to_state='completed',
            ).exists()
        )
        self.assertTrue(
            StateTransitionAuditLog.objects.filter(
                transaction=txn,
                entity_type='transaction',
                transition_kind='transaction_status',
                to_state='completed',
            ).exists()
        )

    def test_mutual_vouch_is_transaction_scoped(self):
        listing = self._create_listing()
        txn = self._create_transaction(
            listing,
            status='completed',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )
        Payment.objects.create(
            transaction=txn,
            stripe_charge_id=f'test_paid_vouch_{txn.pk}',
            amount=txn.price,
            status='completed',
            payment_method='in_person',
        )

        self._login_verified(self.buyer)
        response = self.client.post(
            reverse('marketplace:leave_review', kwargs={'username': self.seller.username}),
            {
                'transaction_id': str(txn.pk),
                'is_vouch': 'true',
                'comment': 'Great seller',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Review.objects.filter(reviewer=self.buyer, seller=self.seller, transaction=txn).exists()
        )

        self._login_verified(self.seller)
        response = self.client.post(
            reverse('marketplace:leave_review', kwargs={'username': self.buyer.username}),
            {
                'transaction_id': str(txn.pk),
                'is_vouch': 'true',
                'comment': 'Great buyer',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Review.objects.filter(reviewer=self.seller, seller=self.buyer, transaction=txn).exists()
        )
        self.assertEqual(Review.objects.filter(transaction=txn).count(), 2)

    def test_leave_review_rejects_unpaid_transaction(self):
        listing = self._create_listing()
        txn = self._create_transaction(
            listing,
            status='completed',
            buyer_confirmed_meeting=True,
            seller_confirmed_meeting=True,
        )
        Payment.objects.create(
            transaction=txn,
            stripe_charge_id=f'test_pending_vouch_{txn.pk}',
            amount=txn.price,
            status='pending',
            payment_method='in_person',
        )

        self._login_verified(self.buyer)
        response = self.client.post(
            reverse('marketplace:leave_review', kwargs={'username': self.seller.username}),
            {
                'transaction_id': str(txn.pk),
                'is_vouch': 'true',
                'comment': 'Should not pass',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse('marketplace:public_profile', kwargs={'username': self.seller.username}),
            response['Location'],
        )
        self.assertFalse(Review.objects.filter(reviewer=self.buyer, seller=self.seller, transaction=txn).exists())

    def test_yellow_tier_requires_id_verification(self):
        school = School.objects.create(name='Test University', short_name='TU')
        profile = self.buyer.profile
        profile.full_name = 'Buyer Panel'
        profile.school = school
        profile.year_level = 'year_1'
        profile.phone = '09171234567'
        profile.address = 'Sampaloc, Manila'
        profile.id_verified = False
        profile.save(
            update_fields=['full_name', 'school', 'year_level', 'phone', 'address', 'id_verified']
        )

        profile.update_verification_tier()
        profile.refresh_from_db()
        self.assertEqual(profile.verification_tier, 'grey')

        profile.id_verified = True
        profile.save(update_fields=['id_verified'])
        profile.update_verification_tier()
        profile.refresh_from_db()
        self.assertEqual(profile.verification_tier, 'yellow')

    def test_submit_school_id_creates_pending_request_and_blocks_duplicate(self):
        self._login_verified(self.buyer)

        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                response = self.client.post(
                    reverse('marketplace:submit_school_id_verification'),
                    {'id_image': self._valid_png_upload('school-id.png')},
                )
                self.assertEqual(response.status_code, 302)

                self.assertEqual(
                    SchoolIDVerificationRequest.objects.filter(profile=self.buyer.profile, status='pending').count(),
                    1,
                )

                self.buyer.profile.refresh_from_db()
                self.assertTrue(self.buyer.profile.id_submitted)
                self.assertFalse(self.buyer.profile.id_verified)

                response = self.client.post(
                    reverse('marketplace:submit_school_id_verification'),
                    {'id_image': self._valid_png_upload('school-id-2.png')},
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(
                    SchoolIDVerificationRequest.objects.filter(profile=self.buyer.profile, status='pending').count(),
                    1,
                )

    def test_purchase_stores_proposed_meetup_schedule(self):
        listing = self._create_listing(campus='ust_q_pavilion', quantity_total=3, quantity_available=3)
        proposed_slot = timezone.localtime(timezone.now() + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)

        self._login_verified(self.buyer)
        response = self.client.post(
            reverse('marketplace:initiate_purchase', kwargs={'pk': listing.pk}),
            {
                'quantity': '2',
                'exchange_method': 'in_person',
                'proposed_meetup_location': 'ust_q_pavilion',
                'proposed_meetup_datetime': proposed_slot.strftime('%Y-%m-%dT%H:%M'),
                'notes': 'Can meet near the security desk.',
            },
        )
        self.assertEqual(response.status_code, 302)

        txn = Transaction.objects.get(buyer=self.buyer, seller=self.seller, listing=listing)
        self.assertEqual(txn.proposed_meetup_location, 'ust_q_pavilion')
        self.assertIsNotNone(txn.proposed_meetup_datetime)
        self.assertEqual(
            timezone.localtime(txn.proposed_meetup_datetime).strftime('%Y-%m-%dT%H:%M'),
            proposed_slot.strftime('%Y-%m-%dT%H:%M'),
        )

    def test_listing_filter_supports_meetup_location_param(self):
        ust_listing = self._create_listing(
            title='Meetup Listing UST',
            campus='ust_q_pavilion',
            quantity_total=1,
            quantity_available=1,
        )
        self._create_listing(
            title='Meetup Listing FEU',
            campus='feu_gate4_morayta',
            quantity_total=1,
            quantity_available=1,
        )

        response = self.client.get(
            reverse('marketplace:listing_list'),
            {'meetup_location': 'ust_q_pavilion'},
        )
        self.assertEqual(response.status_code, 200)
        returned_ids = set(response.context['listings'].values_list('id', flat=True))
        self.assertEqual(returned_ids, {ust_listing.id})

    def test_purchase_form_meetup_choices_prioritize_lister_school_then_public_hubs(self):
        ust_school, _ = School.objects.get_or_create(
            short_name='UST',
            defaults={'name': 'University of Santo Tomas'},
        )
        seller_profile = self.seller.profile
        seller_profile.school = ust_school
        seller_profile.save(update_fields=['school'])

        listing = self._create_listing(school=ust_school)

        self._login_verified(self.buyer)
        response = self.client.get(reverse('marketplace:initiate_purchase', kwargs={'pk': listing.pk}))
        self.assertEqual(response.status_code, 200)

        form = response.context['form']
        meetup_choices = list(form.fields['proposed_meetup_location'].choices)

        self.assertEqual(meetup_choices[1][0], 'Near UST')
        self.assertEqual(meetup_choices[2][0], 'Public hubs around U-Belt Manila')

        school_values = {value for value, _label in meetup_choices[1][1]}
        public_values = {value for value, _label in meetup_choices[2][1]}

        self.assertIn('ust_q_pavilion', school_values)
        self.assertIn('lrt2_legarda', public_values)

    def test_listing_form_meetup_choices_use_lister_profile_school(self):
        feu_school, _ = School.objects.get_or_create(
            short_name='FEU',
            defaults={'name': 'Far Eastern University'},
        )
        seller_profile = self.seller.profile
        seller_profile.school = feu_school
        seller_profile.save(update_fields=['school'])

        self._login_verified(self.seller)
        response = self.client.get(reverse('marketplace:listing_create'))
        self.assertEqual(response.status_code, 200)

        form = response.context['form']
        meetup_choices = list(form.fields['campus'].choices)

        self.assertEqual(meetup_choices[1][0], 'Near FEU')
        self.assertEqual(meetup_choices[2][0], 'Public hubs around U-Belt Manila')

        school_values = {value for value, _label in meetup_choices[1][1]}
        public_values = {value for value, _label in meetup_choices[2][1]}

        self.assertIn('feu_gate4_morayta', school_values)
        self.assertIn('lrt2_recto', public_values)

    def test_admin_action_approve_school_id_request_updates_profile(self):
        school = School.objects.create(name='Approval University', short_name='AU')
        profile = self.buyer.profile
        profile.full_name = 'Buyer Panel'
        profile.school = school
        profile.year_level = 'year_1'
        profile.phone = '09170000000'
        profile.address = 'Sampaloc, Manila'
        profile.id_submitted = True
        profile.id_verified = False
        profile.save(
            update_fields=['full_name', 'school', 'year_level', 'phone', 'address', 'id_submitted', 'id_verified']
        )

        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                verification_request = SchoolIDVerificationRequest.objects.create(
                    profile=profile,
                    id_image=self._valid_png_upload('approve-school-id.png'),
                )

        model_admin = SchoolIDVerificationRequestAdmin(SchoolIDVerificationRequest, AdminSite())
        request = self.request_factory.post('/admin/marketplace/schoolidverificationrequest/')
        request.user = self.admin_user

        with patch.object(model_admin, 'message_user'):
            model_admin.approve_requests(request, SchoolIDVerificationRequest.objects.filter(pk=verification_request.pk))

        verification_request.refresh_from_db()
        profile.refresh_from_db()

        self.assertEqual(verification_request.status, 'approved')
        self.assertEqual(verification_request.reviewed_by, self.admin_user)
        self.assertIsNotNone(verification_request.reviewed_at)
        self.assertTrue(profile.id_submitted)
        self.assertTrue(profile.id_verified)

    def test_admin_action_reject_school_id_request_resets_profile_flags(self):
        school = School.objects.create(name='Rejection University', short_name='RU')
        profile = self.buyer.profile
        profile.full_name = 'Buyer Panel'
        profile.school = school
        profile.year_level = 'year_1'
        profile.phone = '09179999999'
        profile.address = 'Sampaloc, Manila'
        profile.id_submitted = True
        profile.id_verified = True
        profile.save(
            update_fields=['full_name', 'school', 'year_level', 'phone', 'address', 'id_submitted', 'id_verified']
        )

        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                verification_request = SchoolIDVerificationRequest.objects.create(
                    profile=profile,
                    id_image=self._valid_png_upload('reject-school-id.png'),
                    status='approved',
                )

        model_admin = SchoolIDVerificationRequestAdmin(SchoolIDVerificationRequest, AdminSite())
        request = self.request_factory.post('/admin/marketplace/schoolidverificationrequest/')
        request.user = self.admin_user

        with patch.object(model_admin, 'message_user'):
            model_admin.reject_requests(request, SchoolIDVerificationRequest.objects.filter(pk=verification_request.pk))

        verification_request.refresh_from_db()
        profile.refresh_from_db()

        self.assertEqual(verification_request.status, 'rejected')
        self.assertEqual(verification_request.reviewed_by, self.admin_user)
        self.assertIsNotNone(verification_request.reviewed_at)
        self.assertFalse(profile.id_submitted)
        self.assertFalse(profile.id_verified)

    def test_mod_dashboard_shows_pending_school_id_verification_queue(self):
        self._login_verified(self.admin_user)

        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                verification_request = SchoolIDVerificationRequest.objects.create(
                    profile=self.buyer.profile,
                    id_image=self._valid_png_upload('mod-dashboard-school-id.png'),
                )

                response = self.client.get(reverse('marketplace:mod_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['pending_school_id_count'], 1)
        pending_ids = {req.pk for req in response.context['pending_school_id_requests']}
        self.assertIn(verification_request.pk, pending_ids)
        self.assertTrue(response.context['school_id_admin_url'])

    def test_mod_dashboard_can_approve_school_id_request(self):
        self._login_verified(self.admin_user)

        school = School.objects.create(name='Mod Approve University', short_name='MAU')
        profile = self.buyer.profile
        profile.school = school
        profile.full_name = 'Buyer Panel'
        profile.year_level = 'year_2'
        profile.phone = '09171230000'
        profile.address = 'Sampaloc, Manila'
        profile.id_submitted = True
        profile.id_verified = False
        profile.save(update_fields=['school', 'full_name', 'year_level', 'phone', 'address', 'id_submitted', 'id_verified'])

        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                verification_request = SchoolIDVerificationRequest.objects.create(
                    profile=profile,
                    id_image=self._valid_png_upload('mod-approve-school-id.png'),
                )

                response = self.client.post(
                    reverse('marketplace:mod_dashboard'),
                    {
                        'verification_request_id': str(verification_request.pk),
                        'verification_action': 'approve',
                        'reviewer_notes': 'Name and school ID number are readable.',
                    },
                )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('marketplace:mod_dashboard'), response['Location'])

        verification_request.refresh_from_db()
        profile.refresh_from_db()

        self.assertEqual(verification_request.status, 'approved')
        self.assertEqual(verification_request.reviewed_by, self.admin_user)
        self.assertTrue(profile.id_submitted)
        self.assertTrue(profile.id_verified)
        self.assertTrue(
            ModerationLog.objects.filter(
                actor=self.admin_user,
                action='approve_school_id',
                target_model='school_id_verification_request',
                target_id=verification_request.pk,
            ).exists()
        )

    def test_mod_dashboard_reject_requires_notes_and_logs_decision(self):
        self._login_verified(self.admin_user)

        profile = self.buyer.profile
        profile.id_submitted = True
        profile.id_verified = True
        profile.save(update_fields=['id_submitted', 'id_verified'])

        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root):
                verification_request = SchoolIDVerificationRequest.objects.create(
                    profile=profile,
                    id_image=self._valid_png_upload('mod-reject-school-id.png'),
                )

                response = self.client.post(
                    reverse('marketplace:mod_dashboard'),
                    {
                        'verification_request_id': str(verification_request.pk),
                        'verification_action': 'reject',
                        'reviewer_notes': '',
                    },
                )

                self.assertEqual(response.status_code, 302)
                verification_request.refresh_from_db()
                self.assertEqual(verification_request.status, 'pending')

                response = self.client.post(
                    reverse('marketplace:mod_dashboard'),
                    {
                        'verification_request_id': str(verification_request.pk),
                        'verification_action': 'reject',
                        'reviewer_notes': 'Photo is blurry and school name is not visible.',
                    },
                )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('marketplace:mod_dashboard'), response['Location'])

        verification_request.refresh_from_db()
        profile.refresh_from_db()

        self.assertEqual(verification_request.status, 'rejected')
        self.assertEqual(verification_request.reviewed_by, self.admin_user)
        self.assertIn('blurry', verification_request.reviewer_notes)
        self.assertFalse(profile.id_submitted)
        self.assertFalse(profile.id_verified)
        self.assertTrue(
            ModerationLog.objects.filter(
                actor=self.admin_user,
                action='reject_school_id',
                target_model='school_id_verification_request',
                target_id=verification_request.pk,
            ).exists()
        )

    def test_mod_security_tests_allows_staff_and_superuser(self):
        self._login_verified(self.staff_user)
        response = self.client.get(reverse('marketplace:mod_security_tests'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Security Testing Lab')

        self._login_verified(self.admin_user)
        response = self.client.get(reverse('marketplace:mod_security_tests'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Security Testing Lab')

    def test_mod_security_tests_denies_regular_user(self):
        self._login_verified(self.buyer)

        response = self.client.get(reverse('marketplace:mod_security_tests'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('marketplace:home'), response['Location'])

    def test_mod_security_probe_requires_staff_and_post(self):
        self._login_verified(self.staff_user)

        response = self.client.get(reverse('marketplace:mod_security_probe'))
        self.assertEqual(response.status_code, 405)

        response = self.client.post(reverse('marketplace:mod_security_probe'))
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {'ok': True, 'message': 'Probe accepted with valid CSRF'})

        self._login_verified(self.buyer)
        response = self.client.post(reverse('marketplace:mod_security_probe'))
        self.assertEqual(response.status_code, 403)

    def test_mod_security_tests_active_check_logs_audit_event(self):
        self._login_verified(self.staff_user)

        before = AuditLog.objects.filter(
            user=self.staff_user,
            event_type='security_alert',
            resource=reverse('marketplace:mod_security_tests'),
        ).count()

        response = self.client.post(
            reverse('marketplace:mod_security_tests'),
            {'action': 'active_csrf_check'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_result']['title'], 'CSRF enforcement probe')

        after = AuditLog.objects.filter(
            user=self.staff_user,
            event_type='security_alert',
            resource=reverse('marketplace:mod_security_tests'),
        ).count()
        self.assertGreater(after, before)

    def test_mod_security_tests_run_security_audit_returns_output(self):
        self._login_verified(self.staff_user)

        response = self.client.post(
            reverse('marketplace:mod_security_tests'),
            {'action': 'run_security_audit'},
        )

        self.assertEqual(response.status_code, 200)
        output = response.context['security_audit_output']
        self.assertIn('SECURITY AUDIT INITIATED', output)

    def test_mod_security_tests_get_logs_view_action(self):
        self._login_verified(self.staff_user)
        target_url = reverse('marketplace:mod_security_tests')

        before = AuditLog.objects.filter(
            user=self.staff_user,
            event_type='security_alert',
            resource=target_url,
        ).count()

        response = self.client.get(target_url)

        self.assertEqual(response.status_code, 200)
        after = AuditLog.objects.filter(
            user=self.staff_user,
            event_type='security_alert',
            resource=target_url,
        ).count()
        self.assertGreater(after, before)

        latest = AuditLog.objects.filter(
            user=self.staff_user,
            event_type='security_alert',
            resource=target_url,
        ).order_by('-timestamp').first()
        self.assertIsNotNone(latest)
        self.assertEqual(latest.details.get('action'), 'view_security_testing_lab')

    def test_mod_security_tests_realtime_xss_demo_outputs_framework(self):
        self._login_verified(self.staff_user)

        response = self.client.post(
            reverse('marketplace:mod_security_tests'),
            {'action': 'active_xss_realtime_check'},
        )

        self.assertEqual(response.status_code, 200)
        active_result = response.context['active_result']
        self.assertEqual(active_result['title'], 'Realtime XSS scripting demo')
        self.assertIn('demo_report', active_result)
        self.assertIn('tests_ran', active_result['demo_report'])
        self.assertTrue(active_result['demo_report']['sample_case'])
        self.assertTrue(active_result['demo_report']['problem'])
        self.assertTrue(active_result['demo_report']['solution'])
        self.assertGreater(len(active_result['demo_report']['tests_ran']), 0)

        latest = AuditLog.objects.filter(
            user=self.staff_user,
            event_type='security_alert',
            resource=reverse('marketplace:mod_security_tests'),
        ).order_by('-timestamp').first()
        self.assertIsNotNone(latest)
        self.assertEqual(latest.details.get('action'), 'active_xss_realtime_check')

    def test_mod_security_tests_realtime_sqli_demo_outputs_framework(self):
        self._login_verified(self.staff_user)

        response = self.client.post(
            reverse('marketplace:mod_security_tests'),
            {'action': 'active_sqli_realtime_check'},
        )

        self.assertEqual(response.status_code, 200)
        active_result = response.context['active_result']
        self.assertEqual(active_result['title'], 'Realtime SQL injection demo')
        self.assertIn('demo_report', active_result)
        self.assertIn('tests_ran', active_result['demo_report'])
        self.assertGreater(len(active_result['demo_report']['tests_ran']), 0)

    def test_mod_security_tests_realtime_report_combines_xss_and_sqli(self):
        self._login_verified(self.staff_user)

        response = self.client.post(
            reverse('marketplace:mod_security_tests'),
            {'action': 'active_realtime_demo_report'},
        )

        self.assertEqual(response.status_code, 200)
        active_result = response.context['active_result']
        self.assertEqual(active_result['title'], 'Realtime attack simulation report')
        self.assertIn('child_results', active_result)
        self.assertEqual(len(active_result['child_results']), 2)
        self.assertIn('demo_report', active_result)
        self.assertGreaterEqual(len(active_result['demo_report']['tests_ran']), 2)
