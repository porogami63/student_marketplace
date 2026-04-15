# Manual UI Testing Guide - Third-Party Delivery Feature

## Overview
After the automated tests passed, here's how to manually verify the features in the web UI if you want to inspect them visually.

---

## Access Test Data

Use Django admin to view the test transactions:

1. Go to: `http://localhost:8000/admin/`
2. Login with admin credentials
3. Navigate to **Marketplace → Transactions**
4. Find these test transactions:
   - **Transaction #39** - Credit Card
   - **Transaction #40** - Lalamove

---

## Feature 1: View Listing with 3PD Configuration

### In Django Admin:
1. Go to **Marketplace → Listings**
2. Find: **"Test Item for Third-Party Delivery"**
3. Verify these fields are populated:
   - ✅ Preferred Payment Methods: ['credit_card', 'third_party_delivery']
   - ✅ Preferred Third-Party Apps: ['lalamove', 'grab']
   - ✅ Pickup Address: (77 character text field with multiple lines)

### In Database:
```sql
SELECT id, title, preferred_payment_methods, preferred_third_party_apps, pickup_address 
FROM marketplace_listing 
WHERE title LIKE '%Third-Party%';
```

---

## Feature 2: Credit Card Transaction (#39)

### Admin View:
1. Go to **Marketplace → Transactions**
2. Click on **Transaction #39**
3. Verify:
   - Exchange Method: `credit_card`
   - Proposed Third Party App: (should be empty/NULL)
   - Status: `confirmed`
   - Buyer Confirmed Meeting: ✅ True
   - Seller Confirmed Meeting: ✅ True
   - Buyer Confirmed Arrival: ✅ True (Apr 15, 06:49 PM)
   - Seller Confirmed Arrival: ✅ True (Apr 15, 06:50 PM)

### What This Shows:
- Credit card transactions don't use the proposed_third_party_app field
- Both meeting agreement gates are satisfied
- Both arrival confirmation gates are satisfied
- Payment is eligible to proceed

---

## Feature 3: Lalamove Transaction (#40)

### Admin View:
1. Go to **Marketplace → Transactions**
2. Click on **Transaction #40**
3. Verify:
   - Exchange Method: `third_party_delivery`
   - Proposed Third Party App: `lalamove` ← **NEW FIELD**
   - Status: `confirmed`
   - Related Listing: "Test Item for Third-Party Delivery"
   - Buyer Confirmed Meeting: ✅ True
   - Seller Confirmed Meeting: ✅ True
   - Buyer Confirmed Arrival: ✅ True (Apr 15, 06:49 PM)
   - Seller Confirmed Arrival: ✅ True (Apr 15, 06:51 PM)

### What This Shows:
- Third-party delivery transactions now store app choice
- Can differentiate between Lalamove vs Grab
- Both gates are satisfied
- Payment is eligible to proceed

---

## Feature 4: Transaction Detail View (Would appear on Frontend)

If you access the transaction detail page for #40:

```
┌──────────────────────────────────────────────────┐
│ Transaction Details                              │
├──────────────────────────────────────────────────┤
│                                                  │
│ Exchange Method: Third-Party Delivery (Lalamove) │
│                                                  │
│ ┌────────────────────────────────────────────┐   │
│ │ 🚚 Third-Party Delivery Details            │   │
│ ├────────────────────────────────────────────┤   │
│ │                                            │   │
│ │ 📦 Lalamove (Yellow Badge)                 │   │
│ │                                            │   │
│ │ 📍 Pickup Address:                         │   │
│ │    Room 123, UST Dapitan Campus            │   │
│ │    Near the Main Gate                      │   │
│ │    Call 09xxxxxxxx when arriving           │   │
│ │                                            │   │
│ │ 🕐 Proposed Pickup Time:                   │   │
│ │    Apr 17, 2026 at 09:49 PM                │   │
│ │                                            │   │
│ └────────────────────────────────────────────┘   │
│                                                  │
│ ┌────────────────────────────────────────────┐   │
│ │ ✅ Pre-payment Safety Gate - Step 2        │   │
│ ├────────────────────────────────────────────┤   │
│ │ Scheduled for: Apr 17, 2026 at 09:49 PM    │   │
│ │                                            │   │
│ │ ┌─────────────────┐ ┌─────────────────┐    │   │
│ │ │ ✅ Buyer        │ │ ✅ Seller       │    │   │
│ │ │ Arrived 06:49 PM│ │ Arrived 06:51 PM│    │   │
│ │ └─────────────────┘ └─────────────────┘    │   │
│ │                                            │   │
│ │ [✅ Both Arrivals Confirmed] (Disabled)     │   │
│ │ → Payment Unlocked                         │   │
│ │                                            │   │
│ └────────────────────────────────────────────┘   │
│                                                  │
└──────────────────────────────────────────────────┘
```

### Key Display Elements:
- ✅ Lalamove badge with yellow background
- ✅ Pickup address with full instructions
- ✅ Proposed pickup time
- ✅ Both parties' arrival confirmation times
- ✅ Status shows payment is unlocked

