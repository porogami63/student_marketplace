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
    EmailTwoFactorCode,
    SchoolIDVerificationRequest,
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


@admin.register(SchoolIDVerificationRequest)
class SchoolIDVerificationRequestAdmin(admin.ModelAdmin):
    list_display = [
        'id_image_thumbnail',
        'profile_user_link',
        'profile_school',
        'profile_tier',
        'status',
        'submitted_at',
        'reviewed_at',
        'reviewed_by',
    ]
    list_filter = ['status', 'submitted_at', 'reviewed_at', 'profile__school']
    search_fields = [
        'profile__user__username',
        'profile__user__email',
        'profile__full_name',
        'profile__school__name',
        'reviewer_notes',
    ]
    readonly_fields = [
        'submitted_at',
        'reviewed_at',
        'reviewed_by',
        'id_image_preview',
        'profile_summary',
        'profile_links',
    ]
    fieldsets = (
        ('Request Status', {'fields': ('profile', 'status', 'reviewer_notes')}),
        ('Submitted School ID', {'fields': ('id_image_preview', 'id_image')}),
        ('Applicant Context', {'fields': ('profile_summary', 'profile_links')}),
        ('Review Metadata', {'fields': ('submitted_at', 'reviewed_at', 'reviewed_by')}),
    )
    actions = ['approve_requests', 'reject_requests']

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('profile__user', 'profile__school', 'reviewed_by')

    @admin.display(description='School ID')
    def id_image_thumbnail(self, obj):
        if not obj.id_image:
            return 'No image'
        return format_html(
            '<a href="{}" target="_blank" rel="noopener"><img src="{}" alt="School ID" style="width:56px;height:56px;object-fit:cover;border-radius:8px;border:1px solid #d1d5db;" /></a>',
            obj.id_image.url,
            obj.id_image.url,
        )

    @admin.display(description='Applicant')
    def profile_user_link(self, obj):
        user = obj.profile.user
        profile_admin_url = reverse('admin:marketplace_profile_change', args=[obj.profile_id])
        public_profile_url = reverse('marketplace:public_profile', kwargs={'username': user.username})
        return format_html(
            '<strong>{}</strong><br><a href="{}">Profile admin</a> · <a href="{}" target="_blank" rel="noopener">Public profile</a>',
            user.username,
            profile_admin_url,
            public_profile_url,
        )

    @admin.display(description='School')
    def profile_school(self, obj):
        school = obj.profile.school
        return school.short_name if school and school.short_name else (school.name if school else 'Not set')

    @admin.display(description='Tier')
    def profile_tier(self, obj):
        return obj.profile.get_verification_tier_display()

    @admin.display(description='School ID Preview')
    def id_image_preview(self, obj):
        if not obj.id_image:
            return 'No image uploaded.'
        return format_html(
            '<a href="{0}" target="_blank" rel="noopener">'
            '<img src="{0}" alt="School ID" style="max-width:420px;width:100%;height:auto;border:1px solid #d1d5db;border-radius:10px;" />'
            '</a><p style="margin-top:8px;"><a href="{0}" target="_blank" rel="noopener">Open full image</a></p>',
            obj.id_image.url,
        )

    @admin.display(description='Profile Summary')
    def profile_summary(self, obj):
        profile = obj.profile
        year = profile.get_year_level_display() if profile.year_level else 'Not set'
        return format_html(
            '<strong>Name:</strong> {}<br>'
            '<strong>Email:</strong> {}<br>'
            '<strong>Phone:</strong> {}<br>'
            '<strong>School:</strong> {}<br>'
            '<strong>Year level:</strong> {}<br>'
            '<strong>Current tier:</strong> {}<br>'
            '<strong>ID submitted:</strong> {}<br>'
            '<strong>ID verified:</strong> {}',
            profile.full_name or 'Not set',
            profile.user.email or 'Not set',
            profile.phone or 'Not set',
            self.profile_school(obj),
            year,
            profile.get_verification_tier_display(),
            'Yes' if profile.id_submitted else 'No',
            'Yes' if profile.id_verified else 'No',
        )

    @admin.display(description='Profile Links')
    def profile_links(self, obj):
        profile_admin_url = reverse('admin:marketplace_profile_change', args=[obj.profile_id])
        public_profile_url = reverse('marketplace:public_profile', kwargs={'username': obj.profile.user.username})
        return format_html(
            '<a href="{}">Open profile in admin</a> · <a href="{}" target="_blank" rel="noopener">Open public profile</a>',
            profile_admin_url,
            public_profile_url,
        )

    @admin.action(description='Approve selected school ID requests')
    def approve_requests(self, request, queryset):
        count = 0
        for req in queryset:
            if req.status == 'approved':
                continue
            req.approve(reviewer=request.user, notes=req.reviewer_notes)
            ModerationLog.objects.create(
                actor=request.user,
                action='approve_school_id',
                target_model='school_id_verification_request',
                target_id=req.pk,
            )
            count += 1

        self.message_user(request, f'{count} request(s) approved.')

    @admin.action(description='Reject selected school ID requests')
    def reject_requests(self, request, queryset):
        count = 0
        for req in queryset:
            if req.status == 'rejected':
                continue
            req.reject(reviewer=request.user, notes=req.reviewer_notes)
            ModerationLog.objects.create(
                actor=request.user,
                action='reject_school_id',
                target_model='school_id_verification_request',
                target_id=req.pk,
            )
            count += 1

        self.message_user(request, f'{count} request(s) rejected.')


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


