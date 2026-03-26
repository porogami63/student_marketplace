from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
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
    UserReport,
    SupportTicket,
    Payment,
    Receipt,
)
from .security import AuditLog, LoginAttempt


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


@admin.register(UserReport)
class UserReportAdmin(admin.ModelAdmin):
    list_display = [
        'listing_thumbnail',
        'id',
        'created_at',
        'status',
        'reason',
        'priority',
        'reporter',
        'reported_user',
        'target_link',
    ]
    list_filter = ['status', 'reason', 'priority', 'created_at']
    search_fields = ['reporter__username', 'reported_user__username', 'description']
    date_hierarchy = 'created_at'
    readonly_fields = [
        'created_at',
        'updated_at',
        'content_type',
        'object_id',
        'reporter',
        'target_link',
        'listing_thumbnail_large',
    ]
    fieldsets = (
        ('Report', {'fields': ('reporter', 'reported_user', 'reason', 'description', 'priority')}),
        ('Target', {'fields': ('target_link', 'listing_thumbnail_large', 'content_type', 'object_id', 'context_url')}),
        ('Triage', {'fields': ('status', 'resolved_at', 'resolved_by', 'resolution_notes')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

    def target_link(self, obj):
        """Link to the reported object inside the same admin site."""
        if not obj.content_type_id or not obj.object_id:
            return '—'
        try:
            url = reverse(
                f"admin:{obj.content_type.app_label}_{obj.content_type.model}_change",
                args=[obj.object_id],
                current_app=self.admin_site.name,
            )
            label = f"{obj.content_type.model.replace('_', ' ').title()} #{obj.object_id}"
            return format_html('<a href="{}">{}</a>', url, label)
        except Exception:
            return f"{obj.content_type} #{obj.object_id}"

    target_link.short_description = 'Target'

    def _listing_image_url(self, obj):
        try:
            if obj.content_type and obj.content_type.model == 'listing':
                target = obj.content_object
                if target and getattr(target, 'image', None):
                    return target.image.url
        except Exception:
            return ''
        return ''

    def listing_thumbnail(self, obj):
        url = self._listing_image_url(obj)
        if not url:
            return '—'
        return format_html(
            '<img src="{}" style="width:44px;height:44px;object-fit:cover;border-radius:8px;border:1px solid #e5e7eb;" />',
            url,
        )

    listing_thumbnail.short_description = 'Image'

    def listing_thumbnail_large(self, obj):
        url = self._listing_image_url(obj)
        if not url:
            return '—'
        return format_html(
            '<img src="{}" style="max-width:420px;width:100%;height:auto;object-fit:cover;border-radius:12px;border:1px solid #e5e7eb;" />',
            url,
        )

    listing_thumbnail_large.short_description = 'Listing Image'


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = [
        'listing_thumbnail',
        'id',
        'created_at',
        'status',
        'priority',
        'assigned_to',
        'report_reason',
        'reporter',
        'title',
    ]
    list_filter = ['status', 'priority', 'assigned_to', 'created_at']
    search_fields = ['title', 'internal_notes', 'public_response', 'report__reporter__username']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'updated_at', 'resolved_at', 'report_link', 'listing_thumbnail_large']
    fieldsets = (
        ('Ticket', {'fields': ('title', 'status', 'priority', 'assigned_to')}),
        ('Linked Report', {'fields': ('report_link', 'listing_thumbnail_large', 'report')}),
        ('Notes', {'fields': ('internal_notes', 'public_response')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at', 'resolved_at')}),
    )

    def report_reason(self, obj):
        try:
            return obj.report.get_reason_display()
        except Exception:
            return '—'

    report_reason.short_description = 'Reason'

    def reporter(self, obj):
        try:
            return obj.report.reporter
        except Exception:
            return '—'

    reporter.short_description = 'Reporter'

    def report_link(self, obj):
        if not obj.report_id:
            return '—'
        try:
            url = reverse(
                'admin:marketplace_userreport_change',
                args=[obj.report_id],
                current_app=self.admin_site.name,
            )
            return format_html('<a href="{}">Report #{}</a>', url, obj.report_id)
        except Exception:
            return f"Report #{obj.report_id}"

    report_link.short_description = 'Report'

    def _listing_image_url(self, obj):
        try:
            report = obj.report
            if report and report.content_type and report.content_type.model == 'listing':
                target = report.content_object
                if target and getattr(target, 'image', None):
                    return target.image.url
        except Exception:
            return ''
        return ''

    def listing_thumbnail(self, obj):
        url = self._listing_image_url(obj)
        if not url:
            return '—'
        return format_html(
            '<img src="{}" style="width:44px;height:44px;object-fit:cover;border-radius:8px;border:1px solid #e5e7eb;" />',
            url,
        )

    listing_thumbnail.short_description = 'Image'

    def listing_thumbnail_large(self, obj):
        url = self._listing_image_url(obj)
        if not url:
            return '—'
        return format_html(
            '<img src="{}" style="max-width:420px;width:100%;height:auto;object-fit:cover;border-radius:12px;border:1px solid #e5e7eb;" />',
            url,
        )

    listing_thumbnail_large.short_description = 'Listing Image'


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


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ['receipt_number', 'buyer', 'seller', 'listing_title', 'total_amount', 'status', 'created_at']
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = ['receipt_number', 'buyer__username', 'seller__username', 'listing_title']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'confirmed_at', 'completed_at']
    fieldsets = (
        ('Receipt Information', {'fields': ('receipt_number', 'transaction', 'payment')}),
        ('Parties Involved', {'fields': ('buyer', 'seller')}),
        ('Item & Pricing', {'fields': ('listing_title', 'listing_price', 'payment_method', 'processing_fee', 'total_amount')}),
        ('Status & Notes', {'fields': ('status', 'notes')}),
        ('Timestamps', {'fields': ('created_at', 'confirmed_at', 'completed_at'), 'classes': ('collapse',)}),
    )


# ============================================================================
# SECURITY & COMPLIANCE ADMIN CLASSES
# ============================================================================

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Admin interface for security audit logs (FERPA, PCI DSS, NIST, ISO 27001)"""
    
    list_display = ['timestamp', 'event_type_badge', 'severity_badge', 'user', 'ip_address', 'resource']
    list_filter = ['event_type', 'severity', 'timestamp']
    search_fields = ['user__username', 'ip_address', 'resource']
    date_hierarchy = 'timestamp'
    readonly_fields = ['timestamp', 'event_type', 'severity', 'user', 'ip_address', 'user_agent', 'resource', 'details_formatted']
    
    fieldsets = (
        ('Security Event', {
            'fields': ('event_type', 'severity_badge', 'timestamp')
        }),
        ('User Information', {
            'fields': ('user', 'ip_address', 'user_agent')
        }),
        ('Resource Accessed', {
            'fields': ('resource', 'details_formatted')
        }),
    )
    
    def event_type_badge(self, obj):
        """Display event type with color coding"""
        colors = {
            'login_success': '#28a745',
            'login_failure': '#dc3545',
            'unauthorized_access': '#fd7e14',
            'data_access': '#0275d8',
            'payment_processed': '#20c997',
            'security_alert': '#e74c3c',
        }
        color = colors.get(obj.event_type, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            obj.get_event_type_display()
        )
    event_type_badge.short_description = 'Event Type'
    
    def severity_badge(self, obj):
        """Display severity level with color coding"""
        colors = {
            'info': '#0275d8',
            'warning': '#ffc107',
            'error': '#dc3545',
            'critical': '#a82833',
        }
        color = colors.get(obj.severity, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            obj.get_severity_display()
        )
    severity_badge.short_description = 'Severity'
    
    def details_formatted(self, obj):
        """Display JSON details in a readable format"""
        import json
        try:
            return format_html(
                '<pre style="background-color: #f5f5f5; padding: 10px; border-radius: 3px; max-height: 300px; overflow: auto;">{}</pre>',
                json.dumps(obj.details, indent=2)
            )
        except:
            return format_html('<pre>{}</pre>', str(obj.details))
    details_formatted.short_description = 'Event Details'
    
    def has_add_permission(self, request):
        """Prevent manual creation of audit logs"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of audit logs"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Allow viewing only"""
        return True


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    """Admin interface for login attempt tracking (Account Lockout - NIST AC-7)"""
    
    list_display = ['attempt_time', 'user', 'status_badge', 'ip_address']
    list_filter = ['success', 'attempt_time']
    search_fields = ['user__username', 'ip_address']
    date_hierarchy = 'attempt_time'
    readonly_fields = ['user', 'ip_address', 'success', 'attempt_time']
    
    fieldsets = (
        ('Login Attempt Details', {
            'fields': ('user', 'status_badge', 'attempt_time')
        }),
        ('Connection Information', {
            'fields': ('ip_address',)
        }),
    )
    
    def status_badge(self, obj):
        """Display login status with color coding"""
        if obj.success:
            return format_html(
                '<span style="background-color: #28a745; color: white; padding: 3px 8px; border-radius: 3px;">✓ Success</span>'
            )
        else:
            return format_html(
                '<span style="background-color: #dc3545; color: white; padding: 3px 8px; border-radius: 3px;">✗ Failed</span>'
            )
    status_badge.short_description = 'Login Status'
    
    def has_add_permission(self, request):
        """Prevent manual creation of login attempts"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of login attempts"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Allow viewing only"""
        return True