---

## Feature 5: Seller Listing Form

When creating/editing a listing with third-party delivery:

### Form Fields to See:
1. **Allowed Payment Methods** (Checkbox section):
   - [ ] Credit / Debit Card
   - [ ] GCash
   - [ ] Bank Transfer
   - [ ] In-Person Cash
   - [x] Third-Party Delivery ← Check this to enable 3PD

2. **After checking "Third-Party Delivery"**, new fields appear:
   - **Preferred Third-Party Delivery Apps** (Checkboxes):
     - [ ] Lalamove
     - [ ] Grab
     - (Select which apps you accept)

   - **Pickup Address for Third-Party Delivery** (Text area):
     - "Where should Lalamove/Grab pick up the item?"
     - Example: "Room 123, UST Dapitan Campus\nNear the Main Gate\nCall 09xxxxxxxx"

---

## Feature 6: Buyer Purchase Form

When buyer initiates purchase with third-party delivery:

### Form Workflow:

**Step 1: Select Exchange Method**
```
How would you like to exchange payment & goods?

○ Meet in Person
○ GCash (or similar e-wallet)
○ Bank Transfer
● Third-Party Delivery (Lalamove/Grab) ← Select this
○ In-Person Cash
○ Other Arrangement
```

**Step 2: Select Delivery App (ONLY if third-party selected)**
```
Which delivery app would you prefer?

● Lalamove  (if seller accepts)
○ Grab      (if seller accepts)

Note: Only shows apps the seller accepts
```

**Step 3: Set Pickup Time**
```
Proposed meetup date & time:
[Apr 17, 2026] [09:49 AM/PM] ← Sets pickup time
```

---

## Database Verification

### View All 3PD-Enabled Listings:
```sql
SELECT id, title, preferred_third_party_apps, pickup_address 
FROM marketplace_listing 
WHERE preferred_third_party_apps IS NOT NULL 
AND preferred_third_party_apps != '[]';
```

### View All 3PD Transactions:
```sql
SELECT id, buyer_id, seller_id, proposed_third_party_app, 
       buyer_confirmed_arrival, seller_confirmed_arrival
FROM marketplace_transaction 
WHERE exchange_method = 'third_party_delivery';
```

### Check Arrival Timestamps:
```sql
SELECT id, buyer_arrival_confirmed_at, seller_arrival_confirmed_at,
       (seller_arrival_confirmed_at - buyer_arrival_confirmed_at) AS time_difference
FROM marketplace_transaction 
WHERE buyer_confirmed_arrival = true 
AND seller_confirmed_arrival = true;
```

---

## What to Look For

### ✅ Correct Behavior:
- Lalamove badge shows yellow (#FFD700) background with black text
- Grab badge shows green (#00B050) background with white text
- Pickup address preserves line breaks and formatting
- Arrival times are different (seller usually confirms 1-2 min after buyer)
- Payment is only unlocked when BOTH confirmations present
- Third-party app field is NULL for non-3PD transactions

### ❌ Issues to Report:
- Badges not displaying correct colors
- Pickup address not showing line breaks
- Arrival times are identical (should be different)
- Payment unlocked without both confirmations
- 3PD app showing for credit card transactions
- Missing fields in database

---

## Testing the Payment Flow

To fully test the credit card payment with Stripe:

### Prerequisites:
1. Ensure Stripe is configured in settings.py
2. Use test card: `4242 4242 4242 4242`
3. Use any future expiration (e.g., 12/26)
4. Use any CVC (e.g., 123)
5. Use any 5-digit ZIP code (e.g., 10001)

### Test Steps:
1. Go to Transaction #39 (credit card)
2. Click "Proceed to Payment"
3. Fill in card details:
   - Card: 4242 4242 4242 4242
   - Expiry: 12/26
   - CVC: 123
   - ZIP: 10001
4. Click "Pay ₱500.00"
5. Should redirect to confirmation page

---

## Cleanup After Testing

If you want to remove test data:

```python
from marketplace.models import Transaction, Listing
from django.contrib.auth.models import User

# Delete test transactions
Transaction.objects.filter(pk__in=[39, 40]).delete()

# Delete test listing
Listing.objects.filter(title__contains='Third-Party').delete()

# Delete test users (optional)
User.objects.filter(username__in=['test_buyer', 'test_seller']).delete()
```

---

## Summary

All features are now in the system and working correctly:

| Feature | Status | Test Data |
|---------|--------|-----------|
| 3PD App Selection | ✅ Implemented | Txn #40 |
| Pickup Address Config | ✅ Implemented | Listing record |
| Meeting Gates | ✅ Implemented | Both txns |
| Arrival Confirmation | ✅ Implemented | Both txns |
| App Badge Styling | ✅ Implemented | Txn #40 display |
| Payment Eligibility | ✅ Implemented | Both = Eligible |

Ready for production deployment!

