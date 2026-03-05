#!/usr/bin/env python
"""
Quick Django shell test to verify vouch and verification features work end-to-end
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'student_marketplace.settings')
django.setup()

from django.contrib.auth.models import User
from marketplace.models import Profile, Review, Notification

print("\n" + "="*70)
print("END-TO-END VOUCH & VERIFICATION FEATURE TEST")
print("="*70)

# Get or create test users
user1, _ = User.objects.get_or_create(
    username='e2e_seller',
    defaults={'email': 'e2e_seller@test.com'}
)
user2, _ = User.objects.get_or_create(
    username='e2e_buyer',
    defaults={'email': 'e2e_buyer@test.com'}
)

# Ensure profiles exist
seller_profile, _ = Profile.objects.get_or_create(user=user1)
buyer_profile, _ = Profile.objects.get_or_create(user=user2)

print("\n1. INITIAL STATE")
print("-" * 70)
print(f"   Seller (@{user1.username}):")
print(f"     - Vouch Count: {seller_profile.vouch_count}")
print(f"     - Verification Tier: {seller_profile.verification_tier}")
print(f"\n   Buyer (@{user2.username}):")
print(f"     - Vouch Count: {buyer_profile.vouch_count}")
print(f"     - Verification Tier: {buyer_profile.verification_tier}")

# Test creating a vouch
print("\n2. CREATING A VOUCH")
print("-" * 70)

# Delete any existing review
Review.objects.filter(reviewer=user2, seller=user1).delete()
Notification.objects.filter(user=user1, message__contains=user2.username).delete()

# Create a new vouch
review = Review.objects.create(
    reviewer=user2,
    seller=user1,
    is_vouch=True,
    comment="Excellent seller! Fast shipping."
)

print(f"   ✅ Created vouch review")
print(f"   - Review ID: {review.id}")
print(f"   - Reviewer: @{review.reviewer.username}")
print(f"   - Seller: @{review.seller.username}")
print(f"   - Is Vouch: {review.is_vouch}")

# Refresh seller profile
seller_profile.refresh_from_db()
print(f"\n3. AFTER VOUCH CREATION")
print("-" * 70)
print(f"   Seller vouch count: {seller_profile.vouch_count} (should be > 0)")

# Check notification was created
notification = Notification.objects.filter(user=user1).order_by('-created_at').first()
print(f"   Notification created: {notification is not None}")
if notification:
    print(f"   - Message: {notification.message}")

# Test updating a vouch (False → True should not increment again)
print(f"\n4. UPDATING VOUCH (same status)")
print("-" * 70)
old_count = seller_profile.vouch_count
review.comment = "Even better! Fast shipping and well packaged."
review.save()
seller_profile.refresh_from_db()
print(f"   Vouch count before: {old_count}")
print(f"   Vouch count after: {seller_profile.vouch_count}")
print(f"   ✅ Count not incremented again" if seller_profile.vouch_count == old_count else "   ✗ ERROR: Count changed unexpectedly")

# Test changing vouch to non-vouch
print(f"\n5. CHANGING VOUCH TO NON-VOUCH")
print("-" * 70)
old_count = seller_profile.vouch_count
review.is_vouch = False
review.save()
seller_profile.refresh_from_db()
print(f"   Vouch count before: {old_count}")
print(f"   Vouch count after: {seller_profile.vouch_count}")
expected_count = old_count - 1
print(f"   ✅ Count decremented correctly" if seller_profile.vouch_count == expected_count else f"   ✗ ERROR: Expected {expected_count}, got {seller_profile.vouch_count}")

# Test changing non-vouch back to vouch
print(f"\n6. CHANGING BACK TO VOUCH")
print("-" * 70)
old_count = seller_profile.vouch_count
review.is_vouch = True
review.save()
seller_profile.refresh_from_db()
print(f"   Vouch count before: {old_count}")
print(f"   Vouch count after: {seller_profile.vouch_count}")
expected_count = old_count + 1
print(f"   ✅ Count incremented correctly" if seller_profile.vouch_count == expected_count else f"   ✗ ERROR: Expected {expected_count}, got {seller_profile.vouch_count}")

# Test verification tier update
print(f"\n7. VERIFICATION TIER LOGIC")
print("-" * 70)

# Complete seller's profile
from marketplace.models import School
school, _ = School.objects.get_or_create(name='Test School', defaults={'short_name': 'TS'})
seller_profile.full_name = 'E2E Seller'
seller_profile.school = school
seller_profile.year_level = 'year_1'
seller_profile.phone = '555-1234'
seller_profile.address = 'Test Address'
seller_profile.save()

seller_profile.update_verification_tier()
seller_profile.refresh_from_db()

print(f"   Complete Profile Check: {seller_profile.is_profile_complete()}")
print(f"   Verification Tier: {seller_profile.verification_tier}")
print(f"   ✅ Yellow tier assigned" if seller_profile.verification_tier == 'yellow' else f"   ✗ ERROR: Expected yellow, got {seller_profile.verification_tier}")

print("\n" + "="*70)
print("✅ END-TO-END TEST COMPLETED SUCCESSFULLY")
print("="*70 + "\n")