@admin.register(EmailTwoFactorCode)
class EmailTwoFactorCodeAdmin(admin.ModelAdmin):
    list_display = ['user', 'purpose', 'email', 'created_at', 'expires_at', 'attempts', 'consumed_at']
    list_filter = ['purpose', 'created_at', 'consumed_at']
    search_fields = ['user__username', 'user__email', 'email']
    readonly_fields = ['user', 'purpose', 'email', 'code_hash', 'created_at', 'expires_at', 'attempts', 'consumed_at', 'ip_address']

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['buyer', 'seller', 'listing', 'price', 'status', 'no_show_status', 'created_at']
    list_filter = ['status', 'no_show_status', 'created_at', 'exchange_method']
    search_fields = ['buyer__username', 'seller__username', 'listing__title']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'confirmed_at', 'completed_at', 'admin_cancelled_at', 'no_show_reported_at']
    
    fieldsets = (
        ('Transaction Participants', {'fields': ('buyer', 'seller', 'listing')}),
        ('Transaction Amount', {'fields': ('price', 'quantity', 'unit_price')}),
        ('Status & Timing', {'fields': ('status', 'created_at', 'confirmed_at', 'completed_at'), 'classes': ('collapse',)}),
        ('Meeting Agreement', {'fields': ('exchange_method', 'proposed_meetup_location', 'proposed_meetup_datetime', 'buyer_confirmed_meeting', 'seller_confirmed_meeting')}),
        ('Arrival Confirmation', {'fields': ('buyer_confirmed_arrival', 'buyer_arrival_confirmed_at', 'seller_confirmed_arrival', 'seller_arrival_confirmed_at')}),
        ('No-Show Protection', {'fields': ('no_show_status', 'no_show_reported_by', 'no_show_reported_at', 'no_show_reason', 'no_show_admin_action'), 'classes': ('collapse',)}),
        ('Notes & Admin', {'fields': ('notes', 'seller_notes', 'admin_notes', 'admin_cancel_reason', 'admin_cancelled_by', 'admin_cancelled_at'), 'classes': ('collapse',)}),
        ('Completion & Payment', {'fields': ('buyer_completed', 'seller_completed', 'flagged_for_review'), 'classes': ('collapse',)}),
    )
    
    def save_model(self, request, obj, form, change):
        """Handle receipt generation and vouch notifications when admin completes transaction."""
        # Get the original status before saving
        original_status = None
        if change:  # Only if editing existing object
            try:
                original = Transaction.objects.get(pk=obj.pk)
                original_status = original.status
            except Exception:
                pass
        
        # Save the transaction
        super().save_model(request, obj, form, change)
        
        # If status changed to 'completed', generate receipts and send vouch notifications
        if original_status and original_status != 'completed' and obj.status == 'completed':
            try:
                # Import here to avoid circular imports
                from marketplace.views import _create_receipt
                from django.urls import reverse
                from django.db.models import Q
                
                # Create receipt for both buyer and seller
                receipt = _create_receipt(obj, payment=None)
                
                # Prepare vouch URLs
                buyer_review_url = reverse('marketplace:leave_review', kwargs={'username': obj.seller.username}) + f'?transaction_id={obj.pk}'
                seller_review_url = reverse('marketplace:leave_review', kwargs={'username': obj.buyer.username}) + f'?transaction_id={obj.pk}'
                
                # Notify buyer with vouch link for seller
                Notification.objects.create(
                    user=obj.buyer,
                    related_user=obj.seller,
                    message=f"Transaction verified by admin! Your receipt is ready. Leave a vouch for {obj.seller.username}.",
                    notification_type='transaction',
                    url=buyer_review_url
                )
                
                # Notify seller with vouch link for buyer
                Notification.objects.create(
                    user=obj.seller,
                    related_user=obj.buyer,
                    message=f"Transaction verified by admin! Your receipt is ready. Leave a vouch for {obj.buyer.username}.",
                    notification_type='transaction',
                    url=seller_review_url
                )
            except Exception as e:
                # Log but don't fail the save
                import logging
                logger = logging.getLogger(__name__)
                logger.exception('Error generating receipt/notifications for completed transaction %s', obj.pk)


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
        'moderation_actions_html',
    ]
    fieldsets = (
        ('Actions', {'fields': ('moderation_actions_html',), 'classes': ('collapse', 'expanded')}),
        ('Report', {'fields': ('reporter', 'reported_user', 'reason', 'description', 'priority')}),
        ('Target', {'fields': ('target_link', 'listing_thumbnail_large', 'content_type', 'object_id', 'context_url')}),
        ('Triage', {'fields': ('status', 'resolved_at', 'resolved_by', 'resolution_notes', 'appeal_requested', 'appeal_status', 'appeal_text')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    actions = ['mark_resolved', 'warn_reported_user', 'ban_reported_user', 'remove_reported_listing']

    @admin.action(description="Mark selected reports as resolved")
    def mark_resolved(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(status='resolved', resolved_at=timezone.now(), resolved_by=request.user)
        self.message_user(request, f"{updated} reports successfully marked as resolved.")

    @admin.action(description="Warn the reported user (System Notification)")
    def warn_reported_user(self, request, queryset):
        from .models import Notification
        from django.utils import timezone
        count = 0
        for report in queryset:
            if report.reported_user_id:
                profile = report.reported_user.profile
                profile.strikes_count += 1
                profile.reputation_score -= 10
                profile.save(update_fields=['strikes_count', 'reputation_score'])
                Notification.objects.create(
                    user=report.reported_user,
                    notification_type='system',
                    message=f"WARNING: We received reports regarding your account for '{report.get_reason_display()}'. Your reputation score is now {profile.reputation_score}. Please make sure to follow the marketplace guidelines to avoid account suspension."
                )
                if report.reporter:
                    reporter_msg = f"Thank you for reporting #{report.id}. We have investigated and issued a formal warning to the user. We apologize for any inconvenience."
                    Notification.objects.create(user=report.reporter, notification_type='system', message=reporter_msg)
                report.status = 'resolved'
                report.resolution_notes = "User was sent a warning notification."
                report.resolved_at = timezone.now()
                report.resolved_by = request.user
                report.save(update_fields=['status', 'resolution_notes', 'resolved_at', 'resolved_by'])
                count += 1
        self.message_user(request, f"Issued warnings to {count} users and resolved their reports.")

    @admin.action(description="Ban the reported user (Deactivate)")
    def ban_reported_user(self, request, queryset):
        from django.utils import timezone
        count = 0
        for report in queryset:
            user = report.reported_user
            if user and user.is_active:
                user.is_active = False
                user.save(update_fields=['is_active'])
                if report.reporter:
                    reporter_msg = f"Thank you for reporting #{report.id}. We have permanently banned the offending user. We apologize for the inconvenience and appreciate your help!"
                    Notification.objects.create(user=report.reporter, notification_type='system', message=reporter_msg)
                if report.reporter:
                    reporter_msg = f"Thank you for reporting #{report.id}. We have permanently banned the offending user. We apologize for the inconvenience and appreciate your help!"
                    Notification.objects.create(user=report.reporter, notification_type='system', message=reporter_msg)
                report.status = 'resolved'
                report.resolution_notes = "User was banned (account deactivated)."
                report.resolved_at = timezone.now()
                report.resolved_by = request.user
                report.save(update_fields=['status', 'resolution_notes', 'resolved_at', 'resolved_by'])
                count += 1
        self.message_user(request, f"Banned {count} users and resolved their reports.")

    @admin.action(description="Remove the reported listing")
    def remove_reported_listing(self, request, queryset):
        from django.utils import timezone
        from .models import Listing
        count = 0
        for report in queryset:
            if report.content_type and report.content_type.model == 'listing':
                listing = report.content_object
                if isinstance(listing, Listing):
                    listing.delete()  # Or you can do listing.is_sold=True / a new `is_active=False` field if it exists
                    if report.reporter:
                        reporter_msg = f"Thank you for reporting #{report.id}. We have permanently removed the offending listing. We apologize for the inconvenience and appreciate your help!"
                        Notification.objects.create(user=report.reporter, notification_type='system', message=reporter_msg)
                    if report.reporter:
                        reporter_msg = f"Thank you for reporting #{report.id}. We have permanently removed the offending listing. We apologize for the inconvenience and appreciate your help!"
                        Notification.objects.create(user=report.reporter, notification_type='system', message=reporter_msg)
                    report.status = 'resolved'
                    report.resolution_notes = "Reported listing was removed."
                    report.resolved_at = timezone.now()
                    report.resolved_by = request.user
                    report.save(update_fields=['status', 'resolution_notes', 'resolved_at', 'resolved_by'])
                    count += 1
        self.message_user(request, f"Removed {count} listings and resolved their reports.")

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:object_id>/action/warn/', self.admin_site.admin_view(self.view_warn_user), name='marketplace_userreport_action_warn'),
            path('<int:object_id>/action/ban/', self.admin_site.admin_view(self.view_ban_user), name='marketplace_userreport_action_ban'),
            path('<int:object_id>/action/remove_listing/', self.admin_site.admin_view(self.view_remove_listing), name='marketplace_userreport_action_removelisting'),
        ]
        return custom_urls + urls

    def view_warn_user(self, request, object_id):
        from django.shortcuts import get_object_or_404, redirect
        from django.utils import timezone
        from .models import Notification
        report = get_object_or_404(self.model, pk=object_id)
        if report.reported_user_id:
            profile = report.reported_user.profile
            profile.strikes_count += 1
            profile.reputation_score -= 10
            profile.save(update_fields=['strikes_count', 'reputation_score'])
            msg = f"WARNING: Your account has received a report for '{report.get_reason_display()}'. Your reputation score was decreased to {profile.reputation_score}. You can file an appeal if you believe this is a mistake."
            Notification.objects.create(user=report.reported_user, notification_type='system', message=msg)
            if report.reporter:
                reporter_msg = f"Thank you for reporting #{report.id}. We have investigated and issued a formal warning to the user. We apologize for any inconvenience they caused and appreciate you keeping our community safe!"
                Notification.objects.create(user=report.reporter, notification_type='system', message=reporter_msg)
            report.status = 'resolved'
            report.resolution_notes = "Gave warning via notification. Resolving report."
            report.resolved_at = timezone.now()
            report.resolved_by = request.user
            report.save(update_fields=['status', 'resolution_notes', 'resolved_at', 'resolved_by'])
            self.message_user(request, "Warning sent to user and report marked resolved.")
        return redirect('admin:marketplace_userreport_change', object_id)

    def view_ban_user(self, request, object_id):
        from django.shortcuts import get_object_or_404, redirect
        from django.utils import timezone
        from .models import Notification
        report = get_object_or_404(self.model, pk=object_id)
        if report.reported_user and report.reported_user.is_active:
            report.reported_user.is_active = False
            report.reported_user.save(update_fields=['is_active'])
            msg = f"BANNED: Your account has been banned due to a report for '{report.get_reason_display()}'. You may file an appeal."
            Notification.objects.create(user=report.reported_user, notification_type='system', message=msg)
            if report.reporter:
                reporter_msg = f"Thank you for reporting #{report.id}. We have permanently banned the offending user. We apologize for the inconvenience and appreciate your help in keeping UBXchange secure!"
                Notification.objects.create(user=report.reporter, notification_type='system', message=reporter_msg)
            report.status = 'resolved'
            report.resolution_notes = "User account banned/deactivated. Resolving report."
            report.resolved_at = timezone.now()
            report.resolved_by = request.user
            report.save(update_fields=['status', 'resolution_notes', 'resolved_at', 'resolved_by'])
            self.message_user(request, "User banned and report marked resolved.")
        return redirect('admin:marketplace_userreport_change', object_id)

    def view_remove_listing(self, request, object_id):
        from django.shortcuts import get_object_or_404, redirect
        from django.utils import timezone
        from .models import Listing, Notification
        report = get_object_or_404(self.model, pk=object_id)
        if report.content_type and report.content_type.model == 'listing':
            listing = report.content_object
            if isinstance(listing, Listing):
                seller = listing.seller
                seller_profile = seller.profile
                seller_profile.strikes_count += 1
                seller_profile.reputation_score -= 10
                seller_profile.save(update_fields=['strikes_count', 'reputation_score'])
                msg = f"LISTING REMOVED: Your listing '{listing.title}' was removed due to a violation ('{report.get_reason_display()}'). Your reputation is now {seller_profile.reputation_score}. You may appeal this decision."
                Notification.objects.create(user=seller, notification_type='system', message=msg)
                listing.delete()
                if report.reporter:
                    reporter_msg = f"Thank you for reporting #{report.id}. We have permanently removed the offending listing. We apologize for the inconvenience and appreciate your help in keeping the community safe!"
                    Notification.objects.create(user=report.reporter, notification_type='system', message=reporter_msg)
                report.status = 'resolved'
                report.resolution_notes = "Listing removed. Resolving report."
                report.resolved_at = timezone.now()
                report.resolved_by = request.user
                report.save(update_fields=['status', 'resolution_notes', 'resolved_at', 'resolved_by'])
                self.message_user(request, "Listing successfully deleted and report resolved.")
        return redirect('admin:marketplace_userreport_change', object_id)

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        if change and obj:
            context['custom_actions'] = True
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def moderation_actions_html(self, obj):
        if not obj or not obj.pk:
            return 'Save the report first'
        html = '<div style="display:flex;gap:10px;margin-top:10px;">'
        
        warn_url = reverse('admin:marketplace_userreport_action_warn', args=[obj.pk], current_app=self.admin_site.name)
        ban_url = reverse('admin:marketplace_userreport_action_ban', args=[obj.pk], current_app=self.admin_site.name)
        
        if obj.reported_user_id:
            html += f'<a class="button" style="background-color:#f0ad4e;color:white;" href="{warn_url}">Warn User</a>'
            html += f'<a class="button" style="background-color:#d9534f;color:white;" href="{ban_url}">Ban User</a>'
            
        if obj.content_type and obj.content_type.model == 'listing':
            rem_url = reverse('admin:marketplace_userreport_action_removelisting', args=[obj.pk], current_app=self.admin_site.name)
            html += f'<a class="button" style="background-color:#d9534f;color:white;" href="{rem_url}">Take Down Listing</a>'
            
        html += '</div>'
        return format_html(html)
    moderation_actions_html.short_description = "Quick Actions"

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