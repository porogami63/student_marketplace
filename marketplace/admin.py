from django.contrib import admin
from .models import (
    School,
    Category,
    Listing,
    Profile,
    SocialMedia,
    Favorite,
    Conversation,
    ConversationParticipant,
    Message,
    ForumPost,
    ForumReply,
    Notification,
    Review,
    Transaction,
    ModerationLog,
    Payment,
)


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ['name', 'short_name', 'logo_url']
    fieldsets = (
        ('School info', {'fields': ('name', 'short_name')}),
        ('Branding', {'fields': ('logo_url', 'primary_color', 'secondary_color')}),
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ['title', 'price', 'listing_type', 'category', 'seller', 'school', 'is_sold', 'created_at']
    list_filter = ['listing_type', 'category', 'condition', 'is_sold', 'school']
    search_fields = ['title', 'description']
    date_hierarchy = 'created_at'


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'full_name', 'verification_tier', 'vouch_count', 'total_sold', 'total_bought']
    list_filter = ['verification_tier', 'id_verified', 'school']
    search_fields = ['user__username', 'full_name', 'user__email']
    fieldsets = (
        ('User Account', {'fields': ('user',)}),
        ('Personal Information', {'fields': ('full_name', 'age', 'birthday', 'phone', 'address', 'bio')}),
        ('School & Academic', {'fields': ('school', 'year_level')}),
        ('Contact & Social', {'fields': ('contact_info',)}),
        ('Media', {'fields': ('avatar', 'header_image', 'google_avatar_url')}),
        ('Verification & Trust', {
            'fields': ('verification_tier', 'vouch_count', 'id_submitted', 'id_verified', 'forum_posts_count'),
            'description': 'Verification tier is automatically updated based on profile completion and activity'
        }),
        ('Activity', {'fields': ('total_sold', 'total_bought')}),
        ('Other', {'fields': ('pinned_post', 'is_verified')}),
    )
    readonly_fields = ['vouch_count', 'total_sold', 'total_bought', 'forum_posts_count']


@admin.register(SocialMedia)
class SocialMediaAdmin(admin.ModelAdmin):
    list_display = ['profile', 'platform', 'handle', 'created_at']
    list_filter = ['platform', 'created_at']
    search_fields = ['profile__user__username', 'handle']
    read_only_fields = ['created_at', 'updated_at']


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ['user', 'listing', 'created_at']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['sender', 'conversation', 'created_at']


@admin.register(ForumPost)
class ForumPostAdmin(admin.ModelAdmin):
    list_display = ['title', 'author', 'listing', 'created_at']


@admin.register(ForumReply)
class ForumReplyAdmin(admin.ModelAdmin):
    list_display = ['post', 'author', 'created_at']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'message', 'is_read', 'created_at']
    list_filter = ['is_read', 'created_at']

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['buyer', 'seller', 'listing', 'price', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['buyer__username', 'seller__username']
    date_hierarchy = 'created_at'


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['reviewer', 'seller', 'is_vouch', 'created_at']
    list_filter = ['is_vouch', 'created_at']
    search_fields = ['reviewer__username', 'seller__username', 'comment']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Vouch Details', {'fields': ('reviewer', 'seller', 'is_vouch')}),
        ('Transaction & Listing', {'fields': ('transaction', 'listing')}),
        ('Feedback', {'fields': ('comment',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )


@admin.register(ModerationLog)
class ModerationLogAdmin(admin.ModelAdmin):
    list_display = ['actor', 'action', 'target_model', 'target_id', 'created_at']
    list_filter = ['action', 'created_at']
    search_fields = ['actor__username']
    date_hierarchy = 'created_at'
    readonly_fields = ['actor', 'action', 'target_model', 'target_id', 'created_at']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['stripe_charge_id', 'transaction', 'amount', 'status', 'payment_method', 'created_at']
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = ['stripe_charge_id', 'transaction__buyer__username', 'transaction__seller__username']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Payment Identification', {'fields': ('stripe_charge_id', 'transaction')}),
        ('Payment Details', {'fields': ('amount', 'status', 'payment_method')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )