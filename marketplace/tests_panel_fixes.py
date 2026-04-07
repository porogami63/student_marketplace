import io
from decimal import Decimal
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from marketplace.admin import SchoolIDVerificationRequestAdmin
from marketplace.email_2fa import SESSION_2FA_VERIFIED_USER
from marketplace.models import (
    Listing,
    ModerationLog,
    Payment,
    Review,
    School,
    SchoolIDVerificationRequest,
    Transaction,
)

class PanelFixRegressionTests(TestCase):
    def setUp(self):
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
        self.request_factory = RequestFactory()

    def _login_verified(self, user):
        # Force-login triggers user_logged_in; patch audit write to avoid unrelated IP constraints.
        with patch('marketplace.signals.record_login_attempt'):
            self.client.force_login(user)
        session = self.client.session
        session[SESSION_2FA_VERIFIED_USER] = user.pk
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

        self._login_verified(self.seller)
        response = self.client.post(
            reverse('marketplace:confirm_payment_received', kwargs={'transaction_id': txn.pk}),
        )
        self.assertEqual(response.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, 'completed')

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
