# Vouch & Verification Implementation Technical Guide

## Architecture Overview

The vouch and verification system is built on three main components:

### 1. **Review Model** (Vouch Storage)
```python
class Review(models.Model):
    reviewer = ForeignKey(User)          # Who gave the vouch
    seller = ForeignKey(User)            # Who received it
    listing = ForeignKey(Listing)        # Optional: related listing
    transaction = ForeignKey(Transaction) # Optional: related transaction
    is_vouch = BooleanField()            # True = vouch, False = feedback
    comment = TextField()                # Optional feedback
    created_at = DateTimeField()         # When created
    updated_at = DateTimeField()         # When updated
```

**Unique Constraint:** One review per reviewer-seller-listing combination

### 2. **Profile Fields** (User Verification Data)
```python
class Profile(models.Model):
    # Vouch data
    vouch_count = PositiveIntegerField()  # Total vouches received
    
    # Tier data
    verification_tier = CharField(       # grey, yellow, green, or blue
        choices=VERIFICATION_TIER_CHOICES
    )
    
    # Activity tracking
    forum_posts_count = PositiveIntegerField()
    total_sold = PositiveIntegerField()
    total_bought = PositiveIntegerField()
    id_verified = BooleanField()         # Admin verification
    
    # Profile completion fields
    full_name = CharField()
    school = ForeignKey(School)
    year_level = CharField()
    phone = CharField()
    address = CharField()
```

### 3. **Verification Logic** (Tier Calculation)
```python
def update_verification_tier(self):
    completed_transactions = self.get_completed_transactions_count()
    
    if self.id_verified and completed_transactions >= 20:
        tier = 'blue'      # Highly trusted
    elif completed_transactions > 0 and (self.forum_posts_count > 0 or self.vouch_count > 0):
        tier = 'green'     # Active member
    elif self.is_profile_complete():
        tier = 'yellow'    # Complete profile
    else:
        tier = 'grey'      # Unverified
    
    self.verification_tier = tier
    self.save(update_fields=['verification_tier'])
```

---

## Data Flow

### When a Vouch is Created

```
1. User visits profile page
   ↓
2. User fills vouch form
   ↓
3. leave_review view creates Review object
   ↓
4. Review.save() is called (model save hook)
   ├── Checks if new or update
   ├── Tracks old is_vouch value for updates
   ├── Calls parent save()
   ├── Updates seller's vouch_count (if applicable)
   ├── Calls profile.update_verification_tier()
   └── Saves profile
   ↓
5. post_save signal fires (notify_seller_on_review)
   ├── Creates Notification
   ├── Sets message based on is_vouch status
   └── Sends to seller
   ↓
6. Seller receives notification and tier updates
```

### Vouch Count Increment Logic

```python
def save(self, *args, **kwargs):
    is_new = self.pk is None
    old_is_vouch = None
    
    # Get old value if updating
    if not is_new:
        old_review = Review.objects.get(pk=self.pk)
        old_is_vouch = old_review.is_vouch
    
    super().save(*args, **kwargs)
    
    profile = self.seller.profile
    
    # Only increment on:
    # 1. NEW vouch (is_new=True AND is_vouch=True)
    # 2. STATUS CHANGE (False→True)
    if is_new and self.is_vouch:
        profile.vouch_count += 1
    elif not is_new and old_is_vouch is not None:
        if not old_is_vouch and self.is_vouch:      # False→True
            profile.vouch_count += 1
        elif old_is_vouch and not self.is_vouch:    # True→False
            if profile.vouch_count > 0:
                profile.vouch_count -= 1
    
    profile.update_verification_tier()
    profile.save()
```

---

## Tier Requirements Matrix

| Tier | Color | Requirements | Use Case |
|------|-------|--------------|----------|
| Grey | ⚪ | Default | New/inactive users |
| Yellow | 🟡 | Complete profile | Engaged users |
| Green | 🟢 | Transactions + (Forum posts OR Vouches) | Active members |
| Blue | 🔵 | 20+ Transactions + ID verified | Highly trusted |

### Example Scenarios

**User A → Grey Tier**
- New user, incomplete profile
- No transactions
- No activity

**User B → Yellow Tier**
- Filled all profile fields
- No transactions yet
- Just getting started

**User C → Green Tier**
- Has 3 completed transactions
- Created 2 forum posts
- No ID verification needed

**User D → Blue Tier**
- Has 25 completed transactions
- ID verified by admin
- Most trusted level

---

## Signal Handlers

### `notify_seller_on_review` Signal

**Trigger:** When a new Review is created  
**Action:** Creates a Notification for the seller

```python
@receiver(post_save, sender=Review)
def notify_seller_on_review(sender, instance, created, **kwargs):
    if created and instance.reviewer_id != instance.seller_id:
        vouch_text = "Vouched for you" if instance.is_vouch else "Posted feedback"
        Notification.objects.create(
            user=instance.seller,
            message=f"New review from {instance.reviewer.username}: {vouch_text}",
            url=reverse('marketplace:public_profile', args=[instance.reviewer.username])
        )
```

---

## Database Queries

