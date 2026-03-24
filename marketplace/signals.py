from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in, user_login_failed
from allauth.socialaccount.signals import social_account_updated, pre_social_login
from .models import Message, ForumReply, Notification, Profile, Review
from .security import AuditLog, get_client_ip, record_login_attempt


@receiver(post_save, sender=Message)
def update_conversation_timestamp(sender, instance, created, **kwargs):
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
    user = sociallogin.user
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        profile = Profile.objects.create(user=user)
    
    # Get extra data from Google
    extra_data = sociallogin.account.extra_data
    
    # Update profile fields from Google
    if 'given_name' in extra_data or 'family_name' in extra_data:
        given_name = extra_data.get('given_name', '')
        family_name = extra_data.get('family_name', '')
        profile.full_name = f"{given_name} {family_name}".strip()
    
    # Store Google avatar URL
    if 'picture' in extra_data:
        profile.google_avatar_url = extra_data['picture']
    
    profile.save()
