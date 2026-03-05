#!/usr/bin/env python
"""Test script for verification tier system."""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'student_marketplace.settings')
sys.path.insert(0, '/root')
django.setup()

from marketplace.models import Profile, Review, Transaction, User

def test_verification_system():
    """Test the new verification tier and vouch system."""
    
    # Create a demo user if needed
    test_user, created = User.objects.get_or_create(
        username='testuser',
        defaults={'email': 'test@example.com'}
    )
    if created:
        test_user.set_password('testpass123')
        test_user.save()
        print(f"✓ Created test user: {test_user.username}")
    else:
        print(f"✓ Using existing user: {test_user.username}")

    # Get or create profile
    profile, _ = Profile.objects.get_or_create(user=test_user)

    # Test 1: Yellow tier - Complete profile
    print("\n1. Testing Yellow Tier (Complete Profile):")
    
    # First get a school object or it will stay incomplete
    from marketplace.models import School
    school = School.objects.first()
    if not school:
        school = School.objects.create(name='Test School', short_name='TS')
        print(f"   Created test school: {school.name}")
    
    profile.full_name = "Test User"
    profile.school = school
    profile.year_level = "year_1"
    profile.phone = "09123456789"
    profile.address = "Manila"
    profile.save()
    profile.update_verification_tier()
    print(f"   Verification Tier: {profile.verification_tier}")
    print(f"   Is Profile Complete: {profile.is_profile_complete()}")
    assert profile.verification_tier == 'yellow', f"Expected 'yellow', got '{profile.verification_tier}'"
    print("   ✓ Yellow tier test PASSED")

    # Test 2: Green tier - Add forum posts and transactions
    print("\n2. Testing Green Tier (Active Member):")
    profile.forum_posts_count = 3
    profile.vouch_count = 2
    profile.save()
    profile.update_verification_tier()
    print(f"   Verification Tier: {profile.verification_tier}")
    print(f"   Forum Posts: {profile.forum_posts_count}")
    print(f"   Vouches: {profile.vouch_count}")
    assert profile.verification_tier == 'green', f"Expected 'green', got '{profile.verification_tier}'"
    print("   ✓ Green tier test PASSED")

    # Test 3: Check that Review model works
    print("\n3. Testing Review Model (Vouch System):")
    review_fields = [f.name for f in Review._meta.get_fields()]
    print(f"   Review fields: {review_fields}")
    assert 'is_vouch' in review_fields, "Review model missing 'is_vouch' field"
    assert 'rating' not in review_fields, "Review model should not have 'rating' field"
    print("   ✓ Review model test PASSED")

    # Test 4: Backward compatibility
    print("\n4. Testing Backward Compatibility:")
    print(f"   average_rating property (vouch_count): {profile.average_rating}")
    print(f"   review_count property (vouch_count): {profile.review_count}")
    assert profile.average_rating == profile.vouch_count, "average_rating should equal vouch_count"
    assert profile.review_count == profile.vouch_count, "review_count should equal vouch_count"
    print("   ✓ Backward compatibility test PASSED")

    print("\n✓ All tests PASSED successfully!")

if __name__ == '__main__':
    test_verification_system()
