from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
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
    LISTING_TYPE_CHOICES = [
        ('wts', 'Want to Sell (WTS)'),
        ('wtb', 'Want to Buy (WTB)'),
    ]

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

    listing_type = models.CharField(max_length=10, choices=LISTING_TYPE_CHOICES, default='wts', help_text='Specify if you want to sell or buy an item')
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

    VERIFICATION_TIER_CHOICES = [
        ('grey', 'Grey - Unverified'),
        ('yellow', 'Yellow - Profile Complete'),
        ('green', 'Green - Active Member'),
        ('blue', 'Blue - Highly Trusted'),
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
    vouch_count = models.PositiveIntegerField(default=0, help_text='Number of vouches received')
    verification_tier = models.CharField(max_length=10, choices=VERIFICATION_TIER_CHOICES, default='grey', help_text='Verification tier based on profile completion and activity')
    total_sold = models.PositiveIntegerField(default=0, help_text='Number of items sold')
    total_bought = models.PositiveIntegerField(default=0, help_text='Number of items purchased')
    id_submitted = models.BooleanField(default=False, help_text='Admin approval required for blue tier')
    id_verified = models.BooleanField(default=False, help_text='ID has been verified by admin')
    forum_posts_count = models.PositiveIntegerField(default=0, help_text='Number of forum posts created')
    is_verified = models.BooleanField(default=False, help_text='Kept for backward compatibility')
    pinned_post = models.ForeignKey('ProfilePost', on_delete=models.SET_NULL, null=True, blank=True, related_name='pinned_in_profile', help_text='Featured post on profile')

    def __str__(self):
        return f"{self.user.username}'s profile"

    @property
    def display_name(self):
        return self.full_name or self.user.get_full_name() or self.user.username

    @property
    def average_rating(self):
        """Backward compatibility property - returns vouch count."""
        return self.vouch_count

    @property
    def review_count(self):
        """Backward compatibility property - alias for vouch_count."""
        return self.vouch_count

    def is_profile_complete(self):
        """Check if profile has all required information for yellow tier."""
        return bool(self.full_name and self.school and self.year_level and self.phone and self.address)

    def get_completed_transactions_count(self):
        """Get count of completed transactions as buyer or seller."""
        from django.db.models import Q
        return self.user.purchases.filter(status='completed').count() + self.user.sales.filter(status='completed').count()

    def update_verification_tier(self):
        """Recalculate and update verification tier based on profile activity."""
        completed_transactions = self.get_completed_transactions_count()
        
        # Blue tier: 20+ completed transactions, ID verified by admin
        if self.id_verified and completed_transactions >= 20:
            self.verification_tier = 'blue'
        # Green tier: Active member - forum posts, transactions, and general activity
        elif completed_transactions > 0 and (self.forum_posts_count > 0 or self.vouch_count > 0):
            self.verification_tier = 'green'
        # Yellow tier: Complete profile information
        elif self.is_profile_complete():
            self.verification_tier = 'yellow'
        # Grey tier: Minimal information
        else:
            self.verification_tier = 'grey'
        
        self.save(update_fields=['verification_tier'])

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
        """Backward compatibility method - updates verification tier instead."""
        self.update_verification_tier()

    def get_avatar_url(self):
        """Get the avatar URL for this profile, preferring uploaded avatar over Google avatar."""
        if self.avatar:
            return self.avatar.url
        elif self.google_avatar_url:
            return self.google_avatar_url
        return None


class SocialMedia(models.Model):
    """Social media accounts linked to a user profile."""
    PLATFORM_CHOICES = [
        ('facebook', 'Facebook'),
        ('instagram', 'Instagram'),
        ('twitter', 'Twitter / X'),
        ('discord', 'Discord'),
        ('whatsapp', 'WhatsApp'),
        ('linkedin', 'LinkedIn'),
        ('viber', 'Viber'),
        ('telegram', 'Telegram'),
    ]

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='social_media')
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    handle = models.CharField(max_length=255, help_text='Username, handle, or profile URL')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['profile', 'platform']
        verbose_name_plural = 'Social Media'
        ordering = ['platform']

    def __str__(self):
        return f"{self.profile.user.username} - {self.get_platform_display()}"

    def get_url(self):
        """Generate a clickable URL from the handle."""
        handle = self.handle.strip()
        
        # If already a full URL, return as-is
        if handle.startswith('http://') or handle.startswith('https://'):
            return handle
        
        # Remove leading @ if present
        clean_handle = handle.lstrip('@')
        
        urls = {
            'facebook': f'https://www.facebook.com/{clean_handle}',
            'instagram': f'https://www.instagram.com/{clean_handle}/',
            'twitter': f'https://www.twitter.com/{clean_handle}',
            'linkedin': f'https://www.linkedin.com/in/{clean_handle}' if '/in/' not in clean_handle else f'https://www.linkedin.com/{clean_handle}',
            'discord': f'https://discordapp.com/users/{clean_handle}',
            'whatsapp': f'https://wa.me/{clean_handle.replace("+", "")}',
            'telegram': f'https://t.me/{clean_handle}',
            'viber': f'viber://contact?number={clean_handle}' if clean_handle.startswith('+') else f'viber://chat?number={clean_handle}',
        }
        
        return urls.get(self.platform, '#')


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
    NOTIFICATION_TYPES = [
        ('transaction', 'Transaction Update'),
        ('message', 'New Message'),
        ('offer', 'Offer'),
        ('review', 'Review/Vouch'),
        ('listing', 'Listing Update'),
        ('system', 'System Alert'),
        ('forum', 'Forum Reply'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    related_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='triggered_notifications')
    message = models.CharField(max_length=255)
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='system')
    url = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_notification_type_display()} - {self.message[:50]}"

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
    buyer_confirmed_meeting = models.BooleanField(default=False, help_text='Buyer confirmed attendance at meeting')
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
    """User vouch/endorsement for a seller."""
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews_given')
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews_received')
    listing = models.ForeignKey(Listing, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviews')
    transaction = models.OneToOneField(Transaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='review')
    is_vouch = models.BooleanField(default=True, help_text='True if reviewer vouches for seller')
    comment = models.TextField(blank=True, help_text='Optional feedback from the transaction')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['reviewer', 'seller', 'listing']

    def __str__(self):
        vouch_text = "Vouched" if self.is_vouch else "Not Vouched"
        return f"{self.reviewer.username} → {self.seller.username} ({vouch_text})"

    def save(self, *args, **kwargs):
        # Track if this is a new review and the old is_vouch status
        is_new = self.pk is None
        old_is_vouch = None
        
        if not is_new:
            # Get the original is_vouch value for updates
            try:
                old_review = Review.objects.get(pk=self.pk)
                old_is_vouch = old_review.is_vouch
            except Review.DoesNotExist:
                pass
        
        super().save(*args, **kwargs)
        
        # Update seller's vouch count and verification tier
        if hasattr(self.seller, 'profile'):
            profile = self.seller.profile
            
            # Handle vouch count changes
            if is_new and self.is_vouch:
                # New vouch review
                profile.vouch_count += 1
            elif not is_new and old_is_vouch is not None:
                # Updating existing review
                if not old_is_vouch and self.is_vouch:
                    # Changed from non-vouch to vouch
                    profile.vouch_count += 1
                elif old_is_vouch and not self.is_vouch:
                    # Changed from vouch to non-vouch
                    if profile.vouch_count > 0:
                        profile.vouch_count -= 1
            
            profile.update_verification_tier()
            profile.save()


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


class UserReport(models.Model):
    """User-submitted report about content or another user."""

    REASON_CHOICES = [
        ('fraud', 'Fraud / Scam'),
        ('harassment', 'Harassment / Bullying'),
        ('spam', 'Spam / Advertising'),
        ('unsafe_meetup', 'Unsafe Meetup'),
        ('suspicious', 'Suspicious Activity'),
        ('refund_dispute', 'Refund / Dispute'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('new', 'New'),
        ('reviewing', 'Reviewing'),
        ('resolved', 'Resolved'),
        ('dismissed', 'Dismissed'),
    ]

    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reports_submitted')
    reported_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reports_received')

    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    description = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    priority = models.PositiveSmallIntegerField(default=0, help_text='Higher numbers are higher priority')

    # Generic relation to the reported object (listing/message/forum/transaction/user/etc.)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    context_url = models.CharField(max_length=255, blank=True, help_text='Where the report was submitted from')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reports_resolved')
    resolution_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['reason', 'created_at']),
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f"Report #{self.pk} by {self.reporter.username} ({self.reason})"


class SupportTicket(models.Model):
    """Admin-facing ticket created from a user report."""

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('assigned', 'Assigned'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]

    report = models.OneToOneField(UserReport, on_delete=models.CASCADE, related_name='ticket')
    title = models.CharField(max_length=200)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    priority = models.PositiveSmallIntegerField(default=0)
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_support_tickets',
        limit_choices_to={'is_staff': True},
    )

    internal_notes = models.TextField(blank=True)
    public_response = models.TextField(blank=True, help_text='Optional response summary visible to the reporter')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'priority', 'created_at']),
            models.Index(fields=['assigned_to', 'status']),
        ]

    def __str__(self):
        return f"Ticket #{self.pk} ({self.status})"