### Get user's tier
```python
profile = Profile.objects.get(user_id=user_id)
tier = profile.verification_tier
```

### Get all vouches for a user
```python
vouches = Review.objects.filter(seller_id=user_id, is_vouch=True)
```

### Count users by tier
```python
from django.db.models import Count
by_tier = Profile.objects.values('verification_tier').annotate(count=Count('id'))
```

### Find green tier users
```python
green_users = Profile.objects.filter(verification_tier='green')
```

### Recalculate all tiers
```python
for profile in Profile.objects.all():
    profile.update_verification_tier()
```

---

## View Integration

### `public_profile_view` Usage

```python
def public_profile_view(request, username):
    user = get_object_or_404(User, username=username)
    profile, _ = Profile.objects.get_or_create(user=user)
    
    # Get vouches
    reviews = Review.objects.filter(seller=user).select_related('reviewer')
    
    # Check if can leave vouch
    has_reviewed = Review.objects.filter(
        reviewer=request.user, 
        seller=user
    ).exists()
    
    context = {
        'user': user,
        'profile': profile,
        'reviews': reviews,
        'has_reviewed': has_reviewed,
    }
    return render(request, 'marketplace/public_profile.html', context)
```

### `leave_review` View

```python
def leave_review(request, username):
    seller = get_object_or_404(User, username=username)
    
    if request.user == seller:
        messages.error(request, "You can't vouch for yourself.")
        return redirect('marketplace:public_profile', username=username)
    
    if request.method == 'POST':
        is_vouch = request.POST.get('is_vouch') == 'true'
        comment = request.POST.get('comment', '')
        
        review, created = Review.objects.get_or_create(
            reviewer=request.user,
            seller=seller,
            defaults={'is_vouch': is_vouch, 'comment': comment}
        )
        
        if not created:
            review.is_vouch = is_vouch
            review.comment = comment
            review.save()  # Triggers save hook
        
        messages.success(request, 'Your vouch has been posted!')
        return redirect('marketplace:public_profile', username=username)
    
    return render(request, 'marketplace/leave_review.html', {...})
```

---

## Testing Checklist

### Unit Tests
- [ ] Review model creates correctly
- [ ] Profile tier updates correctly
- [ ] Vouch count increments only once
- [ ] Vouch count decrements on removal
- [ ] Notification creates on new vouch
- [ ] Self-vouches prevented in view

### Integration Tests
- [ ] Full user flow: create → vouch → update → notify
- [ ] Existing users data consistency
- [ ] Tier changes with activity changes
- [ ] Multiple vouches don't duplicate

### Edge Cases
- [ ] User with no profile
- [ ] Deleted user references
- [ ] Rapid successive vouchs
- [ ] Tier recalculation with missing data
- [ ] Forum posts not yet implemented

---

## Performance Considerations

### Optimization Tips
1. **Caching:** Cache verification tiers (they're calculated frequently)
   ```python
   cache_key = f'profile_tier_{profile_id}'
   tier = cache.get(cache_key)
   if not tier:
       profile.update_verification_tier()
       tier = profile.verification_tier
       cache.set(cache_key, tier, 3600)  # 1 hour
   ```

2. **Batch Updates:** Recalculate tiers in batches
   ```python
   profiles = Profile.objects.filter(verification_tier='grey')[:100]
   for profile in profiles:
       profile.update_verification_tier()
   Profile.objects.bulk_update(profiles, ['verification_tier'], batch_size=100)
   ```

3. **Indexes:** Ensure these fields are indexed
   - Profile.verification_tier
   - Review.seller
   - Review.is_vouch
   - Profile.vouch_count

---

## Migration History

**No migrations needed!** All models and fields already exist in the database.

Review exists with all necessary fields:
- ✅ reviewer_id
- ✅ seller_id
- ✅ is_vouch
- ✅ comment
- ✅ created_at

Profile exists with all necessary fields:
- ✅ vouch_count
- ✅ verification_tier
- ✅ forum_posts_count
- ✅ id_verified
- ✅ All profile fields

---

## Troubleshooting

### Issue: Vouch count doesn't match reviews
**Solution:** Run consistency check
```python
for profile in Profile.objects.all():
    actual = Review.objects.filter(seller=profile.user, is_vouch=True).count()
    if profile.vouch_count != actual:
        profile.vouch_count = actual
        profile.save()
```

### Issue: Tier doesn't update
**Solution:** Manually trigger update
```python
profile.update_verification_tier()
```

### Issue: Notification not appearing
**Solution:** Check signal handler is registered
```python
from django.core.signals import request_started
from django.dispatch import receiver
# Ensure signals.py is imported in apps.py ready() method
```

---

## API Reference

### Model Methods

**Profile.update_verification_tier()**
- Recalculates tier based on current activity
- Saves the profile
- Triggered automatically on save hooks

**Profile.is_profile_complete()**
- Returns: Boolean
- Checks if all profile fields are filled
- Required for Yellow tier

**Profile.get_completed_transactions_count()**
- Returns: Integer count
- Sums buyer + seller completed transactions
- Required for Green/Blue tiers

---

**Last Updated:** March 5, 2026  
**Status:** Production Ready
