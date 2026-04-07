from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in, user_login_failed
from allauth.socialaccount.signals import social_account_updated, pre_social_login
import logging
from .models import Message, ForumReply, Notification, Profile, Review
from .security import AuditLog, get_client_ip, record_login_attempt


logger = logging.getLogger(__name__)


@receiver(post_save, sender=Message)
def update_conversation_timestamp(sender, instance, created, **kwargs):
    if kwargs.get('raw', False):
        return
    if created:
        conversation = instance.conversation
        conversation.save()  # triggers auto_now on updated_at

        # Notify other participants about a new message
        sender_user = instance.sender
        for participant in conversation.participants.exclude(pk=sender_user.pk):
            Notification.objects.create(
                user=participant,
                related_user=sender_user,
                message=f"New message from {sender_user.username}",
                notification_type='message',
                url=reverse('marketplace:conversation', args=[conversation.pk]),
            )


@receiver(post_save, sender=Review)
def notify_seller_on_review(sender, instance, created, **kwargs):
    """Notify seller when they receive a new review/vouch (but not their own reviews)."""
    if kwargs.get('raw', False):
        return
    if created:
        # Only notify if it's a new review and not a self-review
        if instance.reviewer_id != instance.seller_id:
            vouch_text = "Vouched for you" if instance.is_vouch else "Posted feedback"
            Notification.objects.create(
                user=instance.seller,
                related_user=instance.reviewer,
                message=f"New review from {instance.reviewer.username}: {vouch_text}",
                notification_type='review',
                url=reverse('marketplace:public_profile', args=[instance.reviewer.username]),
            )


@receiver(post_save, sender=ForumReply)
def notify_forum_reply(sender, instance, created, **kwargs):
    if kwargs.get('raw', False):
        return
    if not created:
        return
    post = instance.post
    # Notify the original post author, but not when they reply to themselves
    if instance.author_id != post.author_id:
        Notification.objects.create(
            user=post.author,
            related_user=instance.author,
            message=f"New reply from {instance.author.username} on your forum post \"{post.title}\"",
            notification_type='forum',
            url=reverse('marketplace:forum_post', args=[post.pk]),
        )


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Automatically create a profile when a new user is created."""
    # During fixture loading (loaddata), Django saves models with raw=True.
    # Avoid creating related rows that the fixture will also provide.
    if kwargs.get('raw', False):
        return
    if created:
        Profile.objects.get_or_create(user=instance)


@receiver(user_logged_in)
def record_successful_login(sender, request, user, **kwargs):
    """Record successful logins for the backoffice Security Overview."""
    try:
        ip_address = get_client_ip(request)
        record_login_attempt(user=user, ip_address=ip_address, success=True)
    except Exception:
        # Never block login due to audit telemetry.
        pass


@receiver(user_login_failed)
def record_failed_login(sender, credentials, request, **kwargs):
    """Record failed logins (best effort)."""
    if request is None:
        return

    try:
        ip_address = get_client_ip(request)
        attempted = (credentials or {}).get('username') or (credentials or {}).get('email') or ''

        matched_user = None
        if attempted:
            matched_user = User.objects.filter(username=attempted).first() or User.objects.filter(email=attempted).first()

        if matched_user is not None:
            record_login_attempt(user=matched_user, ip_address=ip_address, success=False)
        else:
            # Still create an audit log even if the user doesn't exist.
            AuditLog.objects.create(
                event_type='login_failure',
                severity='warning',
                user=None,
                ip_address=ip_address,
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                resource=request.path,
                details={'attempted_username': attempted},
            )
    except Exception:
        # Never block authentication due to audit telemetry.
        pass


@receiver(social_account_updated)
def update_profile_from_google(sender, request, sociallogin, **kwargs):
    """Update user profile with Google account information."""
    try:
        user = sociallogin.user
        profile, _ = Profile.objects.get_or_create(user=user)

        extra_data = getattr(sociallogin.account, 'extra_data', {}) or {}
        update_fields = []

        if 'given_name' in extra_data or 'family_name' in extra_data:
            given_name = (extra_data.get('given_name') or '').strip()
            family_name = (extra_data.get('family_name') or '').strip()
            full_name = f"{given_name} {family_name}".strip()
            if full_name:
                max_len = Profile._meta.get_field('full_name').max_length
                profile.full_name = full_name[:max_len] if max_len else full_name
                update_fields.append('full_name')

        picture = (extra_data.get('picture') or '').strip()
        if picture:
            max_len = Profile._meta.get_field('google_avatar_url').max_length
            profile.google_avatar_url = picture[:max_len] if max_len else picture
            update_fields.append('google_avatar_url')

        if update_fields:
            profile.save(update_fields=update_fields)
    except Exception:
        # Profile synchronization should never break social authentication.
        logger.exception(
            'Non-fatal profile sync failure during social_account_updated for user_id=%s',
            getattr(getattr(sociallogin, 'user', None), 'pk', None),
        )