class ProfilePost(models.Model):
    """User posts on their profile - visible to public."""
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_posts')
    content = models.TextField(max_length=1000)
    image = models.ImageField(upload_to='profile_posts/', blank=True, null=True, help_text='Optional image for your post (max 5MB)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.author.username}'s post ({self.created_at.strftime('%Y-%m-%d')})"
    
    def comment_count(self):
        """Get count of non-deleted comments on this post."""
        return self.comments.count()


class ProfilePostComment(models.Model):
    """Comments on profile posts - allows interaction on user profiles."""
    post = models.ForeignKey(ProfilePost, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='profile_post_comments')
    content = models.TextField(max_length=500, help_text='Comment text (max 500 chars)')
    image = models.ImageField(upload_to='profile_comments/', blank=True, null=True, help_text='Optional image in comment (max 2MB)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_edited = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['post', 'created_at']),
        ]

    def __str__(self):
        return f"{self.author.username} on {self.post.author.username}'s post"


class Payment(models.Model):
    """Payment record for transactions."""
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('credit_card', 'Credit Card'),
        ('gcash', 'GCash'),
        ('bank_transfer', 'Bank Transfer'),
        ('in_person', 'In-Person Cash'),
        ('other', 'Other Arrangement'),
    ]

    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name='payment')
    stripe_charge_id = models.CharField(max_length=255, unique=True, help_text='Stripe charge or payment intent ID')
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text='Amount paid in PHP')
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES, default='credit_card', help_text='Payment method used')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment {self.stripe_charge_id} - {self.status}"

    def get_payment_method_display(self):
        """Return the display name for the payment method."""
        return dict(self.PAYMENT_METHOD_CHOICES).get(self.payment_method, self.payment_method)


