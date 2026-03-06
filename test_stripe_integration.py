#!/usr/bin/env python
"""
Test script to verify Stripe integration is working correctly.
This tests the Stripe API configuration and Payment Intent creation.
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'student_marketplace.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

import stripe
from student_marketplace.settings import STRIPE_PUBLIC_KEY, STRIPE_SECRET_KEY

def test_stripe_config():
    """Test that Stripe API keys are properly configured."""
    print("=" * 60)
    print("STRIPE CONFIGURATION TEST")
    print("=" * 60)
    
    print(f"\nPublic Key configured: {bool(STRIPE_PUBLIC_KEY)}")
    if STRIPE_PUBLIC_KEY:
        print(f"  First 20 chars: {STRIPE_PUBLIC_KEY[:20]}...")
    
    print(f"\nSecret Key configured: {bool(STRIPE_SECRET_KEY)}")
    if STRIPE_SECRET_KEY:
        print(f"  First 20 chars: {STRIPE_SECRET_KEY[:20]}...")
    
    if not STRIPE_SECRET_KEY:
        print("\n❌ ERROR: STRIPE_SECRET_KEY is not configured!")
        print("   Please check your .env file and settings.py")
        return False
    
    return True


def test_stripe_api():
    """Test that we can connect to Stripe API."""
    print("\n" + "=" * 60)
    print("STRIPE API CONNECTION TEST")
    print("=" * 60)
    
    if not STRIPE_SECRET_KEY:
        print("\n❌ Cannot test - STRIPE_SECRET_KEY not configured")
        return False
    
    stripe.api_key = STRIPE_SECRET_KEY
    
    try:
        # Try to retrieve account info (minimal API call)
        account = stripe.Account.retrieve()
        
        print(f"\n✅ Successfully connected to Stripe!")
        print(f"   Account ID: {account.id}")
        print(f"   Account Status: {account.charges_enabled and 'Enabled' or 'Disabled'}")
        print(f"   Country: {account.country}")
        
        return True
    except stripe.error.AuthenticationError as e:
        print(f"\n❌ Authentication Error: {e.user_message}")
        print("   Check that STRIPE_SECRET_KEY is valid")
        return False
    except Exception as e:
        print(f"\n❌ Error connecting to Stripe: {str(e)}")
        return False


def test_payment_intent_creation():
    """Test creating a Payment Intent (what the app does for credit card payments)."""
    print("\n" + "=" * 60)
    print("PAYMENT INTENT CREATION TEST")
    print("=" * 60)
    
    if not STRIPE_SECRET_KEY:
        print("\n❌ Cannot test - STRIPE_SECRET_KEY not configured")
        return False
    
    stripe.api_key = STRIPE_SECRET_KEY
    
    try:
        # Create a test payment intent (using PHP currency like the app does)
        intent = stripe.PaymentIntent.create(
            amount=100 * 100,  # 100 PHP in cents
            currency='php',
            description='Test Payment Intent',
            automatic_payment_methods={'enabled': True},
            metadata={
                'test': 'true',
                'transaction_id': '999',
            }
        )
        
        print(f"\n✅ Successfully created Payment Intent!")
        print(f"   Intent ID: {intent.id}")
        print(f"   Amount: {intent.amount} cents ({intent.amount / 100} {intent.currency.upper()})")
        print(f"   Status: {intent.status}")
        print(f"   Client Secret: {intent.client_secret[:20]}...")
        print(f"\n   For testing purposes, use Stripe test card: 4242 4242 4242 4242")
        print(f"   Expiry: Any future date (e.g., 12/25)")
        print(f"   CVC: Any 3 digits (e.g., 123)")
        
        return True
    except stripe.error.InvalidRequestError as e:
        print(f"\n❌ Invalid Request: {e.user_message}")
        print(f"   Details: {str(e)}")
        return False
    except Exception as e:
        print(f"\n❌ Error creating Payment Intent: {str(e)}")
        return False


def main():
    """Run all tests."""
    results = []
    
    # Test 1: Configuration
    results.append(("Stripe Configuration", test_stripe_config()))
    
    # Test 2: API Connection
    results.append(("Stripe API Connection", test_stripe_api()))
    
    # Test 3: Payment Intent Creation
    results.append(("Payment Intent Creation", test_payment_intent_creation()))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:10} {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ All Stripe integration tests passed!")
        print("   The app should be able to process credit card payments.")
    else:
        print("\n❌ Some tests failed. Check configurations above.")
    
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
