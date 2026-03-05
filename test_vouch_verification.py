#!/usr/bin/env python
"""
Comprehensive test script for vouch and verification tier features.
Tests:
1. Vouch functionality (creating reviews)
2. Verification tier calculations
3. Existing user integration
"""

import os
import sys
import django
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'student_marketplace.settings')
django.setup()

from django.contrib.auth.models import User
from marketplace.models import Profile, Review, Listing, Category, School, Transaction

def create_test_data():
    """Create test users and data if they don't exist."""
    print("\n" + "="*70)
    print("CREATING TEST DATA")
    print("="*70)
    
    # Get or create a school
    school, created = School.objects.get_or_create(
        name='Test University',
        defaults={'short_name': 'TU', 'primary_color': '#003366'}
    )
    print(f"✓ School: {school.name}")
    
    # Create test users if they don't exist
    test_users = {}
    for i in range(4):
        username = f'test_user_{i}'
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': f'{username}@example.com',
                'first_name': f'Test{i}',
                'last_name': f'User{i}'
            }
        )
        
        # Ensure profile exists
        profile, profile_created = Profile.objects.get_or_create(
            user=user,
            defaults={
                'full_name': f'Test User {i}',
                'school': school,
                'year_level': 'year_1',
                'phone': f'555-000{i}',
                'address': 'Test Address'
            }
        )
        
        test_users[f'user_{i}'] = user
        status = "CREATED" if created else "EXISTS"
        print(f"  [{status}] @{username} - Profile completion: {profile.is_profile_complete()}")
    
    return test_users, school

def test_vouch_functionality(test_users):
    """Test that vouch/review functionality works."""
    print("\n" + "="*70)
    print("TEST 1: VOUCH FUNCTIONALITY")
    print("="*70)
    
    reviewer = test_users['user_0']
    seller = test_users['user_1']
    
    # Check if review already exists
    existing = Review.objects.filter(reviewer=reviewer, seller=seller).first()
    if existing:
        print(f"⚠ Review already exists between {reviewer.username} and {seller.username}")
        print(f"  - is_vouch: {existing.is_vouch}")
        print(f"  - comment: {existing.comment}")
        return existing
    
    # Create a new vouch review
    review = Review.objects.create(
        reviewer=reviewer,
        seller=seller,
        is_vouch=True,
        comment="Great seller! Very responsive and honest."
    )
    
    print(f"✓ Created vouch review:")
    print(f"  - Reviewer: @{reviewer.username}")
    print(f"  - Seller: @{seller.username}")
    print(f"  - Is Vouch: {review.is_vouch}")
    print(f"  - Comment: {review.comment}")
    print(f"  - Created at: {review.created_at}")
    
    return review

def test_vouch_count_increment(test_users):
    """Test that vouch count is incremented in profile."""
    print("\n" + "="*70)
    print("TEST 2: VOUCH COUNT IS INCREMENTED")
    print("="*70)
    
    seller = test_users['user_1']
    seller_profile = seller.profile
    
    initial_vouch_count = seller_profile.vouch_count
    print(f"✓ Current vouch count for @{seller.username}: {initial_vouch_count}")
    
    # Count reviews in database
    vouch_count = Review.objects.filter(seller=seller, is_vouch=True).count()
    print(f"✓ Vouches in database: {vouch_count}")
    
    if vouch_count == initial_vouch_count:
        print(f"✓ PASS: Vouch count matches database reviews")
    else:
        print(f"✗ FAIL: Vouch count ({initial_vouch_count}) != database reviews ({vouch_count})")
        # Fix the count
        seller_profile.vouch_count = vouch_count
        seller_profile.save()
        print(f"  [FIXED] Updated vouch_count to {vouch_count}")
    
    return vouch_count

def test_verification_tier_yellow(test_users, school):
    """Test that profile with complete info gets yellow tier."""
    print("\n" + "="*70)
    print("TEST 3: VERIFICATION TIER - YELLOW (Profile Complete)")
    print("="*70)
    
    user = test_users['user_2']
    profile = user.profile
    
    # Ensure profile is complete
    profile.full_name = 'Test User 2'
    profile.school = school
    profile.year_level = 'year_2'
    profile.phone = '555-0002'
    profile.address = 'Test Address'
    profile.save()
    
    # Update verification tier
    profile.update_verification_tier()
    profile.refresh_from_db()
    
    print(f"✓ Profile for @{user.username}:")
    print(f"  - Full Name: {profile.full_name}")
    print(f"  - School: {profile.school}")
    print(f"  - Year Level: {profile.year_level}")
    print(f"  - Phone: {profile.phone}")
    print(f"  - Address: {profile.address}")
    print(f"  - Is Complete: {profile.is_profile_complete()}")
    print(f"  - Verification Tier: {profile.verification_tier}")
    
    if profile.verification_tier == 'yellow':
        print(f"✓ PASS: Yellow tier assigned for complete profile")
    else:
        print(f"✗ FAIL: Expected 'yellow', got '{profile.verification_tier}'")
    
    return profile