class Receipt(models.Model):
    """Digital receipt for transactions - stored in user's inbox."""
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name='receipt')
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name='receipt', null=True, blank=True)
    receipt_number = models.CharField(max_length=50, unique=True, help_text='Unique receipt ID (e.g., RCP-2024-001)')
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='receipts_received', help_text='Buyer of the item')
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='receipts_issued', help_text='Seller of the item')
    listing_title = models.CharField(max_length=200, help_text='Snapshot of listing title at time of purchase')
    listing_price = models.DecimalField(max_digits=10, decimal_places=2, help_text='Snapshot of price at time of purchase')
    payment_method = models.CharField(max_length=50, help_text='How the item was paid for')
    processing_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text='2% fee for credit card payments')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text='Final amount including fees')
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending - Awaiting seller confirmation'),
            ('confirmed', 'Confirmed - Seller has acknowledged'),
            ('completed', 'Completed - Transaction finished'),
            ('failed', 'Failed - Transaction cancelled'),
        ],
        default='pending'
    )
    notes = models.TextField(blank=True, help_text='Additional buyer notes or special instructions')
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True, help_text='When buyer confirmed receipt')
    completed_at = models.DateTimeField(null=True, blank=True, help_text='When exchange was completed')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Receipt {self.receipt_number} - {self.buyer.username} → {self.seller.username}"

    @property
    def is_recent(self):
        """Check if receipt was created within last 7 days."""
        from datetime import timedelta
        from django.utils import timezone
        return timezone.now() - self.created_at < timedelta(days=7)