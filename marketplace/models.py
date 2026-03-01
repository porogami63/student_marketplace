from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse
from django.db.models import JSONField


class School(models.Model):
    """University Belt schools in Manila with official color motifs and logos."""
    name = models.CharField(max_length=120)
    short_name = models.CharField(max_length=20, blank=True)
    logo_url = models.URLField(blank=True, null=True, help_text='URL to school logo image (preferably PNG with transparency)')
    primary_color = models.CharField(max_length=7, default='#1a2b4a', help_text='Hex color (e.g. #FFD700)')
    secondary_color = models.CharField(max_length=7, default='#ffffff', blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.short_name or self.name


class Category(models.Model):
    """Listing categories (textbooks, electronics, etc.)."""
    name = models.CharField(max_length=60)
    slug = models.SlugField(unique=True)
    icon = models.CharField(max_length=30, default='box')

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Listing(models.Model):
    """Marketplace listing."""
    CONDITION_CHOICES = [
        ('new', 'Brand New'),
        ('like_new', 'Like New'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('used', 'Well Used'),
    ]

    CAMPUS_CHOICES = [
        ('manila', 'Manila'),
        ('dapitan', 'Dapitan'),
        ('pureza', 'Pureza'),
        ('public', 'Public'),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default='good')
    campus = models.CharField(max_length=20, choices=CAMPUS_CHOICES, blank=True, null=True)
    image = models.ImageField(upload_to='listings/', blank=True, null=True)
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='listings')
    school = models.ForeignKey(School, on_delete=models.SET_NULL, null=True, blank=True)
    contact_info = models.CharField(max_length=200, blank=True, help_text='Phone or social media')
    is_sold = models.BooleanField(default=False)
    view_count = models.PositiveIntegerField(default=0)
    product_details = JSONField(default=dict, blank=True, help_text='Category-specific product details (brand, size, material, etc.)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('marketplace:listing_detail', kwargs={'pk': self.pk})

    @property
    def pending_offers_count(self):
        """Returns the number of pending offers for this listing."""
        from .models import Message
        return Message.objects.filter(
            conversation__listing=self,
            is_offer=True,
            offer_status='pending'
        ).count()


class Profile(models.Model):
    """Extended user profile for students."""
    YEAR_LEVEL_CHOICES = [
        ('grade_11', 'Grade 11'),
        ('grade_12', 'Grade 12'),
        ('year_1', 'Year 1 - College'),
        ('year_2', 'Year 2 - College'),
        ('year_3', 'Year 3 - College'),
        ('year_4', 'Year 4 - College'),
        ('year_5', 'Year 5 - College'),
        ('masters', "Master's Degree"),
        ('doctorate', 'Doctorate Degree'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    full_name = models.CharField(max_length=120, blank=True)
    school = models.ForeignKey(School, on_delete=models.SET_NULL, null=True, blank=True)
    year_level = models.CharField(max_length=20, choices=YEAR_LEVEL_CHOICES, blank=True, null=True, help_text='Academic year level')
    age = models.PositiveIntegerField(blank=True, null=True)
    birthday = models.DateField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True)
    contact_info = models.CharField(max_length=200, blank=True, help_text='Social media or alternate contact')
    address = models.CharField(max_length=255, blank=True, help_text='General meetup area or barangay')
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    header_image = models.ImageField(upload_to='profile_headers/', blank=True, null=True, help_text='Cover image for your profile header')
    google_avatar_url = models.URLField(blank=True)
    reputation_score = models.DecimalField(max_digits=3, decimal_places=2, default=5.0, help_text='Average reputation score from reviews (1-5 stars)')
    review_count = models.PositiveIntegerField(default=0, help_text='Total number of reviews received')
    total_sold = models.PositiveIntegerField(default=0, help_text='Number of items sold')
    total_bought = models.PositiveIntegerField(default=0, help_text='Number of items purchased')
    is_verified = models.BooleanField(default=False, help_text='Verified email or school verification')
    pinned_post = models.ForeignKey('ProfilePost', on_delete=models.SET_NULL, null=True, blank=True, related_name='pinned_in_profile', help_text='Featured post on profile')

    def __str__(self):
        return f"{self.user.username}'s profile"

    @property
    def display_name(self):
        return self.full_name or self.user.get_full_name() or self.user.username

    @property
    def average_rating(self):
        """Backward compatibility property for reputation_score."""
        return self.reputation_score

    @property
    def total_spent(self):
        """Calculate total amount spent by this user as a buyer."""
        from django.db.models import Sum
        total = self.user.purchases.filter(status='completed').aggregate(Sum('price'))['price__sum']
        return total or 0

    @property
    def total_earned(self):
        """Calculate total amount earned by this user as a seller."""
        from django.db.models import Sum
        total = self.user.sales.filter(status='completed').aggregate(Sum('price'))['price__sum']
        return total or 0

    def update_rating(self):
        """Recalculate reputation score from reviews."""
        reviews = self.user.reviews_received.all()
        if reviews.exists():
            self.reputation_score = sum(r.rating for r in reviews) / reviews.count()
            self.review_count = reviews.count()
        else:
            self.reputation_score = 5.0
            self.review_count = 0
        self.save(update_fields=['reputation_score', 'review_count'])


class Favorite(models.Model):
    """User's saved/favorited listings."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorites')
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'listing']


class Conversation(models.Model):
    """Private conversation between two users, optionally about a listing."""
    listing = models.ForeignKey(Listing, on_delete=models.SET_NULL, null=True, blank=True, related_name='conversations')
    participants = models.ManyToManyField(User, related_name='conversations', through='ConversationParticipant')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_other_participant(self, user):
        return self.participants.exclude(pk=user.pk).first()


class ConversationParticipant(models.Model):
    """Links users to conversations."""
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['conversation', 'user']


class Message(models.Model):
    """Private message within a conversation."""
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    body = models.TextField()
    is_offer = models.BooleanField(default=False)
    offer_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    offer_status = models.CharField(
        max_length=20, 
        choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('declined', 'Declined')],
        default='pending',
        null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_hidden = models.BooleanField(default=False, help_text='Moderator-hidden content')
    moderation_notes = models.TextField(blank=True, help_text='Internal moderator notes')

    class Meta:
        ordering = ['created_at']


class ForumPost(models.Model):
    """Live forum post - users can promote their listings here."""
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='forum_posts')
    title = models.CharField(max_length=200)
    body = models.TextField()
    listing = models.ForeignKey(Listing, on_delete=models.SET_NULL, null=True, blank=True, related_name='forum_promotions')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_hidden = models.BooleanField(default=False, help_text='Moderator-hidden content')
    moderation_notes = models.TextField(blank=True, help_text='Internal moderator notes')

    class Meta:
        ordering = ['-created_at']


class ForumReply(models.Model):
    """Reply to a forum post."""
    post = models.ForeignKey(ForumPost, on_delete=models.CASCADE, related_name='replies')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='forum_replies')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_hidden = models.BooleanField(default=False, help_text='Moderator-hidden content')
    moderation_notes = models.TextField(blank=True, help_text='Internal moderator notes')

    class Meta:
        ordering = ['created_at']
        verbose_name_plural = 'Forum replies'


class Notification(models.Model):
    """Simple notification for users (messages, forum replies, etc.)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.CharField(max_length=255)
    url = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

class Transaction(models.Model):
    """Track sales between buyer and seller with exchange method tracking."""
    STATUS_CHOICES = [
        ('pending', 'Pending - Waiting for seller confirmation'),
        ('confirmed', 'Confirmed - Ready for exchange'),
        ('completed', 'Completed - Transaction finished'),
        ('cancelled', 'Cancelled'),
    ]
    
    EXCHANGE_METHOD_CHOICES = [
        ('in_person', 'Meet in Person'),
        ('gcash', 'GCash (or similar e-wallet)'),
        ('bank_transfer', 'Bank Transfer'),
        ('other', 'Other arrangement'),
    ]

    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='purchases')
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sales')
    listing = models.ForeignKey(Listing, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    exchange_method = models.CharField(max_length=20, choices=EXCHANGE_METHOD_CHOICES, default='in_person')
    notes = models.TextField(blank=True, help_text='Buyer notes about delivery/exchange (e.g., preferred meetup location)')
    seller_notes = models.TextField(blank=True, help_text='Seller confirmation notes (e.g., availability, location)')
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    buyer_completed = models.BooleanField(default=False, help_text='Buyer confirmed exchange happened')
    seller_completed = models.BooleanField(default=False, help_text='Seller confirmed exchange happened')
    admin_notes = models.TextField(blank=True, help_text='Internal admin notes for dispute/fraud follow-up')
    flagged_for_review = models.BooleanField(default=False, help_text='Flagged by admin for follow-up')
    admin_cancelled_at = models.DateTimeField(null=True, blank=True)
    admin_cancel_reason = models.TextField(blank=True, help_text='Documented reason for admin cancellation (audit trail)')
    admin_cancelled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='admin_cancelled_transactions')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.buyer.username} → {self.seller.username} ({self.listing.title if self.listing else 'Deleted'})"


class TransactionMessage(models.Model):
    """Message exchanged between buyer and seller within a transaction."""
    transaction = models.ForeignKey('Transaction', on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transaction_messages')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender.username}: {self.body[:30]}..."


class Review(models.Model):
    """User review/rating for a seller."""
    RATING_CHOICES = [
        (1, '⭐ Poor'),
        (2, '⭐⭐ Fair'),
        (3, '⭐⭐⭐ Good'),
        (4, '⭐⭐⭐⭐ Very Good'),
        (5, '⭐⭐⭐⭐⭐ Excellent'),
    ]

    reviewer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews_given')
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews_received')
    listing = models.ForeignKey(Listing, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviews')
    transaction = models.OneToOneField(Transaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='review')
    rating = models.IntegerField(choices=RATING_CHOICES, default=5)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['reviewer', 'seller', 'listing']

    def __str__(self):
        return f"{self.reviewer.username} → {self.seller.username} ({self.rating}★)"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update seller's average rating
        if hasattr(self.seller, 'profile'):
            self.seller.profile.update_rating()


class ModerationLog(models.Model):
    """Audit log for admin moderation actions."""
    ACTION_CHOICES = [
        ('hide_forum_post', 'Hide Forum Post'),
        ('restore_forum_post', 'Restore Forum Post'),
        ('hide_forum_reply', 'Hide Forum Reply'),
        ('restore_forum_reply', 'Restore Forum Reply'),
        ('hide_message', 'Hide Message'),
        ('restore_message', 'Restore Message'),
        ('flag_transaction', 'Flag Transaction'),
        ('unflag_transaction', 'Unflag Transaction'),
        ('admin_cancel_transaction', 'Admin Cancel Transaction'),
        ('add_transaction_note', 'Add Transaction Note'),
    ]
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='moderation_actions')
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    target_model = models.CharField(max_length=60, blank=True)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class ProfilePost(models.Model):
    """User posts on their profile - visible to public."""
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_posts')
    content = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.author.username}'s post ({self.created_at.strftime('%Y-%m-%d')})"