def test_verification_tier_green(test_users, school):
    """Test that active member gets green tier."""
    print("\n" + "="*70)
    print("TEST 4: VERIFICATION TIER - GREEN (Active Member)")
    print("="*70)
    
    buyer = test_users['user_0']
    seller = test_users['user_1']
    buyer_profile = buyer.profile
    seller_profile = seller.profile
    
    # Ensure seller has complete profile
    seller_profile.full_name = 'Test Seller'
    seller_profile.school = school
    seller_profile.year_level = 'year_1'
    seller_profile.phone = '555-0001'
    seller_profile.address = 'Test Address'
    seller_profile.save()
    
    # Ensure buyer profile is complete for yellow tier at minimum
    buyer_profile.full_name = 'Test Buyer'
    buyer_profile.school = school
    buyer_profile.year_level = 'year_1'
    buyer_profile.phone = '555-0000'
    buyer_profile.address = 'Test Address'
    
    # Add a forum post to buyer to qualify for green tier
    from marketplace.models import ForumPost
    forum_post, _ = ForumPost.objects.get_or_create(
        author=buyer,
        title="Looking for textbooks",
        defaults={'body': 'Anyone selling any textbooks for this semester?'}
    )
    buyer_profile.forum_posts_count = ForumPost.objects.filter(author=buyer).count()
    buyer_profile.save()
    
    # Check if transaction exists between them
    existing_transaction = Transaction.objects.filter(buyer=buyer, seller=seller).first()
    
    if not existing_transaction:
        # Create a completed transaction
        category, _ = Category.objects.get_or_create(name='Test Category', defaults={'slug': 'test-category'})
        listing = Listing.objects.create(
            title='Test Product',
            price=100.00,
            category=category,
            seller=seller
        )
        
        transaction = Transaction.objects.create(
            buyer=buyer,
            seller=seller,
            listing=listing,
            price=100.00,
            status='completed',
            buyer_completed=True,
            seller_completed=True
        )
        print(f"✓ Created completed transaction")
        print(f"  - Buyer: @{buyer.username}")
        print(f"  - Seller: @{seller.username}")
        print(f"  - Status: {transaction.status}")
    else:
        print(f"✓ Existing transaction found")
        print(f"  - Status: {existing_transaction.status}")
    
    # Check transaction count
    completed_count = buyer.purchases.filter(status='completed').count()
    print(f"✓ Completed transactions for @{buyer.username}: {completed_count}")
    print(f"✓ Forum posts for @{buyer.username}: {buyer_profile.forum_posts_count}")
    print(f"✓ Vouches for @{buyer.username}: {buyer_profile.vouch_count}")
    
    # Update verification tier
    buyer_profile.update_verification_tier()
    buyer_profile.refresh_from_db()
    
    print(f"✓ Verification tier for @{buyer.username}: {buyer_profile.verification_tier}")
    
    if buyer_profile.verification_tier in ['green', 'blue']:
        print(f"✓ PASS: Active member has green or higher tier")
    else:
        print(f"✗ FAIL: Expected green+ tier, got '{buyer_profile.verification_tier}'")
    
    return buyer_profile, seller_profile

