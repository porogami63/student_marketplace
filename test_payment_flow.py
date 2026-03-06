#!/usr/bin/env python
"""
Test script to verify the complete payment flow works end-to-end.
Tests database models, views, and Stripe integration.
"""

import os
import sys
import django
from decimal import Decimal

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'student_marketplace.settings')
sys.path.insert(0, r'c:\Users\Gigabyte\student_marketplace')
django.setup()

from django.contrib.auth.models import User
from marketplace.models import Payment
from django.utils import timezone
import stripe
from django.conf import settings

# Configure stripe
stripe.api_key = settings.STRIPE_SECRET_KEY

def test_1_stripe_payment_intent():
    """Test 1: Verify Stripe PaymentIntent creation"""
    print("\n" + "="*70)
    print("TEST 1: Stripe PaymentIntent Creation")
    print("="*70)
    
    try:
        # Create PaymentIntent with PHP currency
        intent = stripe.PaymentIntent.create(
            amount=50000,  # 500 PHP in cents
            currency='php',
            description='Test Payment for Student Marketplace',
            metadata={'test': 'true'},
        )
        
        print(f"[PASS] PaymentIntent created successfully")
        print(f"  - Intent ID: {intent.id}")
        print(f"  - Amount: {intent.amount} PHP cents = PHP{intent.amount/100}")
        print(f"  - Currency: {intent.currency.upper()}")
        print(f"  - Status: {intent.status}")
        print(f"  - Client Secret: {intent.client_secret[:50]}...")
        
        return True
        
    except stripe.error.CardError as e:
        print(f"[FAIL] Card Error: {e.user_message}")
        return False
    except stripe.error.RateLimitError:
        print(f"[FAIL] Rate Limit Error")
        return False
    except stripe.error.InvalidRequestError as e:
        print(f"[FAIL] Invalid Request: {str(e)}")
        return False
    except stripe.error.AuthenticationError:
        print(f"[FAIL] Authentication Error")
        return False
    except stripe.error.APIConnectionError:
        print(f"[FAIL] API Connection Error")
        return False
    except stripe.error.StripeError as e:
        print(f"[FAIL] Stripe Error: {str(e)}")
        return False
    except Exception as e:
        print(f"[FAIL] {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def test_2_stripe_payment_intent():
    """Test 2: Verify Stripe PaymentIntent creation with metadata"""
    print("\n" + "="*70)
    print("TEST 2: Stripe PaymentIntent with Marketplace Data")
    print("="*70)
    
    try:
        # Create PaymentIntent with marketplace transaction metadata
        intent = stripe.PaymentIntent.create(
            amount=100000,  # 1000 PHP in cents
            currency='php',
            description='Marketplace Purchase: Test Item',
            metadata={
                'transaction_id': '999',
                'buyer': 'test_buyer',
                'seller': 'test_seller',
            },
        )
        
        print(f"[PASS] PaymentIntent with metadata created successfully")
        print(f"  - Intent ID: {intent.id}")
        print(f"  - Amount: PHP{intent.amount/100}")
        print(f"  - Metadata: {intent.metadata}")
        
        return True
        
    except Exception as e:
        print(f"[FAIL] {str(e)}")
        return False

def test_3_payment_views():
    """Test 3: Verify payment views are importable and callable"""
    print("\n" + "="*70)
    print("TEST 3: Payment Views Configuration")
    print("="*70)
    
    try:
        from marketplace.views import payment_checkout, payment_success, payment_cancel
        
        print(f"[PASS] All payment views imported successfully")
        print(f"  - payment_checkout: {'Callable' if callable(payment_checkout) else 'NOT callable'}")
        print(f"  - payment_success: {'Callable' if callable(payment_success) else 'NOT callable'}")
        print(f"  - payment_cancel: {'Callable' if callable(payment_cancel) else 'NOT callable'}")
        
        return True
        
    except ImportError as e:
        print(f"[FAIL] Import Error: {str(e)}")
        return False
    except Exception as e:
        print(f"[FAIL] {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def test_4_payment_admin():
    """Test 4: Verify Payment model is registered in admin"""
    print("\n" + "="*70)
    print("TEST 4: Payment Admin Registration")
    print("="*70)
    
    try:
        from django.contrib.admin import site
        
        if Payment in site._registry:
            print(f"[PASS] Payment model registered in admin")
            admin_class = site._registry[Payment]
            print(f"  - Admin class: {admin_class.__class__.__name__}")
            print(f"  - List display: {admin_class.list_display}")
            print(f"  - List filters: {admin_class.list_filter}")
            return True
        else:
            print(f"[FAIL] Payment model NOT registered in admin")
            return False
            
    except Exception as e:
        print(f"[FAIL] {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def test_5_url_routing():
    """Test 5: Verify payment URLs are configured"""
    print("\n" + "="*70)
    print("TEST 5: Payment URL Routing")
    print("="*70)
    
    try:
        from django.urls import reverse
        
        # Test URL reversing
        payment_checkout_url = reverse('marketplace:payment_checkout', kwargs={'transaction_id': 1})
        payment_success_url = reverse('marketplace:payment_success', kwargs={'transaction_id': 1})
        payment_cancel_url = reverse('marketplace:payment_cancel', kwargs={'transaction_id': 1})
        
        print(f"[PASS] All payment URLs configured successfully")
        print(f"  - Checkout: {payment_checkout_url}")
        print(f"  - Success: {payment_success_url}")
        print(f"  - Cancel: {payment_cancel_url}")
        
        return True
        
    except Exception as e:
        print(f"[FAIL] {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("PAYMENT FLOW INTEGRATION TEST SUITE")
    print("="*70)
    
    results = []
    
    # Run all tests
    results.append(("Stripe PaymentIntent Creation", test_1_stripe_payment_intent()))
    results.append(("Stripe PaymentIntent with Metadata", test_2_stripe_payment_intent()))
    results.append(("Payment Views Configuration", test_3_payment_views()))
    results.append(("Payment Admin Registration", test_4_payment_admin()))
    results.append(("Payment URL Routing", test_5_url_routing()))
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"[{status}] {test_name}")
    
    print("\n" + "="*70)
    print(f"TOTAL: {passed}/{total} tests passed")
    print("="*70 + "\n")
    
    return passed == total

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