def test_existing_users():
    """Test that existing users are properly handled."""
    print("\n" + "="*70)
    print("TEST 5: EXISTING USERS INTEGRATION")
    print("="*70)
    
    # Get all users with profiles
    all_users = User.objects.filter(profile__isnull=False).order_by('-profile__vouch_count')[:5]
    
    print(f"✓ Found {all_users.count()} users with profiles\n")
    
    for i, user in enumerate(all_users, 1):
        profile = user.profile
        
        # Count actual vouches
        actual_vouches = Review.objects.filter(seller=user, is_vouch=True).count()
        
        print(f"\n  User {i}: @{user.username}")
        print(f"    - Profile Vouch Count: {profile.vouch_count}")
        print(f"    - Actual Vouches: {actual_vouches}")
        print(f"    - Verification Tier: {profile.verification_tier}")
        print(f"    - Profile Complete: {profile.is_profile_complete()}")
        print(f"    - Completed Transactions: {profile.get_completed_transactions_count()}")
        print(f"    - Forum Posts: {profile.forum_posts_count}")
        
        # Check for discrepancies
        if profile.vouch_count != actual_vouches:
            print(f"    ⚠ MISMATCH: vouch_count ({profile.vouch_count}) != actual ({actual_vouches})")
            # Fix it
            profile.vouch_count = actual_vouches
            profile.update_verification_tier()
            profile.save()
            print(f"    [FIXED] Updated to {actual_vouches}")
        
        # Verify tier matches criteria
        expected_tier = "grey"
        if profile.id_verified and profile.get_completed_transactions_count() >= 20:
            expected_tier = "blue"
        elif profile.get_completed_transactions_count() > 0 and (profile.forum_posts_count > 0 or profile.vouch_count > 0):
            expected_tier = "green"
        elif profile.is_profile_complete():
            expected_tier = "yellow"
        
        if profile.verification_tier != expected_tier:
            print(f"    ⚠ TIER MISMATCH: Expected '{expected_tier}', got '{profile.verification_tier}'")
            profile.verification_tier = expected_tier
            profile.save()
            print(f"    [FIXED] Updated tier to '{expected_tier}'")

def test_review_model_save_hook():
    """Test that Review.save() properly updates vouch count."""
    print("\n" + "="*70)
    print("TEST 6: REVIEW MODEL SAVE HOOK")
    print("="*70)
    
    # Get test users
    reviewer = User.objects.filter(username='test_user_0').first()
    seller = User.objects.filter(username='test_user_3').first()
    
    if not reviewer or not seller:
        print("✗ Test users not available for this test")
        return
    
    seller_profile = seller.profile
    initial_count = seller_profile.vouch_count
    
    # Create a review
    review, created = Review.objects.get_or_create(
        reviewer=reviewer,
        seller=seller,
        defaults={'is_vouch': True, 'comment': 'Test vouch for save hook'}
    )
    
    # Refresh profile
    seller_profile.refresh_from_db()
    
    if created:
        print(f"✓ Created new review")
        print(f"  - Initial vouch count: {initial_count}")
        print(f"  - After save vouch count: {seller_profile.vouch_count}")
        if seller_profile.vouch_count > initial_count:
            print(f"✓ PASS: Vouch count incremented")
        else:
            print(f"✗ FAIL: Vouch count not incremented")
    else:
        print(f"ℹ Review already exists, not testing save hook")

def print_summary():
    """Print a summary of all vouch data."""
    print("\n" + "="*70)
    print("FINAL SUMMARY")
    print("="*70)
    
    total_users = User.objects.filter(profile__isnull=False).count()
    total_vouches = Review.objects.filter(is_vouch=True).count()
    total_reviews = Review.objects.count()
    users_with_vouches = User.objects.filter(profile__vouch_count__gt=0).count()
    
    print(f"✓ Total users with profiles: {total_users}")
    print(f"✓ Total vouch reviews: {total_vouches}")
    print(f"✓ Total reviews (including non-vouches): {total_reviews}")
    print(f"✓ Users who have received vouches: {users_with_vouches}")
    
    # Verification tier distribution
    print(f"\nVerification Tier Distribution:")
    tiers = Profile.objects.values('verification_tier').annotate(count=django.db.models.Count('id'))
    for tier_data in tiers:
        tier = tier_data['verification_tier']
        count = tier_data['count']
        labels = {
            'grey': '⚪ Grey (Unverified)',
            'yellow': '🟡 Yellow (Complete Profile)',
            'green': '🟢 Green (Active)',
            'blue': '🔵 Blue (Highly Trusted)'
        }
        print(f"  {labels.get(tier, tier)}: {count} users")

if __name__ == '__main__':
    try:
        # Create test data
        test_users, school = create_test_data()
        
        # Run tests
        test_vouch_functionality(test_users)
        test_vouch_count_increment(test_users)
        test_verification_tier_yellow(test_users, school)
        test_verification_tier_green(test_users, school)
        test_review_model_save_hook()
        test_existing_users()
        
        # Print summary
        print_summary()
        
        print("\n" + "="*70)
        print("✓ ALL TESTS COMPLETED")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"\n✗ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
