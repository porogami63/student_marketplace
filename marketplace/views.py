import logging
import io
import re
import hashlib
from collections import deque
from pathlib import Path
from urllib.parse import urlparse
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from allauth.account.models import EmailAddress
from django.core.management import call_command
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.db import transaction as db_transaction

logger = logging.getLogger(__name__)
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse
from django.http import HttpResponseForbidden
import json
from datetime import datetime, timedelta
from django.db.models import Q, Count, Sum
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from .models import (
    Listing,
    Category,
    School,
    Profile,
    Favorite,
    Conversation,
    ConversationParticipant,
    Message,
    ForumPost,
    ForumReply,
    Notification,
    Review,
    Transaction,
    TransactionMessage,
    ModerationLog,
    UserReport,
    SupportTicket,
    ProfilePost,
    ProfilePostComment,
    SocialMedia,
    Payment,
    Receipt,
    StateTransitionAuditLog,
    SchoolIDVerificationRequest,
)
from .forms import (
    CustomUserCreationForm,
    ProfileRegistrationForm,
    ListingForm,
    ProfileForm,
    MessageForm,
    ForumPostForm,
    ForumReplyForm,
    PurchaseForm,
    TransactionConfirmForm,
    ProfilePostForm,
    ProfilePostCommentForm,
    ReportForm,
    SchoolIDVerificationRequestForm,
)
from .utils import get_similar_listings_price_stats
from .security import rate_limit, AuditLog, get_client_ip
from .security_testing import build_security_test_context, run_active_security_check
from .email_2fa import is_sensitive_recent, set_next_url
import stripe
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

_STATIC_PREFIX = settings.STATIC_URL
if not _STATIC_PREFIX.startswith('/'):
    _STATIC_PREFIX = f'/{_STATIC_PREFIX}'
if not _STATIC_PREFIX.endswith('/'):
    _STATIC_PREFIX += '/'

HERO_IMAGE_URLS = [
    f"{_STATIC_PREFIX}media/hero/image-crossing.jpg",
    f"{_STATIC_PREFIX}media/hero/ubelt-mendiola-arch.jpg",
    f"{_STATIC_PREFIX}media/hero/ubelt-campus-park.jpg",
]

CATEGORY_OVERVIEW = [
    ('textbooks', 'Textbooks', 'Save money on course materials'),
    ('electronics', 'Electronics', 'Laptops, phones, and gadgets'),
    ('clothing-uniforms', 'Clothing & Uniforms', 'PE uniforms, lab coats, and more'),
    ('school-supplies', 'School Supplies', 'Pens, notebooks, and supplies'),
    ('dorm-living', 'Dorm & Living', 'Furniture, lamps, and storage'),
    ('study-materials', 'Study Materials', 'Lecture notes & study guides'),
]

SUGGESTED_MEETUP_POINTS = {
    'UST': ['Q-Pavilion (Inside España)', 'España Gate 2', 'P. Noval Gate', 'Dapitan Gate'],
    'FEU': ['Gate 4 (Morayta)', 'Grandstand/Square', 'Paredes St. Entrance'],
    'UE': ['Lualhati Square', 'Gastambide Gate', 'S.H. Loyala Entrance'],
    'NU': ['NU Main Lobby', 'Jocson St. Entrance'],
    'Public': ['LRT-2 Legarda Station', 'SM San Lazaro (Main Entrance)', 'Isetann Recto', 'LRT-2 Recto Station'],
}


def _get_allowed_payment_methods(listing):
    """Return normalized allowed payment methods for a listing."""
    valid_codes = {choice[0] for choice in Listing.PREFERRED_PAYMENT_CHOICES}
    default_codes = [code for code, _ in Listing.PREFERRED_PAYMENT_CHOICES]

    if not listing:
        return default_codes

    configured = listing.preferred_payment_methods or []
    allowed = [code for code in configured if code in valid_codes]
    return allowed or default_codes


def _tail_text_file(file_path, limit=30):
    """Return the last non-empty lines from a text file, safely.

    This is used to surface live Render-side logs in moderator views when the
    hosted platform does not expose its own log console.
    """
    try:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return []

        lines = deque(path.read_text(encoding='utf-8', errors='replace').splitlines(), maxlen=max(1, int(limit)))
        return [line for line in lines if line.strip()]
    except Exception:
        logger.exception('Failed to tail log file path=%s', file_path)
        return []


@login_required
@rate_limit(max_attempts_per_period=5, period_seconds=60)
def report_create(request, target, pk):
    """Submit a user report about an allowed target object.

    Creates a linked SupportTicket for admin triage.
    """

    allowed_targets = {
        'user': User,
        'listing': Listing,
        'message': Message,
        'forum_post': ForumPost,
        'forum_reply': ForumReply,
        'transaction': Transaction,
    }

    model = allowed_targets.get(target)
    if model is None:
        messages.error(request, 'Invalid report target.')
        return redirect('marketplace:home')

    obj = get_object_or_404(model, pk=pk)

    # Basic permission checks for private objects
    if isinstance(obj, Message):
        if not request.user.is_superuser and not obj.conversation.participants.filter(pk=request.user.pk).exists():
            return HttpResponseForbidden('You do not have permission to report this message.')
    if isinstance(obj, Transaction):
        if not request.user.is_superuser and request.user not in (obj.buyer, obj.seller):
            return HttpResponseForbidden('You do not have permission to report this transaction.')
    if isinstance(obj, User) and obj.pk == request.user.pk:
        messages.error(request, "You can't report your own account.")
        return redirect('marketplace:home')

    if request.method == 'POST':
        form = ReportForm(request.POST)
        if form.is_valid():
            content_type = ContentType.objects.get_for_model(obj.__class__)

            # Lightweight de-dupe: one open report per reporter/target in last 24h
            recent_open_exists = UserReport.objects.filter(
                reporter=request.user,
                content_type=content_type,
                object_id=obj.pk,
                status__in=['new', 'reviewing'],
                created_at__gte=timezone.now() - timedelta(hours=24),
            ).exists()
            if recent_open_exists:
                messages.error(request, 'You already submitted a report for this item recently.')
            else:
                report = form.save(commit=False)
                report.reporter = request.user
                report.content_type = content_type
                report.object_id = obj.pk
                report.context_url = (request.POST.get('context_url') or request.META.get('HTTP_REFERER') or '')[:255]

                # Best-effort reported_user extraction for triage
                if isinstance(obj, User):
                    report.reported_user = obj
                elif isinstance(obj, Listing):
                    report.reported_user = obj.seller
                elif isinstance(obj, Message):
                    report.reported_user = obj.sender
                elif isinstance(obj, ForumPost):
                    report.reported_user = obj.author
                elif isinstance(obj, ForumReply):
                    report.reported_user = obj.author
                elif isinstance(obj, Transaction):
                    report.reported_user = obj.seller

                # Priority mapping
                priority_map = {
                    'unsafe_meetup': 3,
                    'fraud': 3,
                    'harassment': 2,
                    'suspicious': 2,
                    'refund_dispute': 1,
                    'spam': 1,
                    'other': 0,
                }
                report.priority = priority_map.get(report.reason, 0)
                report.save()

                ticket_title = f"{report.get_reason_display()} — {target.replace('_', ' ').title()} #{obj.pk}"
                SupportTicket.objects.create(
                    report=report,
                    title=ticket_title[:200],
                    priority=report.priority,
                )

                # Notify superusers (uses existing notification system)
                admin_users = User.objects.filter(is_superuser=True)
                # Use the custom admin site namespace when present (Render deploy uses /admin/ -> security_admin_site).
                notify_url = ''
                for current_app in ('security_admin', None):
                    try:
                        notify_url = reverse('admin:marketplace_userreport_change', args=[report.pk], current_app=current_app)
                        break
                    except Exception:
                        continue
                if not notify_url:
                    notify_url = f"/admin/marketplace/userreport/{report.pk}/change/"
                for admin_user in admin_users:
                    Notification.objects.create(
                        user=admin_user,
                        related_user=request.user,
                        message=f"New report: {ticket_title}",
                        notification_type='system',
                        url=notify_url,
                    )

                messages.success(request, 'Report submitted. Our admins will review it soon.')

                # Redirect back to the most relevant page
                if hasattr(obj, 'get_absolute_url'):
                    return redirect(obj.get_absolute_url())
                return redirect('marketplace:home')
    else:
        form = ReportForm()

    return render(request, 'marketplace/report_form.html', {
        'form': form,
        'target': target,
        'object': obj,
        'buyer_remorse_notice': "Buyer’s remorse is not a valid refund reason. Use ‘Refund / Dispute’ only for issues like misrepresentation, damage, non-delivery, or unsafe behavior.",
    })


def _get_listing_context(request):
    listings = Listing.objects.filter(is_sold=False).select_related(
        'category', 'seller', 'school', 'seller__profile'
    ).annotate(fav_count=Count('favorited_by'))

    q = request.GET.get('q', '').strip()
    if q:
        listings = listings.filter(
            Q(title__icontains=q) | 
            Q(description__icontains=q) |
            Q(category__name__icontains=q) |
            Q(school__name__icontains=q) |
            Q(school__short_name__icontains=q) |
            Q(product_details__author__icontains=q) |
            Q(product_details__brand__icontains=q) |
            Q(product_details__course_code__icontains=q) |
            Q(product_details__icontains=q)
        )

    category_slug = request.GET.get('category')
    if category_slug:
        listings = listings.filter(category__slug=category_slug)

    school_id = request.GET.get('school')
    if school_id and school_id.isdigit():
        listings = listings.filter(school_id=school_id)

    min_price = request.GET.get('min_price')
    if min_price and min_price.isdigit():
        listings = listings.filter(price__gte=min_price)

    max_price = request.GET.get('max_price')
    if max_price and max_price.isdigit():
        listings = listings.filter(price__lte=max_price)

    condition = request.GET.get('condition')
    if condition:
        listings = listings.filter(condition=condition)

    meetup_location = (request.GET.get('meetup_location') or request.GET.get('campus') or '').strip()
    if meetup_location:
        listings = listings.filter(campus=meetup_location)

    brand = request.GET.get('brand')
    if brand:
        listings = listings.filter(product_details__brand__icontains=brand)

    size = request.GET.get('size')
    if size:
        listings = listings.filter(product_details__size__iexact=size)

    author = request.GET.get('author')
    if author:
        listings = listings.filter(product_details__author__icontains=author)

    attribute = request.GET.get('attribute')
    if attribute:
        # Search across all values in the JSON field
        # This is a bit trickier in SQLite but we can use icontains on the whole JSON field as a string
        # or just check common fields.
        listings = listings.filter(
            Q(product_details__icontains=attribute)
        )

    sort = request.GET.get('sort', 'newest')
    if sort == 'price_low':
        listings = listings.order_by('price')
    elif sort == 'price_high':
        listings = listings.order_by('-price')
    elif sort == 'popular':
        listings = listings.order_by('-view_count')
    else:
        listings = listings.order_by('-created_at')

    categories = Category.objects.all()
    schools = School.objects.all()
    
    # Check if any filters are active
    filters_active = any([
        q, category_slug, school_id, min_price, max_price, 
        condition, meetup_location, brand, size, author, attribute
    ])
    
    newly_listed = list(listings[:12]) if not filters_active else []
    
    # Improved trending info
    trending = []
    if categories.exists():
        for c in categories[:8]:
            trending.append({'name': c.name, 'slug': c.slug})
    else:
        for t in ['textbooks', 'laptop', 'phone', 'furniture', 'notes']:
            trending.append({'name': t})

    category_cards = []
    listing_with_image = Listing.objects.filter(is_sold=False, image__isnull=False).exclude(image='')
    for slug, title, subtitle in CATEGORY_OVERVIEW:
        card_listing = listing_with_image.filter(category__slug=slug).order_by('-created_at').first()
        category_cards.append({
            'slug': slug,
            'name': title,
            'subtitle': subtitle,
            'image_field': card_listing.image if card_listing and card_listing.image else None,
        })

    forum_posts = ForumPost.objects.filter(is_hidden=False).select_related('author', 'listing')[:3]

    return {
        'listings': listings,
        'newly_listed': newly_listed,
        'categories': categories,
        'schools': schools,
        'condition_choices': Listing.CONDITION_CHOICES,
        'campus_choices': Listing.CAMPUS_CHOICES,
        'meetup_location_choices': Listing.CAMPUS_CHOICES,
        'query': q,
        'selected_category': category_slug,
        'selected_school': school_id,
        'min_price': min_price or '',
        'max_price': max_price or '',
        'condition': condition or '',
        'campus': meetup_location,
        'meetup_location': meetup_location,
        'brand': brand or '',
        'size': size or '',
        'author': author or '',
        'attribute': attribute or '',
        'sort': sort,
        'trending': trending,
        'hero_images': HERO_IMAGE_URLS,
        'category_cards': category_cards,
        'forum_posts': forum_posts,
    }


def _get_recommended_for_user(user, limit=8):
    """Get recommended listings based on user's favorite categories and schools."""
    if not user.is_authenticated:
        return []
    
    # Get user's favorite listings
    favorites = Favorite.objects.filter(user=user).select_related('listing__category', 'listing__school').values_list('listing', flat=True)
    
    if not favorites:
        return []
    
    # Extract categories and schools from favorites
    favorite_listings = Listing.objects.filter(pk__in=favorites).values_list('category_id', 'school_id')
    categories = set()
    schools = set()
    for cat_id, school_id in favorite_listings:
        if cat_id:
            categories.add(cat_id)
        if school_id:
            schools.add(school_id)
    
    # Find recommendations from same categories or schools (excluding already favorited)
    recommendations = Listing.objects.filter(
        is_sold=False
    ).exclude(
        pk__in=favorites
    ).select_related(
        'category', 'seller', 'school', 'seller__profile'
    ).annotate(
        fav_count=Count('favorited_by')
    )
    
    # Prioritize by categories and schools
    from django.db.models import Q, Case, When, IntegerField
    recommendations = recommendations.filter(
        Q(category_id__in=categories) | Q(school_id__in=schools)
    )
    
    # Order by category match, then recency
    recommendations = recommendations.annotate(
        category_match=Case(
            When(category_id__in=categories, then=2),
            default=1,
            output_field=IntegerField()
        )
    ).order_by('-category_match', '-created_at')
    
    return list(recommendations[:limit])


def home(request):
    """Homepage with hero and safety banner."""
    context = _get_listing_context(request)
    # Add recommended listings for authenticated users
    if request.user.is_authenticated:
        context['recommended_listings'] = _get_recommended_for_user(request.user)
    return render(request, 'marketplace/home.html', context)


def listing_list(request):
    """Browse all listings with search and filters."""
    context = _get_listing_context(request)
    return render(request, 'marketplace/listing_list.html', context)


def listing_detail(request, pk):
    """View a single listing."""
    listing = get_object_or_404(Listing.objects.select_related(
        'category', 'seller', 'school'
    ), pk=pk)

    # Ensure seller has profile for display
    seller_profile, _ = Profile.objects.get_or_create(user=listing.seller)

    # Increment view count
    listing.view_count += 1
    listing.save(update_fields=['view_count'])

    # Seller's other active listings
    other_listings = Listing.objects.filter(seller=listing.seller, is_sold=False).exclude(pk=pk).select_related('category', 'school')[:4]

    # Related listings from same category (but different seller)
    related_listings = Listing.objects.filter(
        category=listing.category, is_sold=False
    ).exclude(pk=pk).exclude(seller=listing.seller).select_related('category', 'school', 'seller')[:6]

    is_favorited = False
    if request.user.is_authenticated:
        is_favorited = Favorite.objects.filter(user=request.user, listing=listing).exists()

    # Price statistics for similar items
    price_stats = get_similar_listings_price_stats(listing)

    return render(request, 'marketplace/listing_detail.html', {
        'listing': listing,
        'seller_profile': seller_profile,
        'other_listings': other_listings,
        'related_listings': related_listings,
        'is_favorited': is_favorited,
        'price_stats': price_stats,
    })


def register(request):
    """User registration with extended profile information."""
    if request.user.is_authenticated:
        return redirect('marketplace:home')

    if request.method == 'POST':
        user_form = CustomUserCreationForm(request.POST)
        profile_form = ProfileRegistrationForm(request.POST)
        
        if user_form.is_valid() and profile_form.is_valid():
            # Create user
            user = user_form.save()

            normalized_email = (user.email or '').strip().lower()
            if user.email != normalized_email:
                user.email = normalized_email
                user.save(update_fields=['email'])

            email_address, _ = EmailAddress.objects.update_or_create(
                user=user,
                email=user.email,
                defaults={
                    'primary': True,
                    'verified': False,
                },
            )
            
            # Get the auto-created profile and update it with form data
            profile = user.profile
            profile.full_name = profile_form.cleaned_data.get('full_name')
            profile.school = profile_form.cleaned_data.get('school')
            profile.year_level = profile_form.cleaned_data.get('year_level')
            profile.birthday = profile_form.cleaned_data.get('birthday')
            profile.age = profile_form.cleaned_data.get('age')
            profile.phone = profile_form.cleaned_data.get('phone')
            profile.address = profile_form.cleaned_data.get('address')
            profile.contact_info = profile_form.cleaned_data.get('contact_info')
            profile.save()
            
            try:
                email_address.send_confirmation(request=request, signup=True)
                messages.success(
                    request,
                    'Account created. Check your email to verify your account before signing in.'
                )
            except Exception:
                logger.exception('Unable to send signup verification email for user=%s', user.username)
                messages.warning(
                    request,
                    'Account created, but we could not send a verification email right now. '
                    'Please try signing in later to resend verification.'
                )

            return redirect('account_login')
    else:
        user_form = CustomUserCreationForm()
        profile_form = ProfileRegistrationForm()

    return render(request, 'marketplace/register.html', {
        'user_form': user_form,
        'profile_form': profile_form,
    })


@login_required
def complete_profile(request):
    """Complete/update profile information, especially after Google signup."""
    profile = request.user.profile
    
    if request.method == 'POST':
        form = ProfileRegistrationForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile completed successfully!')
            return redirect('marketplace:home')
    else:
        form = ProfileRegistrationForm(instance=profile)
    
    return render(request, 'marketplace/complete_profile.html', {'form': form})


@login_required
def get_category_fields(request):
    category_id = request.GET.get('category_id')
    listing_id = request.GET.get('listing_id')
    
    category = None
    if category_id and category_id.isdigit():
        category = get_object_or_404(Category, id=category_id)
        
    listing = None
    if listing_id and listing_id.isdigit():
        listing = get_object_or_404(Listing, id=listing_id)
        
    form = ListingForm(instance=listing, initial={'category': category}, user=request.user)
    # If category changed via AJAX, we need to manually trigger the field addition 
    # because the form's __init__ might have used the instance's category
    if category:
        form.product_attribute_fields = {}
        form._add_product_fields(category.slug)
    
    return render(request, 'marketplace/_product_fields.html', {'form': form})


@login_required
def listing_create(request):
    """Create a new listing."""
    profile = getattr(request.user, 'profile', None)
    if request.method == 'POST':
        form = ListingForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            listing = form.save(commit=False)
            listing.seller = request.user
            if not listing.contact_info and profile:
                listing.contact_info = profile.phone or profile.contact_info or ''
            if not listing.school and profile:
                listing.school = profile.school
            listing.save()
            messages.success(request, 'Your listing has been posted!')
            return redirect(listing.get_absolute_url())
    else:
        initial = {}
        if profile:
            initial = {
                'school': profile.school,
                'contact_info': profile.phone or profile.contact_info,
            }
        form = ListingForm(initial=initial, user=request.user)

    return render(request, 'marketplace/listing_form.html', {
        'form': form,
        'title': 'Sell an Item',
    })


@login_required
def listing_edit(request, pk):
    """Edit a listing."""
    listing = get_object_or_404(Listing, pk=pk)
    if listing.seller != request.user:
        messages.error(request, "You can't edit this listing.")
        return redirect(listing.get_absolute_url())

    if request.method == 'POST':
        form = ListingForm(request.POST, request.FILES, instance=listing, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Listing updated.')
            return redirect(listing.get_absolute_url())
    else:
        form = ListingForm(instance=listing, user=request.user)

    return render(request, 'marketplace/listing_form.html', {
        'form': form,
        'listing': listing,
        'title': 'Edit Listing',
    })


@login_required
def listing_delete(request, pk):
    """Delete a listing."""
    listing = get_object_or_404(Listing, pk=pk)
    if listing.seller != request.user:
        messages.error(request, "You can't delete this listing.")
        return redirect(listing.get_absolute_url())

    if request.method == 'POST':
        listing.delete()
        messages.success(request, 'Listing deleted.')
        return redirect('marketplace:listing_list')

    return render(request, 'marketplace/listing_confirm_delete.html', {'listing': listing})


@login_required
def listing_mark_sold(request, pk):
    """Mark listing as sold."""
    listing = get_object_or_404(Listing, pk=pk)
    if listing.seller != request.user:
        messages.error(request, "You can't modify this listing.")
        return redirect(listing.get_absolute_url())

    listing.is_sold = True
    listing.quantity_available = 0
    listing.save(update_fields=['is_sold', 'quantity_available'])
    messages.success(request, 'Listing marked as sold.')
    return redirect('marketplace:my_listings')


@login_required
def my_listings(request):
    """Redirect to unified My Profile page."""
    return redirect('marketplace:profile')


@login_required
def profile_view(request):
    """Unified My Profile page - redirects to public profile with edit form."""
    # When a user views their own profile, show them the public profile view
    # This allows them to see their profile exactly as other users see it
    return public_profile_view(request, request.user.username, is_owner=True)


def public_profile_view(request, username, is_owner=False):
    """View another user's public profile, or your own when is_owner=True."""
    user = get_object_or_404(User, username=username)
    profile, _ = Profile.objects.get_or_create(user=user)
    
    # Determine if current user is the profile owner
    is_profile_owner = request.user.is_authenticated and request.user == user
    
    # If viewing own profile through profile_view, get edit form
    form = None
    school_id_form = None
    latest_school_id_request = None
    if is_profile_owner and is_owner:
        latest_school_id_request = profile.school_id_requests.order_by('-submitted_at').first()
        if not profile.id_verified and (not latest_school_id_request or latest_school_id_request.status != 'pending'):
            school_id_form = SchoolIDVerificationRequestForm()

        if request.method == 'POST':
            form = ProfileForm(request.POST, request.FILES, instance=profile)
            if form.is_valid():
                form.save()
                profile.update_verification_tier()
                profile.save()
                messages.success(request, 'Profile updated.')
                return redirect('marketplace:profile')
        else:
            form = ProfileForm(instance=profile)
    
    listings = user.listings.filter(is_sold=False).select_related('category', 'school')
    reviews = Review.objects.filter(seller=user).select_related('reviewer').order_by('-created_at')[:10]
    profile_posts = ProfilePost.objects.filter(author=user)
    forum_posts = ForumPost.objects.filter(author=user)
    pinned_post = profile.pinned_post
    
    # Check if current user has bought from this seller
    has_purchased = False
    if request.user.is_authenticated and request.user != user:
        has_purchased = Transaction.objects.filter(buyer=request.user, seller=user).exists()
    
    # Check if user has already reviewed this seller
    has_reviewed = False
    if request.user.is_authenticated and request.user != user:
        has_reviewed = Review.objects.filter(reviewer=request.user, seller=user).exists()

    # Fetch transaction data for owner
    buyer_transactions = seller_transactions = None
    if is_profile_owner and is_owner:
        buyer_transactions = user.purchases.select_related('seller', 'listing').order_by('-created_at')
        seller_transactions = user.sales.select_related('buyer', 'listing').order_by('-created_at')

    # Get social media accounts
    social_media_accounts = profile.social_media.all().order_by('platform')
    
    context = {
        'profile_user': user,
        'profile': profile,
        'listings': listings,
        'reviews': reviews,
        'has_purchased': has_purchased,
        'has_reviewed': has_reviewed,
        'profile_posts': profile_posts,
        'forum_posts': forum_posts,
        'pinned_post': pinned_post,
        'is_profile_owner': is_profile_owner,
        'is_owner_view': is_owner,
        'form': form,
        'school_id_form': school_id_form,
        'latest_school_id_request': latest_school_id_request,
        'buyer_transactions': buyer_transactions,
        'seller_transactions': seller_transactions,
        'social_media_accounts': social_media_accounts,
    }
    
    return render(request, 'marketplace/public_profile.html', context)


@login_required
def submit_school_id_verification(request):
    """Submit a school ID for admin verification before trusted tiers."""
    profile = request.user.profile

    if request.method != 'POST':
        return redirect('marketplace:profile')

    if profile.id_verified:
        messages.info(request, 'Your school ID is already verified.')
        return redirect('marketplace:profile')

    pending_request = SchoolIDVerificationRequest.objects.filter(
        profile=profile,
        status='pending'
    ).first()
    if pending_request:
        messages.info(request, 'You already have a pending school ID verification request.')
        return redirect('marketplace:profile')

    form = SchoolIDVerificationRequestForm(request.POST, request.FILES)
    if not form.is_valid():
        error_list = form.errors.get('id_image', ['Please upload a valid school ID image.'])
        messages.error(request, str(error_list[0]))
        return redirect('marketplace:profile')

    request_obj = form.save(commit=False)
    request_obj.profile = profile
    request_obj.status = 'pending'
    request_obj.save()

    profile.id_submitted = True
    profile.id_verified = False
    profile.save(update_fields=['id_submitted', 'id_verified'])
    profile.update_verification_tier()

    messages.success(request, 'School ID submitted. Our team will review it before granting your trusted tier.')
    return redirect('marketplace:profile')


@login_required
def leave_review(request, username):
    """Leave a transaction-scoped vouch for the transaction counterparty."""
    seller = get_object_or_404(User, username=username)

    if seller == request.user:
        messages.error(request, "You can't vouch for yourself.")
        return redirect('marketplace:public_profile', username=username)

    tx_id = request.POST.get('transaction_id') or request.GET.get('transaction_id')
    eligible_transactions = Transaction.objects.filter(
        Q(buyer=request.user, seller=seller) | Q(buyer=seller, seller=request.user),
        status='completed',
        payment__status='completed',
    ).select_related('listing')

    transaction = None
    if tx_id:
        transaction = eligible_transactions.filter(pk=tx_id).first()
    else:
        transaction = eligible_transactions.order_by('-completed_at', '-created_at').first()

    if not transaction:
        messages.error(request, 'You can only leave a vouch after a completed and paid transaction.')
        return redirect('marketplace:public_profile', username=username)

    counterparty = transaction.seller if request.user == transaction.buyer else transaction.buyer
    if counterparty != seller:
        messages.error(request, 'The selected transaction does not match this profile.')
        return redirect('marketplace:public_profile', username=username)

    existing_review = Review.objects.filter(
        reviewer=request.user,
        seller=seller,
        transaction=transaction,
    ).first()
    
    if request.method == 'POST':
        is_vouch_str = request.POST.get('is_vouch', 'true')
        is_vouch = is_vouch_str.lower() == 'true'
        comment = request.POST.get('comment', '')

        if existing_review:
            existing_review.is_vouch = is_vouch
            existing_review.comment = comment
            existing_review.save()
            messages.success(request, 'Your vouch has been updated.')
        else:
            Review.objects.create(
                reviewer=request.user,
                seller=seller,
                listing=transaction.listing,
                transaction=transaction,
                is_vouch=is_vouch,
                comment=comment
            )
            messages.success(request, 'Your vouch has been posted!')

        return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)
    
    context = {
        'seller': seller,
        'existing_review': existing_review,
        'transaction': transaction,
    }
    return render(request, 'marketplace/leave_review.html', context)


@login_required
def create_profile_post(request):
    """Create a new post on user's profile."""
    if request.method == 'POST':
        form = ProfilePostForm(request.POST)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            messages.success(request, 'Post added to your profile!')
            return redirect('marketplace:public_profile', username=request.user.username)
    else:
        form = ProfilePostForm()
    
    return render(request, 'marketplace/profile_post_form.html', {'form': form})


@login_required
def delete_profile_post(request, pk):
    """Delete a profile post."""
    post = get_object_or_404(ProfilePost, pk=pk)
    
    if post.author != request.user:
        messages.error(request, 'You can only delete your own posts.')
        return redirect('marketplace:public_profile', username=request.user.username)
    
    if request.method == 'POST':
        # If this post was pinned, unpin it
        if post.author.profile.pinned_post == post:
            post.author.profile.pinned_post = None
            post.author.profile.save()
        
        post.delete()
        messages.success(request, 'Post deleted.')
        return redirect('marketplace:public_profile', username=request.user.username)
    
    return render(request, 'marketplace/profile_post_confirm_delete.html', {'post': post})


@login_required
def pin_profile_post(request, pk):
    """Pin/unpin a profile post."""
    post = get_object_or_404(ProfilePost, pk=pk)
    profile = request.user.profile
    
    if post.author != request.user:
        messages.error(request, 'You can only pin your own posts.')
        return redirect('marketplace:public_profile', username=request.user.username)
    
    if profile.pinned_post == post:
        # Unpin
        profile.pinned_post = None
        messages.success(request, 'Post unpinned.')
    else:
        # Pin
        profile.pinned_post = post
        messages.success(request, 'Post pinned to your profile!')
    
    profile.save()
    return redirect('marketplace:public_profile', username=request.user.username)


@login_required
def create_profile_post_comment(request, post_id):
    """Create a comment on a profile post."""
    post = get_object_or_404(ProfilePost, pk=post_id)
    
    if request.method == 'POST':
        form = ProfilePostCommentForm(request.POST, request.FILES)
        if form.is_valid():
            from .models import ProfilePostComment
            comment = form.save(commit=False)
            comment.post = post
            comment.author = request.user
            comment.save()
            messages.success(request, 'Comment added!')
            return redirect('marketplace:public_profile', username=post.author.username)
    else:
        form = ProfilePostCommentForm()
    
    return render(request, 'marketplace/post_comment_form.html', {
        'form': form,
        'post': post
    })


@login_required
def delete_profile_post_comment(request, comment_id):
    """Delete a comment on a profile post."""
    from .models import ProfilePostComment
    comment = get_object_or_404(ProfilePostComment, pk=comment_id)
    post = comment.post
    
    # Check permissions - comment author or post author can delete
    if comment.author != request.user and post.author != request.user:
        messages.error(request, 'You can only delete your own comments.')
        return redirect('marketplace:public_profile', username=post.author.username)
    
    if request.method == 'POST':
        comment.delete()
        messages.success(request, 'Comment deleted.')
        return redirect('marketplace:public_profile', username=post.author.username)
    
    return render(request, 'marketplace/comment_confirm_delete.html', {'comment': comment})


@login_required
def favorite_toggle(request, pk):
    """Add or remove listing from favorites."""
    listing = get_object_or_404(Listing, pk=pk)
    fav, created = Favorite.objects.get_or_create(user=request.user, listing=listing)
    if not created:
        fav.delete()
        messages.info(request, 'Removed from favorites.')
    else:
        messages.success(request, 'Added to favorites!')
    next_url = request.META.get('HTTP_REFERER') or listing.get_absolute_url()
    return redirect(next_url)


@login_required
def favorites_list(request):
    """View user's favorited listings."""
    favs = Favorite.objects.filter(user=request.user).select_related(
        'listing', 'listing__category', 'listing__school'
    ).order_by('-created_at')
    listings = [f.listing for f in favs]
    
    # Get recommendations based on favorites
    recommended_listings = _get_recommended_for_user(request.user, limit=6)
    
    return render(request, 'marketplace/favorites.html', {
        'listings': listings,
        'recommended_listings': recommended_listings
    })


@login_required
def recommended_listings(request):
    """Display AI-powered recommended listings based on user preferences."""
    profile = request.user.profile
    
    # Get user's favorites
    favorite_ids = Favorite.objects.filter(user=request.user).values_list('listing_id', flat=True)
    
    # Get available listings for recommendations
    available = Listing.objects.filter(
        is_sold=False
    ).exclude(
        pk__in=favorite_ids
    ).exclude(
        seller=request.user
    ).select_related('category', 'school')
    
    # Get Gemini recommendations
    from .utils import get_gemini_recommendations
    favorite_objs = Favorite.objects.filter(user=request.user).select_related('listing')[:10]
    
    recommendations = get_gemini_recommendations(
        user_profile=profile,
        favorite_listings=favorite_objs,
        available_listings=available,
        max_recommendations=12
    )
    
    # Fetch full listing details for recommended IDs
    recommended_listings = []
    if recommendations:
        for rec in recommendations:
            try:
                listing = Listing.objects.select_related('category', 'school', 'seller').get(id=rec['id'])
                recommended_listings.append({
                    'listing': listing,
                    'reason': rec['reason']
                })
            except Listing.DoesNotExist:
                continue
    
    # Fallback to rule-based recommendations if Gemini fails
    if not recommended_listings:
        fallback_listings = _get_recommended_for_user(request.user, limit=12)
        recommended_listings = [{'listing': listing, 'reason': 'Matches your interests'} for listing in fallback_listings]
    
    return render(request, 'marketplace/recommended.html', {
        'recommended_listings': recommended_listings,
        'has_gemini': bool(recommendations)
    })


@login_required
def api_gemini_recommendations(request):
    """API endpoint for Gemini-based recommendations."""
    from django.http import JsonResponse
    from .utils import get_gemini_recommendations
    
    profile = request.user.profile
    
    # Get user's favorites
    favorite_objs = Favorite.objects.filter(user=request.user).select_related('listing')[:10]
    favorite_ids = Favorite.objects.filter(user=request.user).values_list('listing_id', flat=True)
    
    # Get available listings (excluding favorites)
    available = Listing.objects.filter(
        is_sold=False
    ).exclude(
        pk__in=favorite_ids
    ).exclude(
        seller=request.user
    ).select_related('category', 'school')
    
    # Get Gemini recommendations
    recommendations = get_gemini_recommendations(
        user_profile=profile,
        favorite_listings=favorite_objs,
        available_listings=available,
        max_recommendations=6
    )
    
    if not recommendations:
        return JsonResponse({'recommendations': [], 'error': 'Could not generate recommendations'}, status=200)
    
    # Fetch full listing details for recommended IDs
    result_listings = []
    for rec in recommendations:
        try:
            listing = Listing.objects.select_related('category', 'school', 'seller').get(id=rec['id'])
            result_listings.append({
                'id': listing.id,
                'title': listing.title,
                'price': float(listing.price),
                'image_url': listing.image.url if listing.image else None,
                'category': listing.category.name if listing.category else None,
                'school_name': listing.school.short_name if listing.school else None,
                'seller_name': listing.seller.username,
                'ai_reason': rec['reason'],
                'view_count': listing.view_count,
                'url': listing.get_absolute_url()
            })
        except Listing.DoesNotExist:
            continue
    
    return JsonResponse({
        'recommendations': result_listings,
        'count': len(result_listings)
    })


@login_required
def recommendation_chat(request):
    """Display the AI chatbot for item recommendations."""
    return render(request, 'marketplace/recommendation_chat.html', {
        'page_title': 'AI Shopping Assistant'
    })


@login_required
def api_chat_message(request):
    """API endpoint for chat messages with Gemini."""
    from django.http import JsonResponse
    from .utils import get_gemini_chat_response
    
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)
    
    try:
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()
        conversation_history = data.get('history', [])
        
        if not user_message:
            return JsonResponse({'error': 'Message cannot be empty'}, status=400)
        
        # Limit message length
        if len(user_message) > 500:
            return JsonResponse({'error': 'Message too long (max 500 chars)'}, status=400)
        
        # Get available listings
        available_listings = Listing.objects.filter(is_sold=False).select_related('category', 'school')
        
        # Get response from Gemini
        response = get_gemini_chat_response(
            user_message=user_message,
            available_listings=available_listings,
            user_profile=request.user.profile,
            conversation_history=conversation_history
        )
        
        if 'error' in response:
            return JsonResponse({'error': response['error']}, status=500)
        
        # Fetch full listing details if recommendations mentioned
        recommendations = []
        if response.get('recommendations'):
            for listing_id in response['recommendations']:
                try:
                    listing = Listing.objects.select_related('category', 'school', 'seller').get(
                        id=listing_id
                    )
                    recommendations.append({
                        'id': listing.id,
                        'title': listing.title,
                        'price': float(listing.price),
                        'image_url': listing.image.url if listing.image else None,
                        'category': listing.category.name if listing.category else None,
                        'school_name': listing.school.short_name if listing.school else None,
                        'seller_name': listing.seller.username,
                        'url': listing.get_absolute_url()
                    })
                except Listing.DoesNotExist:
                    continue
        
        return JsonResponse({
            'response': response.get('response', ''),
            'recommendations': recommendations,
            'role': 'assistant'
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}")
        return JsonResponse({'error': 'Server error'}, status=500)


# ----- Transactions -----

@login_required
def initiate_purchase(request, pk):
    """Buyer initiates a purchase. Can be at listing price or an agreed offer price.
    
    For WTS listings: request.user is the buyer, listing.seller is the seller
    For WTB listings: listing.seller is the buyer, request.user is the seller (offering the item)
    """
    listing = get_object_or_404(Listing, pk=pk)
    
    # Check if this is from an accepted offer
    offer_amount = None
    offer_quantity = None
    offer_id = request.GET.get('offer_id')
    
    # Determine if this is a WTB or WTS listing
    is_wtb = listing.listing_type == 'wtb'

    if offer_id:
        # For WTS: offer is from the buyer (request.user)
        # For WTB: offer is from the seller/item provider (not request.user)
        if is_wtb:
            # WTB: look for offer from anyone (the item provider), accepted by WTB creator (listing.seller)
            offer_msg = get_object_or_404(Message, pk=offer_id, is_offer=True, offer_status='accepted')
        else:
            # WTS: look for offer from buyer (request.user)
            offer_msg = get_object_or_404(Message, pk=offer_id, is_offer=True, offer_status='accepted', sender=request.user)
        offer_amount = offer_msg.offer_amount
        offer_quantity = max(1, offer_msg.offer_quantity or 1)

    # WTS: Can't buy own listing
    # WTB: Can't offer own listing (request.user can't be the one who posted the WTB)
    if not is_wtb and listing.seller == request.user:
        messages.error(request, "You can't buy your own listing!")
        return redirect(listing.get_absolute_url())
    
    if is_wtb and listing.seller == request.user:
        messages.error(request, "You can't provide an item to your own WTB listing!")
        return redirect(listing.get_absolute_url())
    
    # Can't buy/provide sold listings
    if listing.is_sold or listing.quantity_available <= 0:
        messages.error(request, "This listing is no longer available.")
        return redirect(listing.get_absolute_url())
    
    # Determine buyer and seller based on listing type
    if is_wtb:
        # WTB: listing.seller is the buyer, request.user is the seller (offering the item)
        buyer = listing.seller
        seller = request.user
    else:
        # WTS: request.user is the buyer, listing.seller is the seller
        buyer = request.user
        seller = listing.seller
    
    # Check if there's already a pending transaction for this listing between these parties
    existing_txn = Transaction.objects.filter(
        buyer=buyer,
        seller=seller,
        listing=listing,
        status__in=['pending', 'confirmed']
    ).first()
    
    if existing_txn:
        messages.info(request, "You already have a pending transaction for this item. View it in your inbox.")
        return redirect('marketplace:transaction_detail', transaction_id=existing_txn.pk)
    
    if request.method == 'POST':
        form = PurchaseForm(request.POST, listing=listing)
        if form.is_valid():
            requested_quantity = form.cleaned_data['quantity']
            if offer_quantity is not None:
                requested_quantity = offer_quantity

            if requested_quantity > listing.quantity_available:
                messages.error(request, f"Only {listing.quantity_available} item(s) are currently available.")
                return redirect('marketplace:initiate_purchase', pk=listing.pk)

            unit_price = offer_amount if offer_amount is not None else listing.price
            total_price = Decimal(unit_price) * Decimal(requested_quantity)

            transaction = Transaction.objects.create(
                buyer=buyer,
                seller=seller,
                listing=listing,
                quantity=requested_quantity,
                unit_price=unit_price,
                price=total_price,
                exchange_method=form.cleaned_data['exchange_method'],
                proposed_meetup_location=form.cleaned_data.get('proposed_meetup_location') or '',
                proposed_meetup_datetime=form.cleaned_data.get('proposed_meetup_datetime'),
                notes=form.cleaned_data['notes'],
                status='pending'
            )
            
            # Create notification for the other party
            if is_wtb:
                # WTB: notify the seller (request.user) that buyer wants to confirm
                notified_user = seller
                notification_message = f"{buyer.username} is ready to buy {transaction.quantity} x {listing.title} for ₱{transaction.price:,.2f}"
            else:
                # WTS: notify the seller (listing.seller) that buyer wants to buy
                notified_user = seller
                notification_message = f"{buyer.username} wants to buy {transaction.quantity} x {listing.title}"
            
            Notification.objects.create(
                user=notified_user,
                related_user=buyer,
                message=notification_message,
                notification_type='transaction',
                url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk})
            )
            
            messages.success(request, 'Purchase initiated! Waiting for confirmation.')
            return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)
    else:
        initial_data = {}
        if offer_quantity is not None:
            initial_data['quantity'] = offer_quantity
        if listing.campus:
            initial_data['proposed_meetup_location'] = listing.campus
        form = PurchaseForm(initial=initial_data, listing=listing)
    
    return render(request, 'marketplace/purchase_form.html', {
        'form': form,
        'listing': listing,
        'seller': seller if is_wtb else listing.seller,
        'offer_amount': offer_amount,
        'offer_quantity': offer_quantity,
        'allowed_payment_methods': _get_allowed_payment_methods(listing),
        'is_wtb': is_wtb,
    })


@login_required
def transaction_detail(request, transaction_id):
    """View transaction details and receipt."""
    transaction = get_object_or_404(Transaction, pk=transaction_id)
    
    # Only buyer or seller can view
    if request.user not in [transaction.buyer, transaction.seller]:
        messages.error(request, "You don't have access to this transaction.")
        return redirect('marketplace:inbox')
    
    is_buyer = request.user == transaction.buyer
    is_seller = request.user == transaction.seller
    
    # In-transaction messages
    txn_messages = transaction.messages.select_related('sender').all()
    message_form = MessageForm()

    # Seller confirmation form (pending only)
    confirm_form = TransactionConfirmForm(instance=transaction) if is_seller and transaction.status == 'pending' else None

    if request.method == 'POST':
        action = request.POST.get('action')

        # Seller confirming the transaction
        if action == 'confirm' and is_seller and transaction.status == 'pending':
            confirm_form = TransactionConfirmForm(request.POST, instance=transaction)
            if confirm_form.is_valid():
                # Reserve stock at confirmation time to support partial fills safely.
                if transaction.listing:
                    transaction.listing.refresh_from_db()
                    if transaction.listing.quantity_available < transaction.quantity:
                        messages.error(
                            request,
                            f"Not enough stock left. Available: {transaction.listing.quantity_available}, requested: {transaction.quantity}."
                        )
                        return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

                    transaction.listing.quantity_available -= transaction.quantity
                    transaction.listing.is_sold = transaction.listing.quantity_available == 0
                    transaction.listing.save(update_fields=['quantity_available', 'is_sold'])

                transaction = confirm_form.save(commit=False)
                transaction.status = 'confirmed'
                transaction.confirmed_at = timezone.now()
                transaction.buyer_confirmed_meeting = False
                transaction.seller_confirmed_meeting = False
                transaction.save()
                
                # Notify buyer
                Notification.objects.create(
                    user=transaction.buyer,
                    related_user=transaction.seller,
                    message=f"{transaction.seller.username} confirmed your purchase!",
                    notification_type='transaction',
                    url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk})
                )
                
                messages.success(request, 'Purchase confirmed! Buyer and seller can now exchange contact details.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

        elif action == 'confirm_meeting' and transaction.status == 'confirmed':
            if request.user == transaction.buyer:
                transaction.buyer_confirmed_meeting = True
                who = 'Buyer'
                other_user = transaction.seller
            else:
                transaction.seller_confirmed_meeting = True
                who = 'Seller'
                other_user = transaction.buyer

            transaction.save(update_fields=['buyer_confirmed_meeting', 'seller_confirmed_meeting'])

            if transaction.buyer_confirmed_meeting and transaction.seller_confirmed_meeting:
                Notification.objects.create(
                    user=transaction.buyer,
                    message='Both sides confirmed meetup/agreement. Payment checkout is now unlocked.',
                    notification_type='transaction',
                    url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
                )
                Notification.objects.create(
                    user=transaction.seller,
                    message='Both sides confirmed meetup/agreement. Buyer can now proceed to payment.',
                    notification_type='transaction',
                    url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
                )
                messages.success(request, 'Both sides have confirmed meetup/agreement. Payment can now proceed.')
            else:
                Notification.objects.create(
                    user=other_user,
                    related_user=request.user,
                    message=f'{request.user.username} ({who}) confirmed meetup/agreement. Please confirm on your end to unlock payment.',
                    notification_type='transaction',
                    url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
                )
                messages.info(request, 'Your meetup/agreement confirmation was saved. Waiting for the other party.')

            return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

        elif action == 'upload_meetup_proof' and transaction.status == 'confirmed':
            payment = getattr(transaction, 'payment', None)
            if payment is None or payment.payment_method != 'in_person' or payment.status != 'pending':
                messages.error(request, 'Meetup photo proof is only available for pending in-person cash payments.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

            meetup_photo = request.FILES.get('meetup_photo')
            if meetup_photo is None:
                messages.error(request, 'Please upload a meetup photo before submitting.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

            if not (getattr(meetup_photo, 'content_type', '') or '').lower().startswith('image/'):
                messages.error(request, 'Meetup proof must be a valid image file.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

            max_photo_size = 8 * 1024 * 1024
            if meetup_photo.size > max_photo_size:
                messages.error(request, 'Meetup photo must be 8MB or smaller.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

            now = timezone.now()
            update_fields = []

            if request.user == transaction.buyer:
                payment.buyer_meetup_photo = meetup_photo
                payment.buyer_meetup_photo_uploaded_at = now
                update_fields.extend(['buyer_meetup_photo', 'buyer_meetup_photo_uploaded_at', 'updated_at'])
                notify_user = transaction.seller
            else:
                payment.seller_meetup_photo = meetup_photo
                payment.seller_meetup_photo_uploaded_at = now
                update_fields.extend(['seller_meetup_photo', 'seller_meetup_photo_uploaded_at', 'updated_at'])
                notify_user = transaction.buyer

            payment.save(update_fields=update_fields)

            Notification.objects.create(
                user=notify_user,
                related_user=request.user,
                message=f'{request.user.username} uploaded in-person meetup photo proof for transaction #{transaction.pk}.',
                notification_type='transaction',
                url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
            )

            if _in_person_meetup_proof_ready(payment):
                messages.success(request, 'Both meetup photo proofs are uploaded. Seller can now verify payment evidence.')
            else:
                messages.success(request, 'Meetup photo proof uploaded. Waiting for the other party to upload theirs.')

            return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

        elif action == 'submit_delivery_tracking' and transaction.status == 'confirmed':
            payment = getattr(transaction, 'payment', None)
            if payment is None or payment.payment_method != 'third_party_delivery' or payment.status != 'pending':
                messages.error(request, 'Delivery tracking link can only be set for pending third-party delivery payments.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

            provider_code = (request.POST.get('tracking_provider') or '').strip().lower()
            if provider_code not in THIRD_PARTY_PROVIDER_CODES:
                messages.error(request, 'Please select a valid delivery provider before submitting a tracking link.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

            tracking_link = (request.POST.get('tracking_link') or '').strip()
            is_valid, validation_error = _is_valid_tracking_link(tracking_link, provider=provider_code)
            if not is_valid:
                messages.error(request, validation_error)
                return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

            now = timezone.now()
            payment.third_party_provider = provider_code
            payment.third_party_tracking_link = tracking_link
            payment.third_party_tracking_link_submitted_at = now
            payment.third_party_tracking_link_submitted_by = request.user
            payment.buyer_tracking_acknowledged_at = None
            payment.seller_tracking_acknowledged_at = None
            payment.save(
                update_fields=[
                    'third_party_provider',
                    'third_party_tracking_link',
                    'third_party_tracking_link_submitted_at',
                    'third_party_tracking_link_submitted_by',
                    'buyer_tracking_acknowledged_at',
                    'seller_tracking_acknowledged_at',
                    'updated_at',
                ]
            )

            notify_user = transaction.seller if request.user == transaction.buyer else transaction.buyer
            Notification.objects.create(
                user=notify_user,
                related_user=request.user,
                message=(
                    f'{request.user.username} submitted a shared {provider_code} tracking link for transaction '
                    f'#{transaction.pk}. Please acknowledge it before payment verification.'
                ),
                notification_type='transaction',
                url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
            )

            messages.success(
                request,
                'Tracking link submitted. Both buyer and seller must acknowledge the shared link before verification.',
            )
            return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

        elif action == 'ack_delivery_tracking' and transaction.status == 'confirmed':
            payment = getattr(transaction, 'payment', None)
            if payment is None or payment.payment_method != 'third_party_delivery' or payment.status != 'pending':
                messages.error(request, 'Tracking acknowledgment is only available for pending third-party delivery payments.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

            if not _third_party_tracking_link_ready(payment):
                messages.error(request, 'A shared tracking link must be submitted before acknowledgments can be recorded.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

            now = timezone.now()
            update_fields = ['updated_at']
            if request.user == transaction.buyer:
                if payment.buyer_tracking_acknowledged_at:
                    messages.info(request, 'You already acknowledged the shared tracking link.')
                    return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)
                payment.buyer_tracking_acknowledged_at = now
                update_fields.append('buyer_tracking_acknowledged_at')
                role_label = 'Buyer'
                notify_user = transaction.seller
            else:
                if payment.seller_tracking_acknowledged_at:
                    messages.info(request, 'You already acknowledged the shared tracking link.')
                    return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)
                payment.seller_tracking_acknowledged_at = now
                update_fields.append('seller_tracking_acknowledged_at')
                role_label = 'Seller'
                notify_user = transaction.buyer

            payment.save(update_fields=update_fields)

            Notification.objects.create(
                user=notify_user,
                related_user=request.user,
                message=(
                    f'{request.user.username} ({role_label}) acknowledged the shared delivery tracking link for '
                    f'transaction #{transaction.pk}.'
                ),
                notification_type='transaction',
                url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
            )

            if _third_party_tracking_ack_ready(payment):
                messages.success(request, 'Both parties acknowledged the tracking link. Seller can now continue verification.')
            else:
                messages.success(request, 'Tracking acknowledgment saved. Waiting for the other party to acknowledge.')

            return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

        # Any party sending a message within the transaction
        elif action == 'message':
            message_form = MessageForm(request.POST)
            if message_form.is_valid():
                msg = TransactionMessage.objects.create(
                    transaction=transaction,
                    sender=request.user,
                    body=message_form.cleaned_data['body'],
                )

                # Notify the other party
                other_user = transaction.seller if request.user == transaction.buyer else transaction.buyer
                Notification.objects.create(
                    user=other_user,
                    related_user=request.user,
                    message=f"New message about your transaction for {transaction.listing.title if transaction.listing else 'an item'}",
                    notification_type='message',
                    url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
                )

                messages.success(request, 'Message sent.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)
    
    buyer_profile = getattr(transaction.buyer, 'profile', None) or Profile.objects.filter(user=transaction.buyer).first()
    seller_profile = getattr(transaction.seller, 'profile', None) or Profile.objects.filter(user=transaction.seller).first()
    payment = getattr(transaction, 'payment', None)
    payment_completed = payment is not None and payment.status == 'completed'
    payment_pending = payment is not None and payment.status == 'pending'
    manual_payment_pending = (
        payment_pending
        and payment is not None
        and _is_manual_payment_method(payment.payment_method)
    )
    payment_manual_verification_status = payment.manual_verification_status if payment else ''
    in_person_payment_pending = payment_pending and payment is not None and payment.payment_method == 'in_person'
    third_party_delivery_payment_pending = (
        payment_pending and payment is not None and payment.payment_method == 'third_party_delivery'
    )
    buyer_meetup_photo_uploaded = bool(payment.buyer_meetup_photo) if in_person_payment_pending and payment else False
    seller_meetup_photo_uploaded = bool(payment.seller_meetup_photo) if in_person_payment_pending and payment else False
    in_person_meetup_proof_ready = in_person_payment_pending and _in_person_meetup_proof_ready(payment)
    third_party_tracking_link_ready = third_party_delivery_payment_pending and _third_party_tracking_link_ready(payment)
    third_party_tracking_ack_ready = third_party_delivery_payment_pending and _third_party_tracking_ack_ready(payment)
    third_party_tracking_provider = payment.third_party_provider if third_party_delivery_payment_pending and payment else ''
    third_party_tracking_link = payment.third_party_tracking_link if third_party_delivery_payment_pending and payment else ''
    third_party_tracking_link_submitted_by = (
        payment.third_party_tracking_link_submitted_by if third_party_delivery_payment_pending and payment else None
    )
    buyer_tracking_acknowledged = bool(
        payment.buyer_tracking_acknowledged_at
    ) if third_party_delivery_payment_pending and payment else False
    seller_tracking_acknowledged = bool(
        payment.seller_tracking_acknowledged_at
    ) if third_party_delivery_payment_pending and payment else False
    meeting_confirmed = transaction.buyer_confirmed_meeting and transaction.seller_confirmed_meeting
    allowed_payment_methods = _get_allowed_payment_methods(transaction.listing)
    
    # Determine if this is a WTB transaction
    is_wtb = transaction.listing and transaction.listing.listing_type == 'wtb'

    return render(request, 'marketplace/transaction_detail.html', {
        'transaction': transaction,
        'buyer_profile': buyer_profile,
        'seller_profile': seller_profile,
        'is_buyer': is_buyer,
        'is_seller': is_seller,
        'confirm_form': confirm_form,
        'txn_messages': txn_messages,
        'message_form': message_form,
        'payment': payment,
        'payment_completed': payment_completed,
        'payment_pending': payment_pending,
        'manual_payment_pending': manual_payment_pending,
        'payment_manual_verification_status': payment_manual_verification_status,
        'in_person_payment_pending': in_person_payment_pending,
        'third_party_delivery_payment_pending': third_party_delivery_payment_pending,
        'buyer_meetup_photo_uploaded': buyer_meetup_photo_uploaded,
        'seller_meetup_photo_uploaded': seller_meetup_photo_uploaded,
        'in_person_meetup_proof_ready': in_person_meetup_proof_ready,
        'third_party_tracking_link_ready': third_party_tracking_link_ready,
        'third_party_tracking_ack_ready': third_party_tracking_ack_ready,
        'third_party_tracking_provider': third_party_tracking_provider,
        'third_party_tracking_link': third_party_tracking_link,
        'third_party_tracking_link_submitted_by': third_party_tracking_link_submitted_by,
        'buyer_tracking_acknowledged': buyer_tracking_acknowledged,
        'seller_tracking_acknowledged': seller_tracking_acknowledged,
        'meeting_confirmed': meeting_confirmed,
        'allowed_payment_methods': allowed_payment_methods,
        'is_wtb': is_wtb,
    })


@login_required
def confirm_transaction(request, transaction_id):
    """Allow seller to confirm transaction and move to exchange stage."""
    transaction = get_object_or_404(Transaction, pk=transaction_id)
    
    if transaction.seller != request.user:
        messages.error(request, "Only the seller can confirm this transaction.")
        return redirect('marketplace:inbox')
    
    if transaction.status != 'pending':
        messages.error(request, "This transaction cannot be confirmed.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)
    
    if request.method == 'POST':
        form = TransactionConfirmForm(request.POST, instance=transaction)
        if form.is_valid():
            from django.utils import timezone

            if transaction.listing:
                transaction.listing.refresh_from_db()
                if transaction.listing.quantity_available < transaction.quantity:
                    messages.error(
                        request,
                        f"Not enough stock left. Available: {transaction.listing.quantity_available}, requested: {transaction.quantity}."
                    )
                    return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

                transaction.listing.quantity_available -= transaction.quantity
                transaction.listing.is_sold = transaction.listing.quantity_available == 0
                transaction.listing.save(update_fields=['quantity_available', 'is_sold'])

            transaction = form.save(commit=False)
            transaction.status = 'confirmed'
            transaction.confirmed_at = timezone.now()
            transaction.buyer_confirmed_meeting = False
            transaction.seller_confirmed_meeting = False
            transaction.save()

            # Notify buyer
            from django.urls import reverse
            Notification.objects.create(
                user=transaction.buyer,
                related_user=transaction.seller,
                message=f"{transaction.seller.username} confirmed your purchase!",
                notification_type='transaction',
                url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk})
            )
            
            messages.success(request, 'Purchase confirmed!')
            return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)
    else:
        form = TransactionConfirmForm(instance=transaction)
    
    return render(request, 'marketplace/transaction_confirm.html', {
        'form': form,
        'transaction': transaction,
    })


@login_required
def complete_transaction(request, transaction_id):
    """Mark transaction as complete. Requires mutual confirmation from both parties."""
    transaction = get_object_or_404(Transaction, pk=transaction_id)
    
    # Participant check
    if request.user != transaction.buyer and request.user != transaction.seller:
        messages.error(request, "You are not a participant in this transaction.")
        return redirect('marketplace:inbox')
    
    if transaction.status != 'confirmed':
        messages.error(request, "Transaction must be confirmed by the seller first.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

    if not (transaction.buyer_confirmed_meeting and transaction.seller_confirmed_meeting):
        messages.error(request, "Both parties must confirm meetup/agreement before completing this transaction.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

    payment = getattr(transaction, 'payment', None)
    if payment is None or payment.status != 'completed':
        messages.error(request, "Payment must be confirmed first before completing this transaction.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

    # Require POST to prevent CSRF via GET links
    if request.method != 'POST':
        return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

    previous_buyer_completed = transaction.buyer_completed
    previous_seller_completed = transaction.seller_completed
    previous_transaction_status = transaction.status

    participant_transition_payloads = []
    final_status_transition_payload = None

    from django.urls import reverse
    if request.user == transaction.buyer:
        transaction.buyer_completed = True
        if not previous_buyer_completed:
            participant_transition_payloads.append({
                'from_state': 'false',
                'to_state': 'true',
                'reason': 'buyer_marked_completed',
            })
        status_msg = "You've marked this purchase as successful."
        other_party = transaction.seller
        other_msg = f"{request.user.username} (Buyer) confirmed the exchange. Please confirm on your end."
    else:
        transaction.seller_completed = True
        if not previous_seller_completed:
            participant_transition_payloads.append({
                'from_state': 'false',
                'to_state': 'true',
                'reason': 'seller_marked_completed',
            })
        status_msg = "You've marked this sale as successful."
        other_party = transaction.buyer
        other_msg = f"{request.user.username} (Seller) confirmed the exchange. Please confirm on your end."
    
    if transaction.buyer_completed and transaction.seller_completed:
        from django.utils import timezone
        transaction.status = 'completed'
        transaction.completed_at = timezone.now()
        if previous_transaction_status != transaction.status:
            final_status_transition_payload = {
                'from_state': previous_transaction_status,
                'to_state': transaction.status,
                'reason': 'mutual_participant_completion',
                'details': {
                    'buyer_completed': transaction.buyer_completed,
                    'seller_completed': transaction.seller_completed,
                    'payment_status': payment.status,
                },
            }
        
        if transaction.listing:
            transaction.listing.is_sold = transaction.listing.quantity_available == 0
            transaction.listing.save(update_fields=['is_sold'])
            
        seller_profile = getattr(transaction.seller, 'profile', None) or Profile.objects.filter(user=transaction.seller).first()
        buyer_profile = getattr(transaction.buyer, 'profile', None) or Profile.objects.filter(user=transaction.buyer).first()
        
        if seller_profile:
            seller_profile.total_sold += transaction.quantity
            seller_profile.update_verification_tier()
            seller_profile.save()

        if buyer_profile:
            buyer_profile.total_bought += transaction.quantity
            buyer_profile.update_verification_tier()
            buyer_profile.save()

        # Notify both
        Notification.objects.create(
            user=transaction.seller,
            message="Mutual confirmation received! Sale fully completed. Leave a vouch for your buyer.",
            notification_type='transaction',
            url=f"{reverse('marketplace:leave_review', kwargs={'username': transaction.buyer.username})}?transaction_id={transaction.pk}"
        )
        Notification.objects.create(
            user=transaction.buyer,
            message="Mutual confirmation received! You can now leave a vouch for the seller.",
            notification_type='transaction',
            url=f"{reverse('marketplace:leave_review', kwargs={'username': transaction.seller.username})}?transaction_id={transaction.pk}"
        )
        messages.success(request, '✓ Transaction fully completed!')
    else:
        Notification.objects.create(
            user=other_party,
            related_user=request.user,
            message=other_msg,
            notification_type='transaction',
            url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk})
        )
        messages.info(request, f"{status_msg} Waiting for the other party to confirm.")

    transaction.save()

    for payload in participant_transition_payloads:
        _record_state_transition(
            request,
            entity_type='transaction',
            transition_kind='participant_completion',
            transaction=transaction,
            from_state=payload['from_state'],
            to_state=payload['to_state'],
            reason=payload['reason'],
            details={'actor_role': 'buyer' if request.user == transaction.buyer else 'seller'},
        )

    if final_status_transition_payload is not None:
        _record_state_transition(
            request,
            entity_type='transaction',
            transition_kind='transaction_status',
            transaction=transaction,
            from_state=final_status_transition_payload['from_state'],
            to_state=final_status_transition_payload['to_state'],
            reason=final_status_transition_payload['reason'],
            details=final_status_transition_payload['details'],
        )

    return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)


@login_required
def cancel_transaction(request, transaction_id):
    """Allow buyer or seller to cancel a pending or confirmed transaction."""
    transaction = get_object_or_404(Transaction, pk=transaction_id)
    
    # Only buyer or seller can cancel
    if request.user not in [transaction.buyer, transaction.seller]:
        messages.error(request, "You don't have permission to cancel this transaction.")
        return redirect('marketplace:inbox')
    
    # Can only cancel pending or confirmed
    if transaction.status not in ['pending', 'confirmed']:
        messages.error(request, f"Cannot cancel a {transaction.status} transaction.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)
    
    if request.method == 'POST':
        # Restore listing to available if it was marked sold during confirmation
        if transaction.status == 'confirmed' and transaction.listing:
            transaction.listing.quantity_available = min(
                transaction.listing.quantity_total,
                transaction.listing.quantity_available + transaction.quantity,
            )
            transaction.listing.is_sold = transaction.listing.quantity_available == 0
            transaction.listing.save(update_fields=['quantity_available', 'is_sold'])

        transaction.status = 'cancelled'
        transaction.save()
        
        # Notify the other party
        other_user = transaction.seller if request.user == transaction.buyer else transaction.buyer
        from django.urls import reverse
        Notification.objects.create(
            user=other_user,
            related_user=request.user,
            message=f"{request.user.username} cancelled the transaction for {transaction.listing.title if transaction.listing else 'an item'}",
            notification_type='transaction',
            url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk})
        )
        
        messages.success(request, 'Transaction cancelled.')
        return redirect('marketplace:inbox')
    
    return render(request, 'marketplace/transaction_cancel_confirm.html', {
        'transaction': transaction,
    })


@login_required
def notifications_list(request):
    """Show user's notifications with filtering and pagination."""
    from django.core.paginator import Paginator
    
    # Get filter parameter
    filter_type = request.GET.get('filter', 'all')
    
    # Base queryset
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
    
    # Apply type filter
    if filter_type != 'all':
        if filter_type == 'unread':
            notifications = notifications.filter(is_read=False)
        else:
            notifications = notifications.filter(notification_type=filter_type)
    
    # Mark unread as read (only if viewing all unread)
    if filter_type == 'all' or filter_type == 'unread':
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    
    # Pagination
    paginator = Paginator(notifications, 20)  # 20 per page
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'notifications': page_obj.object_list,
        'filter_type': filter_type,
        'notification_types': Notification.NOTIFICATION_TYPES,
    }
    
    return render(request, 'marketplace/notifications.html', context)


@login_required
def get_recent_notifications(request):
    """AJAX endpoint to fetch recent notifications for dropdown preview."""
    from django.http import JsonResponse
    
    try:
        notifications = list(Notification.objects.filter(user=request.user).order_by('-created_at')[:5])
        
        notifications_data = []
        for n in notifications:
            # Safely build related_user data
            related_user_data = None
            if n.related_user:
                avatar_url = None
                if hasattr(n.related_user, 'profile'):
                    avatar_url = n.related_user.profile.get_avatar_url()
                
                related_user_data = {
                    'username': n.related_user.username,
                    'avatar_url': avatar_url,
                }
            
            notification_data = {
                'id': n.id,
                'message': n.message,
                'type': n.get_notification_type_display(),
                'type_key': n.notification_type,
                'url': n.url or '#',
                'is_read': n.is_read,
                'created_at': n.created_at.strftime('%I:%M %p'),
                'created_at_full': n.created_at.strftime('%b %d, %Y %I:%M %p'),
                'related_user': related_user_data,
            }
            notifications_data.append(notification_data)
        
        return JsonResponse({
            'success': True,
            'notifications': notifications_data,
            'unread_count': sum(1 for n in notifications if not n.is_read),
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=500)


@login_required
def delete_notifications(request):
    """Delete selected notifications or clear old ones."""
    if request.method == 'POST':
        action = request.POST.get('action', 'delete')
        
        if action == 'delete_selected':
            notification_ids = request.POST.getlist('notification_ids')
            Notification.objects.filter(id__in=notification_ids, user=request.user).delete()
        elif action == 'clear_old':
            # Clear notifications older than 30 days
            from datetime import timedelta
            from django.utils import timezone
            thirty_days_ago = timezone.now() - timedelta(days=30)
            Notification.objects.filter(user=request.user, created_at__lt=thirty_days_ago).delete()
        elif action == 'mark_as_read':
            notification_ids = request.POST.getlist('notification_ids')
            Notification.objects.filter(id__in=notification_ids, user=request.user).update(is_read=True)
        elif action == 'mark_as_unread':
            notification_ids = request.POST.getlist('notification_ids')
            Notification.objects.filter(id__in=notification_ids, user=request.user).update(is_read=False)
    
    return redirect('marketplace:notifications')


# ----- Messaging -----

def _get_or_create_conversation(user1, user2, listing=None):
    """Get existing conversation or create new one between two users."""
    from django.db.models import Q
    convs = Conversation.objects.filter(
        participants=user1
    ).filter(
        participants=user2
    )
    if listing:
        convs = convs.filter(listing=listing)
    else:
        convs = convs.filter(listing__isnull=True)
    conv = convs.first()
    if not conv:
        conv = Conversation.objects.create(listing=listing)
        ConversationParticipant.objects.create(conversation=conv, user=user1)
        ConversationParticipant.objects.create(conversation=conv, user=user2)
    return conv


@login_required
def inbox(request):
    """List user's conversations, transactions, and receipts."""
    # Get conversations
    convs = Conversation.objects.filter(participants=request.user).prefetch_related(
        'participants', 'messages__sender', 'listing'
    ).order_by('-updated_at')
    convs_with_preview = []
    for conv in convs:
        other = conv.get_other_participant(request.user)
        if not other:
            continue
        prof = getattr(other, 'profile', None) or Profile.objects.filter(user=other).first()
        last_msg = conv.messages.order_by('-created_at').first()
        convs_with_preview.append({
            'conversation': conv,
            'other': other,
            'other_display_name': (prof.display_name if prof else None) or other.username,
            'last_message': last_msg,
        })
    
    # Get pending, confirmed, completed, and cancelled transactions (all statuses)
    transactions = Transaction.objects.filter(
        Q(buyer=request.user) | Q(seller=request.user)
    ).select_related('listing', 'buyer', 'seller').order_by('-created_at')
    
    # Get receipts
    receipts = Receipt.objects.filter(
        Q(buyer=request.user) | Q(seller=request.user)
    ).select_related('transaction', 'buyer', 'seller').order_by('-created_at')
    
    return render(request, 'marketplace/inbox.html', {
        'conversations': convs_with_preview,
        'transactions': transactions,
        'receipts': receipts,
    })


@login_required
def conversation_view(request, pk):
    """View a conversation and send messages."""
    conv = get_object_or_404(Conversation.objects.prefetch_related('participants', 'messages__sender'), pk=pk)
    if request.user not in conv.participants.all():
        messages.error(request, "You don't have access to this conversation.")
        return redirect('marketplace:inbox')

    other = conv.get_other_participant(request.user)
    other_prof = None
    if other:
        other_prof = getattr(other, 'profile', None) or Profile.objects.filter(user=other).first()
    msgs = conv.messages.filter(is_hidden=False).select_related('sender').all()

    if request.method == 'POST':
        form = MessageForm(request.POST)
        if form.is_valid():
            Message.objects.create(conversation=conv, sender=request.user, body=form.cleaned_data['body'])
            return redirect('marketplace:conversation', pk=pk)
    else:
        form = MessageForm()

    return render(request, 'marketplace/conversation.html', {
        'conversation': conv,
        'other': other,
        'other_display_name': (other_prof.display_name if other_prof else None) or (other.username if other else ''),
        'messages': msgs,
        'form': form,
    })


@login_required
def message_send(request, pk):
    """Start a conversation with a listing seller (from listing page)."""
    listing = get_object_or_404(Listing, pk=pk)
    if listing.seller == request.user:
        messages.error(request, "You can't message yourself.")
        return redirect(listing.get_absolute_url())

    conv = _get_or_create_conversation(request.user, listing.seller, listing=listing)

    if request.method == 'POST':
        form = MessageForm(request.POST)
        if form.is_valid():
            Message.objects.create(conversation=conv, sender=request.user, body=form.cleaned_data['body'])
            messages.success(request, 'Message sent!')
            return redirect('marketplace:conversation', pk=conv.pk)
    else:
        # If jumping straight to an offer, bypass the manual message form
        if request.GET.get('initial_offer') == '1':
            return redirect(reverse('marketplace:conversation', kwargs={'pk': conv.pk}) + '?initial_offer=1')
            
        form = MessageForm()

    return render(request, 'marketplace/message_send.html', {
        'form': form,
        'listing': listing,
        'conversation': conv,
    })


@login_required
def make_offer(request, pk):
    """Handle a formal offer sent within a conversation."""
    conversation = get_object_or_404(Conversation, pk=pk)
    if request.user not in conversation.participants.all():
        return redirect('marketplace:inbox')
    
    if request.method == 'POST':
        amount = request.POST.get('amount')
        quantity_raw = request.POST.get('quantity', '1')
        if amount:
            try:
                amount = float(amount)
                quantity = int(quantity_raw)
                if quantity < 1:
                    raise ValueError('Quantity must be at least 1')
                other_user = conversation.participants.exclude(id=request.user.id).first()

                if conversation.listing and quantity > conversation.listing.quantity_available:
                    messages.error(request, f"Only {conversation.listing.quantity_available} item(s) are available.")
                    return redirect('marketplace:conversation', pk=conversation.pk)
                
                total = amount * quantity
                body = f"OFFER: {quantity} x ₱{amount:,.2f} = ₱{total:,.2f}"
                msg = Message.objects.create(
                    conversation=conversation,
                    sender=request.user,
                    body=body,
                    is_offer=True,
                    offer_amount=amount,
                    offer_quantity=quantity,
                    offer_status='pending'
                )
                
                Notification.objects.create(
                    user=other_user,
                    related_user=request.user,
                    message=f"New offer for {conversation.listing.title if conversation.listing else 'an item'}: {quantity} x ₱{amount:,.2f}",
                    notification_type='offer',
                    url=reverse('marketplace:conversation', kwargs={'pk': conversation.pk})
                )
                
                messages.success(request, f"Offer sent: {quantity} x ₱{amount:,.2f} (₱{total:,.2f} total)")
            except ValueError:
                messages.error(request, "Invalid offer amount or quantity.")
                
    return redirect('marketplace:conversation', pk=conversation.pk)


@login_required
def respond_to_offer(request, pk):
    """Accept or decline an offer message."""
    message = get_object_or_404(Message, pk=pk, is_offer=True)
    if message.conversation.listing.seller != request.user:
        messages.error(request, "Only the seller can respond to offers.")
        return redirect('marketplace:conversation', pk=message.conversation.pk)
    
    action = request.GET.get('action')
    if action == 'accept':
        message.offer_status = 'accepted'
        total = (message.offer_amount or 0) * (message.offer_quantity or 1)
        message.body = f"ACCEPTED OFFER: {message.offer_quantity or 1} x ₱{message.offer_amount:,.2f} = ₱{total:,.2f}"
        
        # Optionally update the listing price? User didn't say, but it makes sense.
        # For now just notify buyer.
        Notification.objects.create(
            user=message.sender,
            related_user=message.conversation.listing.seller if message.conversation.listing else None,
            message=f"Your offer for {message.conversation.listing.title} was ACCEPTED!",
            notification_type='offer',
            url=reverse('marketplace:conversation', kwargs={'pk': message.conversation.pk})
        )
        messages.success(request, "Offer accepted!")
    elif action == 'decline':
        message.offer_status = 'declined'
        total = (message.offer_amount or 0) * (message.offer_quantity or 1)
        message.body = f"DECLINED OFFER: {message.offer_quantity or 1} x ₱{message.offer_amount:,.2f} = ₱{total:,.2f}"
        Notification.objects.create(
            user=message.sender,
            related_user=message.conversation.listing.seller if message.conversation.listing else None,
            message=f"Your offer for {message.conversation.listing.title} was declined.",
            notification_type='offer',
            url=reverse('marketplace:conversation', kwargs={'pk': message.conversation.pk})
        )
        messages.info(request, "Offer declined.")
    
    message.save()
    return redirect('marketplace:conversation', pk=message.conversation.pk)


# ----- Live Forum -----

def forum_index(request):
    """Live forum - list posts, auto-refresh for 'live' feel."""
    posts = ForumPost.objects.filter(is_hidden=False).select_related('author', 'listing', 'listing__category', 'listing__school').prefetch_related('replies').order_by('-created_at')[:50]
    return render(request, 'marketplace/forum_index.html', {'posts': posts})


def forum_post_detail(request, pk):
    """View a forum post and its replies."""
    qs = ForumPost.objects.select_related('author', 'listing', 'listing__category', 'listing__school')
    if not (request.user.is_authenticated and request.user.is_superuser):
        qs = qs.filter(is_hidden=False)
    post = get_object_or_404(qs, pk=pk)
    replies_qs = post.replies.select_related('author').order_by('created_at')
    if not (request.user.is_authenticated and request.user.is_superuser):
        replies_qs = replies_qs.filter(is_hidden=False)
    replies = replies_qs

    form = None
    if request.user.is_authenticated:
        if request.method == 'POST':
            form = ForumReplyForm(request.POST)
            if form.is_valid():
                ForumReply.objects.create(post=post, author=request.user, body=form.cleaned_data['body'])
                messages.success(request, 'Reply posted!')
                return redirect('marketplace:forum_post', pk=pk)
        else:
            form = ForumReplyForm()

    return render(request, 'marketplace/forum_post.html', {
        'post': post,
        'replies': replies,
        'form': form,
    })


@login_required
def forum_create_post(request):
    """Create a new forum post, optionally linking a listing."""
    if request.method == 'POST':
        form = ForumPostForm(request.POST, user=request.user)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            # Track forum post count
            request.user.profile.forum_posts_count += 1
            request.user.profile.update_verification_tier()
            request.user.profile.save()
            messages.success(request, 'Post created!')
            return redirect('marketplace:forum_post', pk=post.pk)
    else:
        form = ForumPostForm(user=request.user)

    return render(request, 'marketplace/forum_form.html', {'form': form, 'title': 'New Post'})


# ----- Moderation (Superuser Only) -----

def _superuser_required(view_func):
    """Decorator: require superuser."""
    decorated = login_required(view_func)
    return user_passes_test(lambda u: u.is_superuser)(decorated)


def _has_mod_security_access(user):
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def _record_security_test_event(request, action, result):
    status = (result or {}).get('status', 'warn')
    severity = 'info' if status == 'pass' else 'warning' if status == 'warn' else 'error'
    details = {
        'feature': 'mod_security_testing',
        'action': action,
        'status': status,
        'summary': (result or {}).get('summary', ''),
        'title': (result or {}).get('title', ''),
    }

    demo_report = (result or {}).get('demo_report') or {}
    tests_ran = demo_report.get('tests_ran') or []
    if tests_ran:
        details['tests_ran'] = tests_ran

    result_details = (result or {}).get('details') or []
    if result_details:
        details['result_details'] = result_details

    try:
        AuditLog.objects.create(
            event_type='security_alert',
            severity=severity,
            user=request.user if request.user.is_authenticated else None,
            ip_address=get_client_ip(request) or '127.0.0.1',
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
            resource=request.path,
            details=details,
        )
    except Exception:
        logger.exception('Failed to write security test audit log action=%s', action)


def mod_dashboard(request):
    """Moderation dashboard: overview, quick stats, recent activity."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        messages.error(request, 'Access denied.')
        return redirect('marketplace:home')

    def _admin_url(name: str) -> str:
        for current_app in ('security_admin', None):
            try:
                return reverse(name, current_app=current_app)
            except Exception:
                continue
        return ''

    if request.method == 'POST':
        verification_action = (request.POST.get('verification_action') or '').strip().lower()
        report_action = (request.POST.get('report_action') or '').strip().lower()
        ticket_action = (request.POST.get('ticket_action') or '').strip().lower()

        if verification_action:
            request_id = (request.POST.get('verification_request_id') or '').strip()
            reviewer_notes = (request.POST.get('reviewer_notes') or '').strip()

            if verification_action not in {'approve', 'reject'}:
                messages.error(request, 'Invalid school ID verification action.')
                return redirect('marketplace:mod_dashboard')

            if not request_id.isdigit():
                messages.error(request, 'Invalid verification request ID.')
                return redirect('marketplace:mod_dashboard')

            verification_request = SchoolIDVerificationRequest.objects.select_related(
                'profile__user',
            ).filter(pk=int(request_id)).first()

            if not verification_request:
                messages.error(request, 'School ID verification request not found.')
                return redirect('marketplace:mod_dashboard')

            if verification_request.status != 'pending':
                messages.info(request, 'This verification request was already reviewed.')
                return redirect('marketplace:mod_dashboard')

            if verification_action == 'reject' and not reviewer_notes:
                messages.error(request, 'Reviewer notes are required when rejecting a school ID request.')
                return redirect('marketplace:mod_dashboard')

            if verification_action == 'approve':
                verification_request.approve(reviewer=request.user, notes=reviewer_notes)
                ModerationLog.objects.create(
                    actor=request.user,
                    action='approve_school_id',
                    target_model='school_id_verification_request',
                    target_id=verification_request.pk,
                )
                messages.success(request, f"Approved school ID for {verification_request.profile.user.username}.")
            else:
                verification_request.reject(reviewer=request.user, notes=reviewer_notes)
                ModerationLog.objects.create(
                    actor=request.user,
                    action='reject_school_id',
                    target_model='school_id_verification_request',
                    target_id=verification_request.pk,
                )
                messages.success(request, f"Rejected school ID for {verification_request.profile.user.username}.")

            return redirect('marketplace:mod_dashboard')

        if report_action:
            report_id = (request.POST.get('report_id') or '').strip()
            report_notes = (request.POST.get('report_resolution_notes') or '').strip()

            if report_action not in {'review', 'resolve', 'dismiss'}:
                messages.error(request, 'Invalid report action.')
                return redirect('marketplace:mod_dashboard')

            if not report_id.isdigit():
                messages.error(request, 'Invalid report ID.')
                return redirect('marketplace:mod_dashboard')

            report = UserReport.objects.filter(pk=int(report_id)).first()
            if not report:
                messages.error(request, 'Report not found.')
                return redirect('marketplace:mod_dashboard')

            update_fields = []
            if report_action == 'review':
                report.status = 'reviewing'
                report.resolved_at = None
                report.resolved_by = None
                update_fields.extend(['status', 'resolved_at', 'resolved_by'])
                if report_notes:
                    report.resolution_notes = report_notes
                    update_fields.append('resolution_notes')
                report.save(update_fields=update_fields)
                messages.success(request, f"Report #{report.pk} moved to reviewing.")
            else:
                report.status = 'resolved' if report_action == 'resolve' else 'dismissed'
                report.resolved_at = timezone.now()
                report.resolved_by = request.user
                update_fields.extend(['status', 'resolved_at', 'resolved_by'])
                if report_notes:
                    report.resolution_notes = report_notes
                    update_fields.append('resolution_notes')
                report.save(update_fields=update_fields)
                if report_action == 'resolve':
                    messages.success(request, f"Report #{report.pk} marked as resolved.")
                else:
                    messages.success(request, f"Report #{report.pk} dismissed.")

            return redirect('marketplace:mod_dashboard')

        if ticket_action:
            ticket_id = (request.POST.get('ticket_id') or '').strip()
            ticket_note = (request.POST.get('ticket_internal_notes') or '').strip()

            if ticket_action not in {'assign', 'start', 'resolve', 'close'}:
                messages.error(request, 'Invalid ticket action.')
                return redirect('marketplace:mod_dashboard')

            if not ticket_id.isdigit():
                messages.error(request, 'Invalid ticket ID.')
                return redirect('marketplace:mod_dashboard')

            ticket = SupportTicket.objects.select_related('assigned_to').filter(pk=int(ticket_id)).first()
            if not ticket:
                messages.error(request, 'Ticket not found.')
                return redirect('marketplace:mod_dashboard')

            now_ts = timezone.now()
            update_fields = []

            if ticket_action == 'assign':
                ticket.assigned_to = request.user
                update_fields.append('assigned_to')
                if ticket.status == 'open':
                    ticket.status = 'assigned'
                    update_fields.append('status')
                success_message = f"Ticket #{ticket.pk} assigned to you."
            elif ticket_action == 'start':
                if not ticket.assigned_to:
                    ticket.assigned_to = request.user
                    update_fields.append('assigned_to')
                ticket.status = 'in_progress'
                update_fields.append('status')
                success_message = f"Ticket #{ticket.pk} moved to in progress."
            elif ticket_action == 'resolve':
                if not ticket.assigned_to:
                    ticket.assigned_to = request.user
                    update_fields.append('assigned_to')
                ticket.status = 'resolved'
                ticket.resolved_at = now_ts
                update_fields.extend(['status', 'resolved_at'])
                success_message = f"Ticket #{ticket.pk} marked as resolved."
            else:
                ticket.status = 'closed'
                update_fields.append('status')
                if not ticket.resolved_at:
                    ticket.resolved_at = now_ts
                    update_fields.append('resolved_at')
                success_message = f"Ticket #{ticket.pk} closed."

            if ticket_note:
                note_line = f"[{now_ts:%Y-%m-%d %H:%M}] {request.user.username}: {ticket_note}"
                ticket.internal_notes = f"{ticket.internal_notes}\n\n{note_line}".strip() if ticket.internal_notes else note_line
                update_fields.append('internal_notes')

            unique_fields = list(dict.fromkeys(update_fields))
            ticket.save(update_fields=unique_fields)
            messages.success(request, success_message)
            return redirect('marketplace:mod_dashboard')

        messages.error(request, 'No moderation action was submitted.')
        return redirect('marketplace:mod_dashboard')

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    month_start = today_start - timedelta(days=30)

    # Sales stats
    completed = Transaction.objects.filter(status='completed')
    total_revenue = completed.aggregate(s=Sum('price'))['s'] or 0
    today_revenue = completed.filter(completed_at__gte=today_start).aggregate(s=Sum('price'))['s'] or 0
    week_revenue = completed.filter(completed_at__gte=week_start).aggregate(s=Sum('price'))['s'] or 0
    month_revenue = completed.filter(completed_at__gte=month_start).aggregate(s=Sum('price'))['s'] or 0

    tx_counts = Transaction.objects.values('status').annotate(cnt=Count('id'))
    status_counts = {s['status']: s['cnt'] for s in tx_counts}

    # User stats
    user_count = User.objects.count()
    new_users_week = User.objects.filter(date_joined__gte=week_start).count()

    # Content counts
    listing_count = Listing.objects.filter(is_sold=False).count()
    forum_post_count = ForumPost.objects.filter(is_hidden=False).count()
    hidden_forum_count = ForumPost.objects.filter(is_hidden=True).count() + ForumReply.objects.filter(is_hidden=True).count()

    # Recent moderation log
    recent_logs = ModerationLog.objects.select_related('actor').order_by('-created_at')[:15]
    recent_auth_log_lines = _tail_text_file(settings.BASE_DIR / 'logs' / 'authentication.log', limit=25)
    recent_security_log_lines = _tail_text_file(settings.BASE_DIR / 'logs' / 'security.log', limit=25)

    # Reports / tickets
    reports_open_count = UserReport.objects.filter(status__in=['new', 'reviewing']).count()
    tickets_open_count = SupportTicket.objects.filter(status__in=['open', 'assigned', 'in_progress']).count()
    open_reports = list(UserReport.objects.select_related(
        'reporter',
        'reported_user',
        'content_type',
    ).filter(status__in=['new', 'reviewing']).order_by('-priority', 'created_at')[:8])
    open_tickets = list(SupportTicket.objects.select_related(
        'report__reporter',
        'assigned_to',
    ).filter(status__in=['open', 'assigned', 'in_progress']).order_by('-priority', 'created_at')[:8])
    pending_school_id_requests = list(SchoolIDVerificationRequest.objects.select_related(
        'profile__user',
        'profile__school',
    ).filter(status='pending').order_by('submitted_at')[:12])
    recent_school_id_reviews = list(SchoolIDVerificationRequest.objects.select_related(
        'profile__user',
        'reviewed_by',
    ).exclude(status='pending').order_by('-reviewed_at')[:6])

    reports_admin_url = _admin_url('admin:marketplace_userreport_changelist') or '/admin/marketplace/userreport/'
    tickets_admin_url = _admin_url('admin:marketplace_supportticket_changelist') or '/admin/marketplace/supportticket/'
    school_id_admin_url = _admin_url('admin:marketplace_schoolidverificationrequest_changelist') or '/admin/marketplace/schoolidverificationrequest/'

    return render(request, 'marketplace/mod/dashboard.html', {
        'total_revenue': total_revenue,
        'today_revenue': today_revenue,
        'week_revenue': week_revenue,
        'month_revenue': month_revenue,
        'status_counts': status_counts,
        'user_count': user_count,
        'new_users_week': new_users_week,
        'listing_count': listing_count,
        'forum_post_count': forum_post_count,
        'hidden_forum_count': hidden_forum_count,
        'recent_logs': recent_logs,
        'recent_auth_log_lines': recent_auth_log_lines,
        'recent_security_log_lines': recent_security_log_lines,
        'reports_open_count': reports_open_count,
        'tickets_open_count': tickets_open_count,
        'open_reports': open_reports,
        'open_tickets': open_tickets,
        'pending_school_id_requests': pending_school_id_requests,
        'pending_school_id_count': len(pending_school_id_requests),
        'recent_school_id_reviews': recent_school_id_reviews,
        'reports_admin_url': reports_admin_url,
        'tickets_admin_url': tickets_admin_url,
        'school_id_admin_url': school_id_admin_url,
    })


def mod_sales_analytics(request):
    """Sales analytics with charts."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        messages.error(request, 'Access denied.')
        return redirect('marketplace:home')

    # Last 30 days daily revenue
    days = 30
    daily_data = []
    for i in range(days - 1, -1, -1):
        d = (timezone.now() - timedelta(days=i)).date()
        day_start = timezone.make_aware(datetime.combine(d, datetime.min.time()))
        day_end = day_start + timedelta(days=1)
        rev = Transaction.objects.filter(
            status='completed',
            completed_at__gte=day_start,
            completed_at__lt=day_end
        ).aggregate(s=Sum('price'))['s'] or 0
        daily_data.append({'date': d.isoformat(), 'revenue': float(rev), 'count': Transaction.objects.filter(status='completed', completed_at__gte=day_start, completed_at__lt=day_end).count()})

    # Revenue by category
    by_category = list(Transaction.objects.filter(status='completed', listing__isnull=False).values(
        'listing__category__name'
    ).annotate(revenue=Sum('price'), count=Count('id')).order_by('-revenue')[:10])
    for c in by_category:
        c['revenue'] = float(c['revenue'])

    return render(request, 'marketplace/mod/sales_analytics.html', {
        'daily_data_json': json.dumps(daily_data),
        'by_category_json': json.dumps(by_category),
    })


def mod_forum(request):
    """Forum moderation: list posts and replies."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        messages.error(request, 'Access denied.')
        return redirect('marketplace:home')

    show_hidden = request.GET.get('hidden') == '1'
    posts = ForumPost.objects.select_related('author', 'listing').prefetch_related('replies').order_by('-created_at')
    if show_hidden:
        posts = posts.filter(is_hidden=True)
    else:
        posts = posts.filter(is_hidden=False)[:100]

    return render(request, 'marketplace/mod/forum.html', {
        'posts': posts,
        'show_hidden': show_hidden,
    })


def mod_forum_action(request, content_type, pk):
    """Hide or restore a forum post or reply."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        messages.error(request, 'Access denied.')
        return redirect('marketplace:home')

    if content_type == 'post':
        obj = get_object_or_404(ForumPost, pk=pk)
    elif content_type == 'reply':
        obj = get_object_or_404(ForumReply, pk=pk)
    else:
        messages.error(request, 'Invalid content type.')
        return redirect('marketplace:mod_forum')

    if request.method == 'POST':
        action = request.POST.get('action')
        reason = request.POST.get('reason', '').strip()

        if action == 'hide':
            obj.is_hidden = True
            obj.moderation_notes = reason
            obj.save()
            log_action = 'hide_forum_post' if content_type == 'post' else 'hide_forum_reply'
            ModerationLog.objects.create(actor=request.user, action=log_action, target_model=content_type, target_id=pk)
            messages.success(request, f'{content_type.capitalize()} hidden.')
        elif action == 'restore':
            obj.is_hidden = False
            obj.moderation_notes = ''
            obj.save()
            log_action = 'restore_forum_post' if content_type == 'post' else 'restore_forum_reply'
            ModerationLog.objects.create(actor=request.user, action=log_action, target_model=content_type, target_id=pk)
            messages.success(request, f'{content_type.capitalize()} restored.')

        if content_type == 'post':
            return redirect('marketplace:mod_forum')
        else:
            return redirect('marketplace:forum_post', pk=obj.post_id)

    return redirect('marketplace:mod_forum')


def mod_chat(request):
    """Chat moderation: list conversations."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        messages.error(request, 'Access denied.')
        return redirect('marketplace:home')

    convs = Conversation.objects.prefetch_related('participants', 'messages').order_by('-updated_at')[:80]
    return render(request, 'marketplace/mod/chat.html', {'conversations': convs})


def mod_conversation(request, pk):
    """Admin view of a conversation (all messages, including hidden)."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        messages.error(request, 'Access denied.')
        return redirect('marketplace:home')

    conv = get_object_or_404(Conversation.objects.prefetch_related('participants', 'messages__sender'), pk=pk)
    msgs = conv.messages.select_related('sender').all().order_by('created_at')
    participants = conv.participants.all()

    return render(request, 'marketplace/mod/conversation.html', {
        'conversation': conv,
        'messages': msgs,
        'participants': list(participants),
    })


def mod_message_action(request, pk):
    """Hide or restore a private message."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        messages.error(request, 'Access denied.')
        return redirect('marketplace:home')

    msg = get_object_or_404(Message, pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action')
        reason = request.POST.get('reason', '').strip()

        if action == 'hide':
            msg.is_hidden = True
            msg.moderation_notes = reason
            msg.save()
            ModerationLog.objects.create(actor=request.user, action='hide_message', target_model='message', target_id=pk)
            messages.success(request, 'Message hidden.')
        elif action == 'restore':
            msg.is_hidden = False
            msg.moderation_notes = ''
            msg.save()
            ModerationLog.objects.create(actor=request.user, action='restore_message', target_model='message', target_id=pk)
            messages.success(request, 'Message restored.')

        return redirect('marketplace:mod_conversation', pk=msg.conversation_id)

    return redirect('marketplace:mod_chat')


def mod_transactions(request):
    """Transaction oversight: list all, filter by status."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        messages.error(request, 'Access denied.')
        return redirect('marketplace:home')

    qs = Transaction.objects.select_related('buyer', 'seller', 'listing').order_by('-created_at')
    status_filter = request.GET.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)
    if request.GET.get('flagged') == '1':
        qs = qs.filter(flagged_for_review=True)
    transactions = qs[:100]

    return render(request, 'marketplace/mod/transactions.html', {
        'transactions': transactions,
        'status_filter': status_filter,
        'flagged_filter': request.GET.get('flagged') == '1',
    })


def mod_transaction_detail(request, transaction_id):
    """Admin view of transaction: add notes, flag, cancel with reason."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        messages.error(request, 'Access denied.')
        return redirect('marketplace:home')

    transaction = get_object_or_404(
        Transaction.objects.select_related('buyer', 'seller', 'listing', 'admin_cancelled_by'),
        pk=transaction_id
    )
    txn_messages = transaction.messages.select_related('sender').all().order_by('created_at')
    buyer_profile = getattr(transaction.buyer, 'profile', None) or Profile.objects.filter(user=transaction.buyer).first()
    seller_profile = getattr(transaction.seller, 'profile', None) or Profile.objects.filter(user=transaction.seller).first()
    payment = getattr(transaction, 'payment', None)
    manual_review_pending = bool(
        payment
        and payment.status == 'pending'
        and payment.manual_verification_status == 'awaiting_moderator_review'
        and _is_manual_payment_method(payment.payment_method)
    )

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_note':
            transaction.admin_notes = request.POST.get('admin_notes', '')
            transaction.save()
            ModerationLog.objects.create(actor=request.user, action='add_transaction_note', target_model='transaction', target_id=transaction_id)
            messages.success(request, 'Note saved.')
        elif action == 'flag':
            transaction.flagged_for_review = True
            transaction.save()
            ModerationLog.objects.create(actor=request.user, action='flag_transaction', target_model='transaction', target_id=transaction_id)
            messages.success(request, 'Transaction flagged for review.')
        elif action == 'unflag':
            transaction.flagged_for_review = False
            transaction.save()
            ModerationLog.objects.create(actor=request.user, action='unflag_transaction', target_model='transaction', target_id=transaction_id)
            messages.success(request, 'Flag removed.')
        elif action == 'approve_manual_payment':
            payment_obj = payment
            if not manual_review_pending or payment_obj is None:
                messages.error(request, 'No pending manual payment review found for this transaction.')
            elif payment_obj.payment_method == 'in_person' and not _in_person_meetup_proof_ready(payment_obj):
                messages.error(request, 'Cannot approve until both in-person meetup photo proofs are present.')
            elif payment_obj.payment_method == 'third_party_delivery' and (
                not _third_party_tracking_link_ready(payment_obj)
                or not _third_party_tracking_ack_ready(payment_obj)
            ):
                messages.error(
                    request,
                    'Cannot approve third-party delivery payment until tracking link submission and both acknowledgments are complete.',
                )
            else:
                review_reason = (request.POST.get('manual_review_reason') or '').strip()
                previous_payment_status = payment_obj.status
                previous_manual_status = payment_obj.manual_verification_status
                payment_obj.status = 'completed'
                payment_obj.manual_verification_status = 'verified'
                payment_obj.verified_at = timezone.now()
                payment_obj.verified_by = request.user

                update_fields = [
                    'status',
                    'manual_verification_status',
                    'verified_at',
                    'verified_by',
                    'updated_at',
                ]

                if review_reason:
                    note_line = f"Moderator approval: {review_reason}"
                    payment_obj.manual_evidence_notes = (
                        (payment_obj.manual_evidence_notes + "\n") if payment_obj.manual_evidence_notes else ""
                    ) + note_line
                    update_fields.append('manual_evidence_notes')

                payment_obj.save(update_fields=update_fields)

                if previous_manual_status != payment_obj.manual_verification_status:
                    _record_state_transition(
                        request,
                        entity_type='payment',
                        transition_kind='manual_verification',
                        transaction=transaction,
                        payment=payment_obj,
                        from_state=previous_manual_status,
                        to_state=payment_obj.manual_verification_status,
                        reason='moderator_approved_manual_payment',
                        evidence_hash=payment_obj.manual_evidence_hash,
                        details={'review_reason': review_reason},
                    )

                if previous_payment_status != payment_obj.status:
                    _record_state_transition(
                        request,
                        entity_type='payment',
                        transition_kind='payment_status',
                        transaction=transaction,
                        payment=payment_obj,
                        from_state=previous_payment_status,
                        to_state=payment_obj.status,
                        reason='moderator_approved_manual_payment',
                        evidence_hash=payment_obj.manual_evidence_hash,
                        details={'review_reason': review_reason},
                    )

                receipt = _ensure_receipt_for_payment(transaction, payment_obj)
                if receipt.status == 'pending':
                    receipt.status = 'confirmed'
                    receipt.confirmed_at = timezone.now()
                    receipt.save(update_fields=['status', 'confirmed_at'])

                Notification.objects.create(
                    user=transaction.buyer,
                    related_user=request.user,
                    message='A moderator approved your manual payment verification. You may continue to transaction completion.',
                    notification_type='transaction',
                    url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
                )
                Notification.objects.create(
                    user=transaction.seller,
                    related_user=request.user,
                    message='A moderator approved this manual payment verification.',
                    notification_type='transaction',
                    url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
                )

                ModerationLog.objects.create(
                    actor=request.user,
                    action='approve_manual_payment',
                    target_model='payment',
                    target_id=payment_obj.pk,
                )
                messages.success(request, 'Manual payment approved and marked completed.')
        elif action == 'reject_manual_payment':
            payment_obj = payment
            if not manual_review_pending or payment_obj is None:
                messages.error(request, 'No pending manual payment review found for this transaction.')
            else:
                rejection_reason = (request.POST.get('manual_review_reason') or '').strip()
                if len(rejection_reason) < 12:
                    messages.error(request, 'Please provide a detailed rejection reason (at least 12 characters).')
                else:
                    previous_payment_status = payment_obj.status
                    previous_manual_status = payment_obj.manual_verification_status
                    payment_obj.status = 'failed'
                    payment_obj.manual_verification_status = 'rejected'
                    payment_obj.verified_at = timezone.now()
                    payment_obj.verified_by = request.user
                    note_line = f"Moderator rejection: {rejection_reason}"
                    payment_obj.manual_evidence_notes = (
                        (payment_obj.manual_evidence_notes + "\n") if payment_obj.manual_evidence_notes else ""
                    ) + note_line
                    payment_obj.save(
                        update_fields=[
                            'status',
                            'manual_verification_status',
                            'verified_at',
                            'verified_by',
                            'manual_evidence_notes',
                            'updated_at',
                        ]
                    )

                    if previous_manual_status != payment_obj.manual_verification_status:
                        _record_state_transition(
                            request,
                            entity_type='payment',
                            transition_kind='manual_verification',
                            transaction=transaction,
                            payment=payment_obj,
                            from_state=previous_manual_status,
                            to_state=payment_obj.manual_verification_status,
                            reason='moderator_rejected_manual_payment',
                            evidence_hash=payment_obj.manual_evidence_hash,
                            details={'rejection_reason': rejection_reason},
                        )

                    if previous_payment_status != payment_obj.status:
                        _record_state_transition(
                            request,
                            entity_type='payment',
                            transition_kind='payment_status',
                            transaction=transaction,
                            payment=payment_obj,
                            from_state=previous_payment_status,
                            to_state=payment_obj.status,
                            reason='moderator_rejected_manual_payment',
                            evidence_hash=payment_obj.manual_evidence_hash,
                            details={'rejection_reason': rejection_reason},
                        )

                    receipt = getattr(payment_obj, 'receipt', None)
                    if receipt and receipt.status == 'pending':
                        receipt.status = 'failed'
                        receipt.save(update_fields=['status'])

                    Notification.objects.create(
                        user=transaction.buyer,
                        related_user=request.user,
                        message='A moderator rejected your manual payment verification. Please resubmit valid payment evidence.',
                        notification_type='transaction',
                        url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
                    )
                    Notification.objects.create(
                        user=transaction.seller,
                        related_user=request.user,
                        message='A moderator rejected this manual payment verification. Buyer must resubmit payment evidence.',
                        notification_type='transaction',
                        url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk}),
                    )

                    ModerationLog.objects.create(
                        actor=request.user,
                        action='reject_manual_payment',
                        target_model='payment',
                        target_id=payment_obj.pk,
                    )
                    messages.success(request, 'Manual payment verification rejected.')
        elif action == 'admin_cancel' and transaction.status in ('pending', 'confirmed'):
            reason = request.POST.get('admin_cancel_reason', '').strip()
            if not reason:
                messages.error(request, 'Please provide a reason for admin cancellation (audit trail).')
            else:
                transaction.status = 'cancelled'
                transaction.admin_cancelled_at = timezone.now()
                transaction.admin_cancel_reason = reason
                transaction.admin_cancelled_by = request.user
                transaction.save()
                ModerationLog.objects.create(actor=request.user, action='admin_cancel_transaction', target_model='transaction', target_id=transaction_id)
                messages.success(request, 'Transaction cancelled by admin. Reason logged for audit.')
        return redirect('marketplace:mod_transaction_detail', transaction_id=transaction_id)

    return render(request, 'marketplace/mod/transaction_detail.html', {
        'transaction': transaction,
        'payment': payment,
        'manual_review_pending': manual_review_pending,
        'txn_messages': txn_messages,
        'buyer_profile': buyer_profile,
        'seller_profile': seller_profile,
    })


def mod_users(request):
    """User analytics and charts."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        messages.error(request, 'Access denied.')
        return redirect('marketplace:home')

    # Registration over time (last 30 days)
    days = 30
    signup_data = []
    for i in range(days - 1, -1, -1):
        d = (timezone.now() - timedelta(days=i)).date()
        day_start = timezone.make_aware(datetime.combine(d, datetime.min.time()))
        day_end = day_start + timedelta(days=1)
        cnt = User.objects.filter(date_joined__gte=day_start, date_joined__lt=day_end).count()
        signup_data.append({'date': d.isoformat(), 'count': cnt})

    total_users = User.objects.count()
    users_with_listings = User.objects.filter(listings__isnull=False).distinct().count()
    users_with_purchases = Transaction.objects.filter(status='completed').values('buyer').distinct().count()

    return render(request, 'marketplace/mod/users.html', {
        'signup_data_json': json.dumps(signup_data),
        'total_users': total_users,
        'users_with_listings': users_with_listings,
        'users_with_purchases': users_with_purchases,
    })


def mod_log(request):
    """Moderation audit log."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        messages.error(request, 'Access denied.')
        return redirect('marketplace:home')

    logs = ModerationLog.objects.select_related('actor').order_by('-created_at')[:100]
    recent_auth_log_lines = _tail_text_file(settings.BASE_DIR / 'logs' / 'authentication.log', limit=40)
    recent_security_log_lines = _tail_text_file(settings.BASE_DIR / 'logs' / 'security.log', limit=40)
    return render(request, 'marketplace/mod/mod_log.html', {
        'logs': logs,
        'recent_auth_log_lines': recent_auth_log_lines,
        'recent_security_log_lines': recent_security_log_lines,
    })


def mod_security_probe(request):
    """Probe endpoint intentionally protected by CSRF for active checks."""
    if not _has_mod_security_access(request.user):
        return HttpResponseForbidden('Access denied.')

    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    return JsonResponse({'ok': True, 'message': 'Probe accepted with valid CSRF'})


def mod_security_tests(request):
    """Staff-accessible security testing lab for demonstration checks."""
    if not _has_mod_security_access(request.user):
        messages.error(request, 'Access denied.')
        return redirect('marketplace:home')

    def _admin_url(name: str) -> str:
        for current_app in ('security_admin', None):
            try:
                return reverse(name, current_app=current_app)
            except Exception:
                continue
        return ''

    context = build_security_test_context(request)
    context['active_result'] = None
    context['security_audit_output'] = ''
    context['admin_security_urls'] = {
        'security_dashboard': _admin_url('admin:security_dashboard') or '/admin/security/',
        'compliance': _admin_url('admin:compliance') or '/admin/security/compliance/',
        'audit_logs': _admin_url('admin:audit_logs') or '/admin/security/audit-logs/',
    }

    if request.method == 'GET':
        _record_security_test_event(
            request,
            'view_security_testing_lab',
            {
                'title': 'Security testing lab viewed',
                'status': 'pass',
                'summary': 'User opened the moderator security testing lab page.',
            },
        )

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        if action == 'run_security_audit':
            output = io.StringIO()
            try:
                call_command('run_security_audit', stdout=output, no_color=True)
                clean_output = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', output.getvalue())
                context['security_audit_output'] = clean_output.strip()
                result = {
                    'title': 'Security audit command',
                    'status': 'pass',
                    'summary': 'Security audit command ran successfully.',
                    'details': [
                        {'label': 'Command', 'value': 'run_security_audit'},
                        {'label': 'Output length', 'value': str(len(context['security_audit_output']))},
                    ],
                }
            except Exception as exc:
                context['security_audit_output'] = str(exc)
                result = {
                    'title': 'Security audit command',
                    'status': 'fail',
                    'summary': 'Security audit command failed.',
                    'details': [
                        {'label': 'Error', 'value': str(exc)},
                    ],
                }
        else:
            result = run_active_security_check(action, request, csrf_probe_view=mod_security_probe)

        context['active_result'] = result
        _record_security_test_event(request, action, result)

    return render(request, 'marketplace/mod/security_tests.html', context)


@login_required
def add_social_media(request):
    """Add a social media account to user's profile (AJAX)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        platform = data.get('platform', '').lower().strip()
        handle = data.get('handle', '').strip()
        
        if not platform or not handle:
            return JsonResponse({'error': 'Platform and handle are required'}, status=400)
        
        profile = request.user.profile
        
        # Check if platform choice is valid
        valid_platforms = [choice[0] for choice in SocialMedia.PLATFORM_CHOICES]
        if platform not in valid_platforms:
            return JsonResponse({'error': 'Invalid platform'}, status=400)
        
        # Create or update social media account
        social_media, created = SocialMedia.objects.update_or_create(
            profile=profile,
            platform=platform,
            defaults={'handle': handle}
        )
        
        return JsonResponse({
            'success': True,
            'platform': social_media.get_platform_display(),
            'handle': social_media.handle,
            'url': social_media.get_url(),
            'is_new': created
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)



@login_required
def remove_social_media(request, platform):
    """Remove a social media account from user's profile (AJAX)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        profile = request.user.profile
        platform = platform.lower().strip()
        
        # Delete the social media account
        deleted, _ = SocialMedia.objects.filter(profile=profile, platform=platform).delete()
        
        if deleted:
            return JsonResponse({'success': True, 'message': 'Removed successfully'})
        else:
            return JsonResponse({'error': 'Account not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def get_social_media(request):
    """Get all social media accounts for current user (AJAX)."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        profile = request.user.profile
        social_accounts = SocialMedia.objects.filter(profile=profile).values('platform', 'handle')
        
        accounts = []
        for account in social_accounts:
            platform = account['platform']
            platform_display = dict(SocialMedia.PLATFORM_CHOICES).get(platform, platform)
            social_obj = SocialMedia.objects.get(profile=profile, platform=platform)
            accounts.append({
                'platform': platform,
                'platform_display': platform_display,
                'handle': account['handle'],
                'url': social_obj.get_url()
            })
        
        return JsonResponse({'success': True, 'accounts': accounts})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ==================== PAYMENT VIEWS ====================

PENDING_SENSITIVE_PAYMENT_SESSION_KEY = 'pending_sensitive_payment_action'
MANUAL_PAYMENT_METHODS = {'gcash', 'bank_transfer', 'in_person', 'third_party_delivery', 'other'}
MANUAL_EVIDENCE_TYPES = {
    'gcash_reference',
    'bank_reference',
    'cash_receipt',
    'delivery_tracking',
    'chat_confirmation',
    'other',
}
THIRD_PARTY_PROVIDER_CODES = {'lalamove', 'grab', 'other'}
THIRD_PARTY_PROVIDER_DOMAINS = {
    'lalamove': ('lalamove.com',),
    'grab': ('grab.com', 'grabtaxi.com'),
}


def _is_manual_payment_method(payment_method):
    return payment_method in MANUAL_PAYMENT_METHODS


def _manual_payment_review_threshold():
    raw_threshold = getattr(settings, 'MANUAL_PAYMENT_MOD_REVIEW_THRESHOLD', '5000.00')
    try:
        return Decimal(str(raw_threshold))
    except Exception:
        return Decimal('5000.00')


def _manual_payment_requires_moderator_review(payment):
    if payment is None or not _is_manual_payment_method(payment.payment_method):
        return False

    # Maximum-safety policy: every manual payment is moderator-gated regardless of amount.
    return True


def _is_valid_tracking_link(link, provider=''):
    cleaned_link = (link or '').strip()
    if len(cleaned_link) < 20 or len(cleaned_link) > 500:
        return False, 'Tracking link must be between 20 and 500 characters.'

    try:
        parsed = urlparse(cleaned_link)
    except Exception:
        return False, 'Tracking link format is invalid.'

    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return False, 'Tracking link must be a valid http/https URL.'

    provider_code = (provider or '').strip().lower()
    if provider_code in THIRD_PARTY_PROVIDER_DOMAINS:
        host = parsed.netloc.lower()
        allowed_domains = THIRD_PARTY_PROVIDER_DOMAINS[provider_code]
        if not any(host.endswith(domain) for domain in allowed_domains):
            return False, f'Tracking link must match the selected provider ({provider_code}).'

    return True, ''


def _third_party_tracking_link_ready(payment):
    if payment is None or payment.payment_method != 'third_party_delivery':
        return True
    return bool(payment.third_party_tracking_link and payment.third_party_tracking_link_submitted_by)


def _third_party_tracking_ack_ready(payment):
    if payment is None or payment.payment_method != 'third_party_delivery':
        return True
    return bool(payment.buyer_tracking_acknowledged_at and payment.seller_tracking_acknowledged_at)


def _in_person_meetup_proof_ready(payment):
    if payment is None or payment.payment_method != 'in_person':
        return True
    return bool(payment.buyer_meetup_photo and payment.seller_meetup_photo)


def _ensure_receipt_for_payment(transaction, payment):
    receipt = _create_receipt(transaction, payment)
    update_fields = []

    if getattr(receipt, 'payment', None) != payment:
        receipt.payment = payment
        update_fields.append('payment')

    if receipt.payment_method != payment.payment_method:
        receipt.payment_method = payment.payment_method
        update_fields.append('payment_method')

    if update_fields:
        receipt.save(update_fields=update_fields)

    return receipt


def _build_manual_evidence_hash(transaction, payment, evidence_type, evidence_reference, evidence_notes):
    raw = "|".join([
        str(transaction.pk),
        str(payment.pk),
        evidence_type.strip().lower(),
        evidence_reference.strip(),
        evidence_notes.strip(),
    ])
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _record_state_transition(
    request,
    *,
    entity_type,
    transition_kind,
    transaction,
    to_state,
    payment=None,
    from_state='',
    reason='',
    evidence_hash='',
    details=None,
):
    details = details or {}
    actor = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None

    StateTransitionAuditLog.objects.create(
        entity_type=entity_type,
        transition_kind=transition_kind,
        transaction=transaction,
        payment=payment,
        actor=actor,
        from_state=from_state or '',
        to_state=to_state,
        reason=reason or '',
        evidence_hash=evidence_hash or '',
        details=details,
        ip_address=get_client_ip(request),
        user_agent=(request.META.get('HTTP_USER_AGENT', '') or '')[:255],
    )


def _normalize_whitespace(value):
    return re.sub(r'\s+', ' ', (value or '').strip())


def _validate_gcash_details(raw_details):
    raw_details = raw_details or {}
    gcash_name = _normalize_whitespace(raw_details.get('gcash_name'))
    gcash_number_raw = re.sub(r'\D', '', raw_details.get('gcash_number') or '')

    if gcash_number_raw.startswith('63') and len(gcash_number_raw) == 12:
        gcash_number = f"0{gcash_number_raw[2:]}"
    elif gcash_number_raw.startswith('09') and len(gcash_number_raw) == 11:
        gcash_number = gcash_number_raw
    else:
        return None, 'GCash number must be a valid Philippine mobile number (for example 09XXXXXXXXX).'

    if len(gcash_name) < 3 or len(gcash_name) > 120:
        return None, 'GCash account name must be between 3 and 120 characters.'

    if not re.fullmatch(r"[A-Za-z0-9 .,'\-]+", gcash_name):
        return None, 'GCash account name contains unsupported characters.'

    return {
        'gcash_name': gcash_name,
        'gcash_number': gcash_number,
    }, ''


def _validate_bank_details(raw_details):
    raw_details = raw_details or {}
    bank_name = _normalize_whitespace(raw_details.get('bank_name'))
    bank_account_name = _normalize_whitespace(raw_details.get('bank_account_name'))
    bank_account_last4 = re.sub(r'\s+', '', raw_details.get('bank_account_last4') or '')

    if len(bank_name) < 2 or len(bank_name) > 80:
        return None, 'Bank name must be between 2 and 80 characters.'
    if not re.fullmatch(r"[A-Za-z0-9 .,&()'\-]+", bank_name):
        return None, 'Bank name contains unsupported characters.'

    if len(bank_account_name) < 3 or len(bank_account_name) > 120:
        return None, 'Bank account name must be between 3 and 120 characters.'
    if not re.fullmatch(r"[A-Za-z0-9 .,'\-]+", bank_account_name):
        return None, 'Bank account name contains unsupported characters.'

    if bank_account_last4 and not re.fullmatch(r'\d{4}', bank_account_last4):
        return None, 'Bank account last 4 digits must contain exactly 4 numbers.'

    return {
        'bank_name': bank_name,
        'bank_account_name': bank_account_name,
        'bank_account_last4': bank_account_last4,
    }, ''


def _validate_other_arrangement_details(arrangement_details):
    cleaned = _normalize_whitespace(arrangement_details)
    if len(cleaned) < 20 or len(cleaned) > 600:
        return '', 'Custom arrangement details must be between 20 and 600 characters.'
    if len(cleaned.split()) < 4:
        return '', 'Provide clearer arrangement details with at least 4 words.'
    return cleaned, ''


def _external_verify_gcash_reference(reference, evidence_notes):
    return {
        'provider': 'gcash',
        'status': 'not_configured',
        'message': 'GCash external verification adapter is phase-ready but not connected to a live provider.',
        'reference_tail': reference[-6:],
    }


def _external_verify_bank_reference(reference, evidence_notes):
    return {
        'provider': 'bank_transfer',
        'status': 'not_configured',
        'message': 'Bank transfer external verification adapter is phase-ready but not connected to a live provider.',
        'reference_tail': reference[-6:],
    }


def _run_external_manual_verification(payment_method, evidence_reference, evidence_notes):
    if payment_method == 'gcash':
        return _external_verify_gcash_reference(evidence_reference, evidence_notes)
    if payment_method == 'bank_transfer':
        return _external_verify_bank_reference(evidence_reference, evidence_notes)
    return {
        'provider': payment_method,
        'status': 'not_applicable',
        'message': 'No external verification adapter configured for this method.',
    }


def _stripe_event_already_processed(event_id):
    if not event_id:
        return False
    return StateTransitionAuditLog.objects.filter(
        entity_type='payment',
        transition_kind='payment_status',
        reason='stripe_webhook_payment_intent_succeeded',
        details__stripe_event_id=event_id,
    ).exists()


def _transaction_amount_cents(transaction):
    try:
        return int(Decimal(str(transaction.price)) * Decimal('100'))
    except Exception:
        return None


def _ensure_credit_card_pending_record(request, transaction, payment_intent_id, *, reason, details=None):
    details = details or {}
    existing_payment = Payment.objects.filter(transaction=transaction).first()
    previous_payment_status = existing_payment.status if existing_payment else ''
    previous_manual_status = existing_payment.manual_verification_status if existing_payment else ''

    payment, _ = Payment.objects.update_or_create(
        transaction=transaction,
        defaults={
            'stripe_charge_id': payment_intent_id,
            'amount': transaction.price,
            'status': 'pending',
            'payment_method': 'credit_card',
            'manual_verification_status': 'not_required',
            'manual_evidence_type': '',
            'manual_evidence_reference': '',
            'manual_evidence_notes': '',
            'manual_evidence_hash': '',
            'seller_acknowledged_at': None,
            'seller_acknowledged_by': None,
            'verified_at': None,
            'verified_by': None,
        },
    )

    if previous_manual_status != payment.manual_verification_status:
        _record_state_transition(
            request,
            entity_type='payment',
            transition_kind='manual_verification',
            transaction=transaction,
            payment=payment,
            from_state=previous_manual_status,
            to_state=payment.manual_verification_status,
            reason=reason,
            details=details,
        )

    if previous_payment_status != payment.status:
        _record_state_transition(
            request,
            entity_type='payment',
            transition_kind='payment_status',
            transaction=transaction,
            payment=payment,
            from_state=previous_payment_status,
            to_state=payment.status,
            reason=reason,
            details=details,
        )

    receipt = _ensure_receipt_for_payment(transaction, payment)
    receipt_updates = []
    if receipt.status != 'pending':
        receipt.status = 'pending'
        receipt_updates.append('status')
    if receipt.confirmed_at is not None:
        receipt.confirmed_at = None
        receipt_updates.append('confirmed_at')
    if receipt_updates:
        receipt.save(update_fields=receipt_updates)

    return payment, receipt


def _complete_credit_card_payment_record(request, transaction, payment, *, reason, details=None):
    details = details or {}
    previous_payment_status = payment.status
    previous_manual_status = payment.manual_verification_status
    now = timezone.now()

    payment.status = 'completed'
    payment.payment_method = 'credit_card'
    payment.manual_verification_status = 'not_required'
    payment.manual_evidence_type = ''
    payment.manual_evidence_reference = ''
    payment.manual_evidence_notes = ''
    payment.manual_evidence_hash = ''
    payment.seller_acknowledged_at = None
    payment.seller_acknowledged_by = None
    payment.verified_at = now
    payment.verified_by = None
    payment.save(
        update_fields=[
            'status',
            'payment_method',
            'manual_verification_status',
            'manual_evidence_type',
            'manual_evidence_reference',
            'manual_evidence_notes',
            'manual_evidence_hash',
            'seller_acknowledged_at',
            'seller_acknowledged_by',
            'verified_at',
            'verified_by',
            'updated_at',
        ]
    )

    if previous_manual_status != payment.manual_verification_status:
        _record_state_transition(
            request,
            entity_type='payment',
            transition_kind='manual_verification',
            transaction=transaction,
            payment=payment,
            from_state=previous_manual_status,
            to_state=payment.manual_verification_status,
            reason=reason,
            details=details,
        )

    if previous_payment_status != payment.status:
        _record_state_transition(
            request,
            entity_type='payment',
            transition_kind='payment_status',
            transaction=transaction,
            payment=payment,
            from_state=previous_payment_status,
            to_state=payment.status,
            reason=reason,
            details=details,
        )

    receipt = _ensure_receipt_for_payment(transaction, payment)
    receipt_updates = []
    if receipt.status != 'confirmed':
        receipt.status = 'confirmed'
        receipt_updates.append('status')
    if receipt.confirmed_at is None:
        receipt.confirmed_at = now
        receipt_updates.append('confirmed_at')
    if receipt_updates:
        receipt.save(update_fields=receipt_updates)

    if previous_payment_status != 'completed':
        Notification.objects.create(
            user=transaction.seller,
            related_user=transaction.buyer,
            message=(
                f'{transaction.buyer.username} paid P{transaction.price} via credit card for '
                f'{transaction.listing.title if transaction.listing else "your item"}.'
            ),
            notification_type='transaction',
            url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.id}),
        )

    return receipt


def _start_sensitive_payment_step_up(request, transaction_id, action_payload):
    request.session[PENDING_SENSITIVE_PAYMENT_SESSION_KEY] = action_payload
    set_next_url(
        request.session,
        reverse('marketplace:payment_finalize_pending', kwargs={'transaction_id': transaction_id}),
        purpose='sensitive_action',
    )
    messages.info(
        request,
        'For your security, verify this payment action with the code sent to your email before we finalize it.'
    )
    return redirect('account_email_2fa_sensitive_verify')


def _finalize_credit_card_payment(request, transaction, payment_intent_id):
    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)

        # Verify this PaymentIntent belongs to the correct transaction (prevent spoofing)
        metadata = getattr(intent, 'metadata', {})
        try:
            metadata_dict = dict(metadata) if metadata is not None else {}
        except Exception:
            metadata_dict = {}
        tx_meta = metadata_dict.get('transaction_id')
        if tx_meta and tx_meta != str(transaction.id):
            messages.error(request, "Payment reference mismatch. Please contact support.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction.id)

        expected_amount = _transaction_amount_cents(transaction)
        intent_amount = getattr(intent, 'amount_received', None) or getattr(intent, 'amount', None)
        intent_currency = (getattr(intent, 'currency', '') or '').lower()
        if expected_amount is None or intent_amount != expected_amount or intent_currency != 'php':
            messages.error(request, "Payment reference mismatch. Please contact support.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction.id)

        webhook_required = bool(getattr(settings, 'STRIPE_WEBHOOK_REQUIRED', False))
        webhook_secret_configured = bool(getattr(settings, 'STRIPE_WEBHOOK_SECRET', ''))

        if intent.status == 'succeeded':
            payment, _ = _ensure_credit_card_pending_record(
                request,
                transaction,
                intent.id,
                reason='stripe_client_finalize_pending',
                details={
                    'payment_intent_id': intent.id,
                    'source': 'client_finalize',
                },
            )

            if webhook_required:
                if not webhook_secret_configured:
                    messages.error(
                        request,
                        'Card verification is configured to require webhooks, but STRIPE_WEBHOOK_SECRET is not set.',
                    )
                    return redirect('marketplace:payment_cancel', transaction_id=transaction.id)

                messages.info(
                    request,
                    'Card authorization received. Final payment confirmation is pending signed webhook verification.',
                )
                return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

            receipt = _complete_credit_card_payment_record(
                request,
                transaction,
                payment,
                reason='stripe_payment_intent_succeeded',
                details={
                    'payment_intent_id': intent.id,
                    'source': 'client_finalize',
                },
            )
            messages.success(request, "Payment successful! Your receipt has been saved to your inbox.")
            return redirect('marketplace:receipt_detail', receipt_id=receipt.id)

        if webhook_required and intent.status in {'processing', 'requires_capture'}:
            _ensure_credit_card_pending_record(
                request,
                transaction,
                intent.id,
                reason='stripe_client_finalize_processing',
                details={
                    'payment_intent_id': intent.id,
                    'status': intent.status,
                    'source': 'client_finalize',
                },
            )
            messages.info(
                request,
                'Card payment is processing. Final confirmation will be applied after signed webhook verification.',
            )
            return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

        messages.error(request, f"Payment not completed. Status: {intent.status}")
        return redirect('marketplace:payment_cancel', transaction_id=transaction.id)

    except stripe.error.CardError as e:
        messages.error(request, f"Card error: {e.user_message}")
        return redirect('marketplace:payment_cancel', transaction_id=transaction.id)
    except stripe.error.StripeError as e:
        messages.error(request, f"Payment error: {str(e)}")
        return redirect('marketplace:payment_cancel', transaction_id=transaction.id)


def _finalize_gcash_payment(request, transaction, buyer_details):
    validated_details, validation_error = _validate_gcash_details(buyer_details)
    if validation_error:
        messages.error(request, validation_error)
        return redirect('marketplace:payment_checkout', transaction_id=transaction.id)

    existing_payment = Payment.objects.filter(transaction=transaction).first()
    previous_payment_status = existing_payment.status if existing_payment else ''
    previous_manual_status = existing_payment.manual_verification_status if existing_payment else ''

    payment, created = Payment.objects.update_or_create(
        transaction=transaction,
        defaults={
            'stripe_charge_id': f'gcash_{transaction.id}_{timezone.now().timestamp()}',
            'amount': transaction.price,
            'status': 'pending',
            'payment_method': 'gcash',
            'manual_verification_status': 'submitted',
            'manual_evidence_type': '',
            'manual_evidence_reference': '',
            'manual_evidence_notes': '',
            'manual_evidence_hash': '',
            'seller_acknowledged_at': None,
            'seller_acknowledged_by': None,
            'verified_at': None,
            'verified_by': None,
        }
    )

    if previous_manual_status != payment.manual_verification_status:
        _record_state_transition(
            request,
            entity_type='payment',
            transition_kind='manual_verification',
            transaction=transaction,
            payment=payment,
            from_state=previous_manual_status,
            to_state=payment.manual_verification_status,
            reason='manual_payment_submitted',
            details={'payment_method': 'gcash'},
        )

    if previous_payment_status != payment.status:
        _record_state_transition(
            request,
            entity_type='payment',
            transition_kind='payment_status',
            transaction=transaction,
            payment=payment,
            from_state=previous_payment_status,
            to_state=payment.status,
            reason='manual_payment_submitted',
            details={'payment_method': 'gcash'},
        )

    receipt = _create_receipt(transaction, payment)
    receipt.status = 'pending'
    receipt.confirmed_at = None
    if validated_details:
        parts = []
        if validated_details.get('gcash_name'):
            parts.append(f"Name: {validated_details.get('gcash_name')}")
        if validated_details.get('gcash_number'):
            parts.append(f"Number: {validated_details.get('gcash_number')}")
        if parts:
            receipt.notes = (receipt.notes or '').strip()
            receipt.notes = (receipt.notes + "\n" if receipt.notes else "") + "GCash details (buyer): " + ", ".join(parts)
    receipt.save()

    Notification.objects.create(
        user=transaction.seller,
        related_user=transaction.buyer,
        message=f'{transaction.buyer.username} submitted GCash payment details for ₱{transaction.price}. Please confirm receipt.',
        notification_type='transaction',
        url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.id}),
    )

    messages.success(request, "GCash submission recorded. Your receipt has been saved and is awaiting seller confirmation.")
    return redirect('marketplace:receipt_detail', receipt_id=receipt.id)


def _finalize_bank_transfer_payment(request, transaction, buyer_details):
    validated_details, validation_error = _validate_bank_details(buyer_details)
    if validation_error:
        messages.error(request, validation_error)
        return redirect('marketplace:payment_checkout', transaction_id=transaction.id)

    existing_payment = Payment.objects.filter(transaction=transaction).first()
    previous_payment_status = existing_payment.status if existing_payment else ''
    previous_manual_status = existing_payment.manual_verification_status if existing_payment else ''

    payment, created = Payment.objects.update_or_create(
        transaction=transaction,
        defaults={
            'stripe_charge_id': f'bank_{transaction.id}_{timezone.now().timestamp()}',
            'amount': transaction.price,
            'status': 'pending',  # Pending until seller confirms receipt
            'payment_method': 'bank_transfer',
            'manual_verification_status': 'submitted',
            'manual_evidence_type': '',
            'manual_evidence_reference': '',
            'manual_evidence_notes': '',
            'manual_evidence_hash': '',
            'seller_acknowledged_at': None,
            'seller_acknowledged_by': None,
            'verified_at': None,
            'verified_by': None,
        }
    )

    if previous_manual_status != payment.manual_verification_status:
        _record_state_transition(
            request,
            entity_type='payment',
            transition_kind='manual_verification',
            transaction=transaction,
            payment=payment,
            from_state=previous_manual_status,
            to_state=payment.manual_verification_status,
            reason='manual_payment_submitted',
            details={'payment_method': 'bank_transfer'},
        )

    if previous_payment_status != payment.status:
        _record_state_transition(
            request,
            entity_type='payment',
            transition_kind='payment_status',
            transaction=transaction,
            payment=payment,
            from_state=previous_payment_status,
            to_state=payment.status,
            reason='manual_payment_submitted',
            details={'payment_method': 'bank_transfer'},
        )

    receipt = _create_receipt(transaction, payment)
    receipt.status = 'pending'
    if validated_details:
        parts = []
        if validated_details.get('bank_name'):
            parts.append(f"Bank: {validated_details.get('bank_name')}")
        if validated_details.get('bank_account_name'):
            parts.append(f"Name: {validated_details.get('bank_account_name')}")
        if validated_details.get('bank_account_last4'):
            parts.append(f"Last4: {validated_details.get('bank_account_last4')}")
        if parts:
            receipt.notes = (receipt.notes or '').strip()
            receipt.notes = (receipt.notes + "\n" if receipt.notes else "") + "Bank transfer details (buyer): " + ", ".join(parts)
    receipt.save()

    Notification.objects.create(
        user=transaction.seller,
        related_user=transaction.buyer,
        message=f'{transaction.buyer.username} has initiated a bank transfer of ₱{transaction.price} for {transaction.listing.title if transaction.listing else "your item"}. Please confirm receipt.',
        notification_type='transaction',
        url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.id}),
    )

    messages.success(request, "Bank transfer request registered. Your receipt has been saved. The seller will confirm receipt.")
    return redirect('marketplace:receipt_detail', receipt_id=receipt.id)


def _finalize_third_party_delivery_payment(request, transaction, delivery_details):
    existing_payment = Payment.objects.filter(transaction=transaction).first()
    previous_payment_status = existing_payment.status if existing_payment else ''
    previous_manual_status = existing_payment.manual_verification_status if existing_payment else ''

    provider_code = (delivery_details.get('provider') or 'other').strip().lower()
    if provider_code not in THIRD_PARTY_PROVIDER_CODES:
        provider_code = 'other'

    tracking_link = (delivery_details.get('tracking_link') or '').strip()
    delivery_notes = (delivery_details.get('delivery_notes') or '').strip()
    now = timezone.now()

    payment, created = Payment.objects.update_or_create(
        transaction=transaction,
        defaults={
            'stripe_charge_id': f'third_party_delivery_{transaction.id}_{timezone.now().timestamp()}',
            'amount': transaction.price,
            'status': 'pending',
            'payment_method': 'third_party_delivery',
            'manual_verification_status': 'submitted',
            'manual_evidence_type': '',
            'manual_evidence_reference': '',
            'manual_evidence_notes': '',
            'manual_evidence_hash': '',
            'seller_acknowledged_at': None,
            'seller_acknowledged_by': None,
            'verified_at': None,
            'verified_by': None,
            'third_party_provider': provider_code,
            'third_party_tracking_link': tracking_link,
            'third_party_tracking_link_submitted_at': now,
            'third_party_tracking_link_submitted_by': request.user,
            'buyer_tracking_acknowledged_at': None,
            'seller_tracking_acknowledged_at': None,
        }
    )

    if previous_manual_status != payment.manual_verification_status:
        _record_state_transition(
            request,
            entity_type='payment',
            transition_kind='manual_verification',
            transaction=transaction,
            payment=payment,
            from_state=previous_manual_status,
            to_state=payment.manual_verification_status,
            reason='manual_payment_submitted',
            details={'payment_method': 'third_party_delivery', 'provider': provider_code},
        )

    if previous_payment_status != payment.status:
        _record_state_transition(
            request,
            entity_type='payment',
            transition_kind='payment_status',
            transaction=transaction,
            payment=payment,
            from_state=previous_payment_status,
            to_state=payment.status,
            reason='manual_payment_submitted',
            details={'payment_method': 'third_party_delivery', 'provider': provider_code},
        )

    receipt = _create_receipt(transaction, payment)
    receipt.status = 'pending'
    receipt.confirmed_at = None
    note_lines = [
        f"Third-party delivery provider: {provider_code}",
        f"Shared tracking link: {tracking_link}",
    ]
    if delivery_notes:
        note_lines.append(f"Delivery notes: {delivery_notes}")
    receipt.notes = (receipt.notes or '').strip()
    receipt.notes = (receipt.notes + "\n" if receipt.notes else "") + "\n".join(note_lines)
    receipt.save()

    Notification.objects.create(
        user=transaction.seller,
        related_user=transaction.buyer,
        message=(
            f'{transaction.buyer.username} initiated third-party delivery payment setup for ₱{transaction.price}. '
            'Review the shared tracking link and acknowledge it in transaction details before verification.'
        ),
        notification_type='transaction',
        url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.id}),
    )

    messages.success(
        request,
        'Third-party delivery setup recorded. Both parties must acknowledge the shared tracking link before verification.',
    )
    return redirect('marketplace:transaction_detail', transaction_id=transaction.id)


@login_required
def confirm_payment_received(request, transaction_id):
    """Seller acknowledges or verifies receipt of a pending payment submission."""
    transaction = get_object_or_404(Transaction, id=transaction_id)

    if request.user != transaction.seller:
        messages.error(request, 'Only the seller can confirm payment receipt.')
        return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

    if request.method != 'POST':
        return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

    payment = getattr(transaction, 'payment', None)
    if payment is None:
        messages.error(request, 'No payment record found for this transaction.')
        return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

    if payment.status != 'pending':
        messages.info(request, 'Payment is already confirmed.')
        return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

    if _is_manual_payment_method(payment.payment_method):
        if transaction.status != 'confirmed':
            messages.error(request, 'Manual payment can only be verified for confirmed transactions.')
            return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

        if not (transaction.buyer_confirmed_meeting and transaction.seller_confirmed_meeting):
            messages.error(request, 'Both parties must confirm meetup/agreement before payment verification.')
            return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

        requested_action = (request.POST.get('verification_action') or 'acknowledge').strip().lower()

        previous_manual_status = payment.manual_verification_status or 'submitted'
        if previous_manual_status == 'not_required':
            previous_manual_status = 'submitted'
            payment.manual_verification_status = 'submitted'
            payment.save(update_fields=['manual_verification_status', 'updated_at'])

        if previous_manual_status == 'awaiting_moderator_review':
            messages.info(request, 'This payment is already waiting for moderator review.')
            return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

        if requested_action == 'acknowledge':
            if previous_manual_status != 'seller_acknowledged':
                payment.manual_verification_status = 'seller_acknowledged'
                payment.seller_acknowledged_at = timezone.now()
                payment.seller_acknowledged_by = request.user
                payment.save(
                    update_fields=[
                        'manual_verification_status',
                        'seller_acknowledged_at',
                        'seller_acknowledged_by',
                        'updated_at',
                    ]
                )
                _record_state_transition(
                    request,
                    entity_type='payment',
                    transition_kind='manual_verification',
                    transaction=transaction,
                    payment=payment,
                    from_state=previous_manual_status,
                    to_state='seller_acknowledged',
                    reason='seller_acknowledged_manual_submission',
                    details={'payment_method': payment.payment_method},
                )

            messages.success(
                request,
                'Payment submission acknowledged. Provide verification evidence to mark this payment completed.',
            )
            return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

        if requested_action != 'verify':
            messages.error(request, 'Unknown payment verification action.')
            return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

        evidence_type = (request.POST.get('evidence_type') or '').strip().lower()
        evidence_reference = (request.POST.get('evidence_reference') or '').strip()
        evidence_notes = (request.POST.get('evidence_notes') or '').strip()

        if evidence_type not in MANUAL_EVIDENCE_TYPES:
            messages.error(request, 'Select a valid evidence type before verifying payment.')
            return redirect('marketplace:transaction_detail', transaction_id=transaction.id)
        if len(evidence_reference) < 6:
            messages.error(request, 'Evidence reference must be at least 6 characters long.')
            return redirect('marketplace:transaction_detail', transaction_id=transaction.id)
        if len(evidence_notes) < 12:
            messages.error(request, 'Verification notes must be at least 12 characters long.')
            return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

        required_evidence_by_method = {
            'gcash': 'gcash_reference',
            'bank_transfer': 'bank_reference',
            'in_person': 'cash_receipt',
            'third_party_delivery': 'delivery_tracking',
            'other': 'chat_confirmation',
        }
        required_evidence_type = required_evidence_by_method.get(payment.payment_method)
        if required_evidence_type and evidence_type != required_evidence_type:
            messages.error(
                request,
                f"Selected payment method requires '{required_evidence_type}' as evidence type.",
            )
            return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

        if payment.payment_method == 'gcash':
            normalized_reference = re.sub(r'\s+', '', evidence_reference).upper()
            if not re.fullmatch(r'[A-Z0-9\-]{8,40}', normalized_reference):
                messages.error(request, 'GCash evidence reference must be 8 to 40 alphanumeric characters/dashes.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.id)
            evidence_reference = normalized_reference

        if payment.payment_method == 'bank_transfer':
            normalized_reference = re.sub(r'\s+', '', evidence_reference).upper()
            if not re.fullmatch(r'[A-Z0-9\-]{8,60}', normalized_reference):
                messages.error(request, 'Bank evidence reference must be 8 to 60 alphanumeric characters/dashes.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.id)
            evidence_reference = normalized_reference

        if payment.payment_method == 'other':
            if len(evidence_reference) < 10:
                messages.error(request, 'Custom arrangement evidence reference must be at least 10 characters long.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.id)
            if len(evidence_notes) < 24:
                messages.error(request, 'Custom arrangement verification notes must be at least 24 characters long.')
                return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

        if payment.payment_method == 'in_person' and not _in_person_meetup_proof_ready(payment):
            messages.error(
                request,
                'Both buyer and seller must upload meetup photo proof before in-person cash payment can be verified.',
            )
            return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

        if payment.payment_method == 'third_party_delivery':
            if not _third_party_tracking_link_ready(payment):
                messages.error(
                    request,
                    'A shared delivery tracking link is required before third-party delivery payment can be verified.',
                )
                return redirect('marketplace:transaction_detail', transaction_id=transaction.id)
            if not _third_party_tracking_ack_ready(payment):
                messages.error(
                    request,
                    'Both buyer and seller must acknowledge the shared delivery tracking link before verification.',
                )
                return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

        evidence_hash = _build_manual_evidence_hash(
            transaction,
            payment,
            evidence_type,
            evidence_reference,
            evidence_notes,
        )

        external_verification_result = _run_external_manual_verification(
            payment.payment_method,
            evidence_reference,
            evidence_notes,
        )

        if external_verification_result.get('status') == 'error':
            messages.error(request, external_verification_result.get('message', 'External verification failed.'))
            return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

        external_note = (
            f"External verification ({external_verification_result.get('provider')}): "
            f"{external_verification_result.get('status')} - {external_verification_result.get('message')}"
        )
        if external_note not in evidence_notes:
            evidence_notes = f"{evidence_notes}\n{external_note}"

        requires_moderator_review = _manual_payment_requires_moderator_review(payment)
        if not requires_moderator_review:
            messages.error(
                request,
                'Manual payment verification is not permitted to complete without moderator review under current safety policy.',
            )
            return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

        previous_payment_status = payment.status
        now = timezone.now()

        payment.manual_verification_status = 'awaiting_moderator_review'
        payment.manual_evidence_type = evidence_type
        payment.manual_evidence_reference = evidence_reference
        payment.manual_evidence_notes = evidence_notes
        payment.manual_evidence_hash = evidence_hash
        if payment.seller_acknowledged_at is None:
            payment.seller_acknowledged_at = now
            payment.seller_acknowledged_by = request.user

        update_fields = [
            'manual_verification_status',
            'manual_evidence_type',
            'manual_evidence_reference',
            'manual_evidence_notes',
            'manual_evidence_hash',
            'seller_acknowledged_at',
            'seller_acknowledged_by',
            'updated_at',
        ]

        payment.verified_at = None
        payment.verified_by = None
        update_fields.extend(['verified_at', 'verified_by'])

        payment.save(update_fields=update_fields)

        if previous_manual_status != payment.manual_verification_status:
            _record_state_transition(
                request,
                entity_type='payment',
                transition_kind='manual_verification',
                transaction=transaction,
                payment=payment,
                from_state=previous_manual_status,
                to_state=payment.manual_verification_status,
                reason='seller_verified_manual_payment',
                evidence_hash=evidence_hash,
                details={
                    'payment_method': payment.payment_method,
                    'evidence_type': evidence_type,
                    'requires_moderator_review': requires_moderator_review,
                    'external_verification': external_verification_result,
                },
            )

        if previous_payment_status != payment.status:
            _record_state_transition(
                request,
                entity_type='payment',
                transition_kind='payment_status',
                transaction=transaction,
                payment=payment,
                from_state=previous_payment_status,
                to_state=payment.status,
                reason='seller_verified_manual_payment',
                evidence_hash=evidence_hash,
                details={
                    'payment_method': payment.payment_method,
                    'requires_moderator_review': requires_moderator_review,
                    'external_verification': external_verification_result,
                },
            )

        admin_review_url = reverse('marketplace:mod_transaction_detail', kwargs={'transaction_id': transaction.pk})
        for admin_user in User.objects.filter(is_superuser=True).exclude(pk=request.user.pk):
            Notification.objects.create(
                user=admin_user,
                related_user=request.user,
                message=(
                    f'Manual payment verification for transaction #{transaction.pk} '
                    f'requires moderator approval (amount: P{transaction.price}).'
                ),
                notification_type='system',
                url=admin_review_url,
            )

        Notification.objects.create(
            user=transaction.buyer,
            related_user=transaction.seller,
            message='Your manual payment evidence was submitted and is pending moderator review.',
            notification_type='transaction',
            url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.id}),
        )

        messages.success(
            request,
            'Evidence submitted. Manual payments can only complete after moderator safety approval.',
        )
        return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

    previous_payment_status = payment.status
    payment.status = 'completed'
    payment.save(update_fields=['status', 'updated_at'])

    _record_state_transition(
        request,
        entity_type='payment',
        transition_kind='payment_status',
        transaction=transaction,
        payment=payment,
        from_state=previous_payment_status,
        to_state=payment.status,
        reason='seller_confirmed_non_manual_payment',
    )

    receipt = _ensure_receipt_for_payment(transaction, payment)
    if receipt.status == 'pending':
        receipt.status = 'confirmed'
        receipt.confirmed_at = timezone.now()
        receipt.save(update_fields=['status', 'confirmed_at'])

    Notification.objects.create(
        user=transaction.buyer,
        related_user=transaction.seller,
        message=f'{transaction.seller.username} confirmed your payment for {transaction.listing.title if transaction.listing else "your transaction"}.',
        notification_type='transaction',
        url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.id}),
    )

    messages.success(request, 'Payment marked as received.')
    return redirect('marketplace:transaction_detail', transaction_id=transaction.id)

@login_required
def payment_checkout(request, transaction_id):
    """Handle payment checkout for a transaction."""
    try:
        transaction = get_object_or_404(Transaction, id=transaction_id, buyer=request.user)
    except:
        messages.error(request, "Transaction not found or you don't have permission to access it.")
        return redirect('marketplace:home')

    # Guard: only confirmed transactions can be paid
    if transaction.status == 'cancelled':
        messages.error(request, "This transaction has been cancelled and cannot be paid.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)
    if transaction.status == 'completed':
        messages.info(request, "This transaction is already completed.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)
    if transaction.status == 'pending':
        messages.info(request, "Payment is not available yet — waiting for the seller to confirm.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)

    if not (transaction.buyer_confirmed_meeting and transaction.seller_confirmed_meeting):
        messages.info(request, "Payment is locked until both buyer and seller confirm meetup/agreement.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)

    allowed_methods = _get_allowed_payment_methods(transaction.listing)

    # Check if payment already exists
    if hasattr(transaction, 'payment'):
        if transaction.payment.status == 'completed':
            messages.info(request, "This transaction has already been paid.")
            return redirect('marketplace:transaction_detail', transaction_id=transaction_id)
        if transaction.payment.status == 'pending':
            if (
                transaction.payment.payment_method == 'credit_card'
                and bool(getattr(settings, 'STRIPE_WEBHOOK_REQUIRED', False))
            ):
                messages.info(
                    request,
                    "Card payment authorization is pending signed webhook confirmation. Please refresh transaction details shortly.",
                )
            else:
                messages.info(request, "Payment submission already exists and is waiting for seller confirmation.")
            return redirect('marketplace:transaction_detail', transaction_id=transaction_id)

    if request.method == 'GET':
        # Prepare context for GET request
        exchange_method = request.GET.get('method', transaction.exchange_method)
        if exchange_method not in allowed_methods:
            exchange_method = allowed_methods[0]
        
        context = {
            'transaction': transaction,
            'exchange_method': exchange_method,
            'allowed_methods': allowed_methods,
            'stripe_public_key': settings.STRIPE_PUBLIC_KEY,
            'stripe_webhook_required': bool(getattr(settings, 'STRIPE_WEBHOOK_REQUIRED', False)),
        }

        # ALWAYS create PaymentIntent for credit card transactions
        # This ensures clientSecret is available when credit card is allowed.
        if 'credit_card' in allowed_methods:
            try:
                amount_cents = int(float(transaction.price) * 100)
                intent = stripe.PaymentIntent.create(
                    amount=amount_cents,
                    currency='php',
                    description=f'Marketplace Purchase: {transaction.listing.title if transaction.listing else "Item"}',
                    metadata={
                        'transaction_id': str(transaction.id),
                        'buyer': transaction.buyer.username,
                        'seller': transaction.seller.username,
                    },
                    automatic_payment_methods={'enabled': True},
                )
                context['client_secret'] = intent.client_secret
            except stripe.error.CardError as e:
                context['error'] = f"Card error: {e.user_message}"
            except stripe.error.RateLimitError:
                context['error'] = "Too many requests. Please try again in a moment."
            except stripe.error.InvalidRequestError:
                context['error'] = "Invalid payment details. Please check your information."
            except stripe.error.AuthenticationError:
                context['error'] = "Authentication failed. Please try again."
            except stripe.error.APIConnectionError:
                context['error'] = "Network error. Please check your connection and try again."
            except stripe.error.StripeError:
                context['error'] = "An error occurred with Stripe. Please try again."

        return render(request, 'marketplace/payment_checkout.html', context)

    elif request.method == 'POST':
        exchange_method = request.POST.get('exchange_method', transaction.exchange_method)

        if exchange_method not in allowed_methods:
            messages.error(request, "This payment method is not allowed by the lister.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

        confirmations = request.POST.getlist('confirm_item')
        if len(confirmations) < 5:
            messages.error(request, "Please acknowledge all safety reminders before continuing.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

        # Route to appropriate payment method page
        if exchange_method == 'credit_card':
            # The frontend sends the PaymentIntent ID after confirmCardPayment succeeds
            payment_intent_id = request.POST.get('payment_intent_id', '').strip()
            if not payment_intent_id or not payment_intent_id.startswith('pi_'):
                messages.error(request, "Invalid payment details. Please try again.")
                return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

            if not is_sensitive_recent(request.session, request.user):
                return _start_sensitive_payment_step_up(
                    request,
                    transaction_id=transaction_id,
                    action_payload={
                        'kind': 'credit_card',
                        'transaction_id': transaction_id,
                        'payment_intent_id': payment_intent_id,
                    },
                )

            return _finalize_credit_card_payment(request, transaction, payment_intent_id)

        elif exchange_method == 'gcash':
            gcash_details = {
                'gcash_number': (request.POST.get('gcash_number') or '').strip(),
                'gcash_name': (request.POST.get('gcash_name') or '').strip(),
            }
            validated_gcash_details, validation_error = _validate_gcash_details(gcash_details)
            if validation_error:
                messages.error(request, validation_error)
                return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

            # Persist buyer details across redirect
            request.session['payment_details_gcash'] = validated_gcash_details

            if not is_sensitive_recent(request.session, request.user):
                return _start_sensitive_payment_step_up(
                    request,
                    transaction_id=transaction_id,
                    action_payload={
                        'kind': 'checkout_to_gcash',
                        'transaction_id': transaction_id,
                    },
                )

            return redirect('marketplace:payment_gcash', transaction_id=transaction_id)
        
        elif exchange_method == 'bank_transfer':
            bank_details = {
                'bank_name': (request.POST.get('bank_name') or '').strip(),
                'bank_account_name': (request.POST.get('bank_account_name') or '').strip(),
                'bank_account_last4': (request.POST.get('bank_account_last4') or '').strip(),
            }
            validated_bank_details, validation_error = _validate_bank_details(bank_details)
            if validation_error:
                messages.error(request, validation_error)
                return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

            request.session['payment_details_bank'] = validated_bank_details

            if not is_sensitive_recent(request.session, request.user):
                return _start_sensitive_payment_step_up(
                    request,
                    transaction_id=transaction_id,
                    action_payload={
                        'kind': 'checkout_to_bank_transfer',
                        'transaction_id': transaction_id,
                    },
                )

            return redirect('marketplace:payment_bank_transfer', transaction_id=transaction_id)

        elif exchange_method == 'third_party_delivery':
            if not is_sensitive_recent(request.session, request.user):
                return _start_sensitive_payment_step_up(
                    request,
                    transaction_id=transaction_id,
                    action_payload={
                        'kind': 'checkout_to_third_party_delivery',
                        'transaction_id': transaction_id,
                    },
                )

            return redirect('marketplace:payment_third_party_delivery', transaction_id=transaction_id)
        
        elif exchange_method == 'in_person':
            return redirect('marketplace:payment_cash_arrangement', transaction_id=transaction_id)
        
        elif exchange_method == 'other':
            return redirect('marketplace:payment_other_arrangement', transaction_id=transaction_id)
        
        else:
            messages.error(request, "Invalid payment method selected.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

    return render(request, 'marketplace/payment_checkout.html', {
        'transaction': transaction,
        'allowed_methods': allowed_methods,
        'stripe_webhook_required': bool(getattr(settings, 'STRIPE_WEBHOOK_REQUIRED', False)),
    })


@login_required
def payment_finalize_pending(request, transaction_id):
    """Resume a pending payment action after sensitive OTP verification."""
    try:
        transaction = get_object_or_404(Transaction, id=transaction_id, buyer=request.user)
    except Exception:
        messages.error(request, "Transaction not found.")
        return redirect('marketplace:home')

    pending_action = request.session.pop(PENDING_SENSITIVE_PAYMENT_SESSION_KEY, None)
    if not pending_action or pending_action.get('transaction_id') != transaction_id:
        messages.error(request, "No pending payment action to finalize.")
        return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

    if not (transaction.buyer_confirmed_meeting and transaction.seller_confirmed_meeting):
        messages.error(request, "Payment finalization is locked until both parties confirm meetup/agreement.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)

    allowed_methods = _get_allowed_payment_methods(transaction.listing)

    if not is_sensitive_recent(request.session, request.user):
        return _start_sensitive_payment_step_up(request, transaction_id, pending_action)

    action_kind = pending_action.get('kind')

    if action_kind == 'credit_card':
        if 'credit_card' not in allowed_methods:
            messages.error(request, "Card payments are not allowed for this listing.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction_id)
        payment_intent_id = (pending_action.get('payment_intent_id') or '').strip()
        if not payment_intent_id.startswith('pi_'):
            messages.error(request, "Pending card payment reference is invalid.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction_id)
        return _finalize_credit_card_payment(request, transaction, payment_intent_id)

    if action_kind == 'gcash':
        if 'gcash' not in allowed_methods:
            messages.error(request, "GCash is not allowed for this listing.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction_id)
        buyer_details = request.session.pop('payment_details_gcash', None) or {}
        return _finalize_gcash_payment(request, transaction, buyer_details)

    if action_kind == 'bank_transfer':
        if 'bank_transfer' not in allowed_methods:
            messages.error(request, "Bank transfer is not allowed for this listing.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction_id)
        buyer_details = request.session.pop('payment_details_bank', None) or {}
        return _finalize_bank_transfer_payment(request, transaction, buyer_details)

    if action_kind == 'third_party_delivery':
        if 'third_party_delivery' not in allowed_methods:
            messages.error(request, "Third-party delivery is not allowed for this listing.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction_id)
        delivery_details = request.session.pop('payment_details_third_party_delivery', None) or {}
        return _finalize_third_party_delivery_payment(request, transaction, delivery_details)

    if action_kind == 'checkout_to_gcash':
        if 'gcash' not in allowed_methods:
            messages.error(request, "GCash is not allowed for this listing.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction_id)
        return redirect('marketplace:payment_gcash', transaction_id=transaction_id)

    if action_kind == 'checkout_to_bank_transfer':
        if 'bank_transfer' not in allowed_methods:
            messages.error(request, "Bank transfer is not allowed for this listing.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction_id)
        return redirect('marketplace:payment_bank_transfer', transaction_id=transaction_id)

    if action_kind == 'checkout_to_third_party_delivery':
        if 'third_party_delivery' not in allowed_methods:
            messages.error(request, "Third-party delivery is not allowed for this listing.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction_id)
        return redirect('marketplace:payment_third_party_delivery', transaction_id=transaction_id)

    messages.error(request, "Unknown pending payment action.")
    return redirect('marketplace:payment_checkout', transaction_id=transaction_id)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """Handle Stripe webhook events for card-payment verification."""
    webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')
    if not webhook_secret:
        return JsonResponse({'error': 'Webhook secret is not configured.'}, status=503)

    signature_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    if not signature_header:
        return JsonResponse({'error': 'Missing Stripe signature header.'}, status=400)

    try:
        event = stripe.Webhook.construct_event(request.body, signature_header, webhook_secret)
    except ValueError:
        return JsonResponse({'error': 'Invalid webhook payload.'}, status=400)
    except stripe.error.SignatureVerificationError:
        return JsonResponse({'error': 'Invalid webhook signature.'}, status=400)
    except Exception:
        logger.exception('Unexpected Stripe webhook parse failure')
        return JsonResponse({'error': 'Unable to parse webhook event.'}, status=400)

    event_id = (event.get('id') or '').strip()
    event_type = (event.get('type') or '').strip()

    if _stripe_event_already_processed(event_id):
        return JsonResponse({'status': 'already_processed'})

    if event_type != 'payment_intent.succeeded':
        return JsonResponse({'status': 'ignored', 'event_type': event_type})

    intent = ((event.get('data') or {}).get('object') or {})
    payment_intent_id = (intent.get('id') or '').strip()
    if not payment_intent_id.startswith('pi_'):
        return JsonResponse({'status': 'ignored', 'reason': 'invalid_payment_intent'})

    metadata = intent.get('metadata') or {}
    tx_meta = str(metadata.get('transaction_id') or '').strip()

    payment = Payment.objects.select_related('transaction').filter(stripe_charge_id=payment_intent_id).first()
    transaction_obj = payment.transaction if payment else None

    if transaction_obj is None and tx_meta.isdigit():
        transaction_obj = Transaction.objects.filter(pk=int(tx_meta)).first()

    if transaction_obj is None:
        logger.warning('Stripe webhook ignored: no matching transaction for payment_intent=%s', payment_intent_id)
        return JsonResponse({'status': 'ignored', 'reason': 'transaction_not_found'})

    expected_amount = _transaction_amount_cents(transaction_obj)
    intent_amount = intent.get('amount_received') or intent.get('amount')
    intent_currency = (intent.get('currency') or '').lower()
    if expected_amount is None or intent_amount != expected_amount or intent_currency != 'php':
        logger.warning(
            'Stripe webhook ignored: amount/currency mismatch for transaction=%s intent=%s',
            transaction_obj.pk,
            payment_intent_id,
        )
        return JsonResponse({'status': 'ignored', 'reason': 'amount_or_currency_mismatch'})

    with db_transaction.atomic():
        payment = Payment.objects.select_for_update().filter(transaction=transaction_obj).first()
        if payment is None or payment.payment_method != 'credit_card' or payment.stripe_charge_id != payment_intent_id:
            payment, _ = _ensure_credit_card_pending_record(
                request,
                transaction_obj,
                payment_intent_id,
                reason='stripe_webhook_seed_pending',
                details={
                    'stripe_event_id': event_id,
                    'payment_intent_id': payment_intent_id,
                    'event_type': event_type,
                    'source': 'stripe_webhook',
                },
            )

        if payment.status != 'completed':
            _complete_credit_card_payment_record(
                request,
                transaction_obj,
                payment,
                reason='stripe_webhook_payment_intent_succeeded',
                details={
                    'stripe_event_id': event_id,
                    'payment_intent_id': payment_intent_id,
                    'event_type': event_type,
                    'source': 'stripe_webhook',
                },
            )

    return JsonResponse({'status': 'processed'})


@login_required
def payment_success(request, transaction_id):
    """Payment success page."""
    try:
        transaction = get_object_or_404(Transaction, id=transaction_id, buyer=request.user)
    except:
        messages.error(request, "Transaction not found.")
        return redirect('marketplace:home')

    payment = getattr(transaction, 'payment', None)

    context = {
        'transaction': transaction,
        'payment': payment,
    }

    return render(request, 'marketplace/payment_success.html', context)


@login_required
def payment_cancel(request, transaction_id):
    """Payment cancellation/failure handler."""
    try:
        transaction = get_object_or_404(Transaction, id=transaction_id, buyer=request.user)
    except:
        messages.error(request, "Transaction not found.")
        return redirect('marketplace:home')

    payment = getattr(transaction, 'payment', None)

    context = {
        'transaction': transaction,
        'payment': payment,
    }

    return render(request, 'marketplace/payment_failure.html', context)


def _generate_receipt_number():
    """Generate a unique receipt number in format RCP-2024-XXXXX."""
    from datetime import datetime
    import random
    year = datetime.now().year
    random_suffix = str(random.randint(10000, 99999))
    receipt_num = f"RCP-{year}-{random_suffix}"
    
    # Ensure uniqueness
    while Receipt.objects.filter(receipt_number=receipt_num).exists():
        random_suffix = str(random.randint(10000, 99999))
        receipt_num = f"RCP-{year}-{random_suffix}"
    
    return receipt_num


def _create_receipt(transaction, payment=None):
    """Create and return a Receipt object for a transaction."""
    receipt_number = _generate_receipt_number()
    
    # Calculate processing fee based on payment method
    processing_fee = Decimal('0.00')
    if payment and payment.payment_method == 'credit_card':
        processing_fee = Decimal(transaction.price) * Decimal('0.02')
    
    total_amount = Decimal(transaction.price) + processing_fee
    
    receipt, created = Receipt.objects.get_or_create(
        transaction=transaction,
        defaults={
            'payment': payment,
            'receipt_number': receipt_number,
            'buyer': transaction.buyer,
            'seller': transaction.seller,
            'listing_title': transaction.listing.title if transaction.listing else 'Item',
            'listing_price': transaction.unit_price or transaction.price,
            'payment_method': payment.payment_method if payment else transaction.exchange_method,
            'processing_fee': processing_fee,
            'total_amount': total_amount,
            'status': 'pending',
            'notes': transaction.notes,
        }
    )
    
    return receipt


@login_required
def payment_gcash(request, transaction_id):
    """GCash/E-wallet payment page with payment instructions."""
    try:
        transaction = get_object_or_404(Transaction, id=transaction_id, buyer=request.user)
    except:
        messages.error(request, "Transaction not found.")
        return redirect('marketplace:home')
    
    if transaction.status != 'confirmed':
        messages.error(request, "This transaction is not ready for payment.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)

    if 'gcash' not in _get_allowed_payment_methods(transaction.listing):
        messages.error(request, "GCash is not an allowed payment method for this listing.")
        return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

    if not (transaction.buyer_confirmed_meeting and transaction.seller_confirmed_meeting):
        messages.error(request, "Both parties must confirm meetup/agreement before starting payment.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)
    
    if request.method == 'POST':
        if not is_sensitive_recent(request.session, request.user):
            return _start_sensitive_payment_step_up(
                request,
                transaction_id=transaction_id,
                action_payload={
                    'kind': 'gcash',
                    'transaction_id': transaction_id,
                },
            )

        buyer_details = request.session.pop('payment_details_gcash', None) or {}
        return _finalize_gcash_payment(request, transaction, buyer_details)
    
    context = {
        'transaction': transaction,
        'payment_method': 'gcash',
        'buyer_gcash_details': request.session.get('payment_details_gcash', {}),
    }
    return render(request, 'marketplace/payment_gcash.html', context)


@login_required
def payment_bank_transfer(request, transaction_id):
    """Bank transfer payment page with bank details."""
    try:
        transaction = get_object_or_404(Transaction, id=transaction_id, buyer=request.user)
    except:
        messages.error(request, "Transaction not found.")
        return redirect('marketplace:home')
    
    if transaction.status != 'confirmed':
        messages.error(request, "This transaction is not ready for payment.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)

    if 'bank_transfer' not in _get_allowed_payment_methods(transaction.listing):
        messages.error(request, "Bank transfer is not an allowed payment method for this listing.")
        return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

    if not (transaction.buyer_confirmed_meeting and transaction.seller_confirmed_meeting):
        messages.error(request, "Both parties must confirm meetup/agreement before starting payment.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)
    
    if request.method == 'POST':
        if not is_sensitive_recent(request.session, request.user):
            return _start_sensitive_payment_step_up(
                request,
                transaction_id=transaction_id,
                action_payload={
                    'kind': 'bank_transfer',
                    'transaction_id': transaction_id,
                },
            )

        buyer_details = request.session.pop('payment_details_bank', None) or {}
        return _finalize_bank_transfer_payment(request, transaction, buyer_details)
    
    context = {
        'transaction': transaction,
        'payment_method': 'bank_transfer',
        'seller_phone': transaction.seller.profile.phone or '',
        'seller_name': transaction.seller.profile.display_name or transaction.seller.username,
        'buyer_bank_details': request.session.get('payment_details_bank', {}),
    }
    return render(request, 'marketplace/payment_bank_transfer.html', context)


@login_required
def payment_third_party_delivery(request, transaction_id):
    """Third-party delivery payment page requiring shared tracking link details."""
    try:
        transaction = get_object_or_404(Transaction, id=transaction_id, buyer=request.user)
    except:
        messages.error(request, "Transaction not found.")
        return redirect('marketplace:home')

    if transaction.status != 'confirmed':
        messages.error(request, "This transaction is not ready for payment.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)

    if 'third_party_delivery' not in _get_allowed_payment_methods(transaction.listing):
        messages.error(request, "Third-party delivery is not an allowed payment method for this listing.")
        return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

    if not (transaction.buyer_confirmed_meeting and transaction.seller_confirmed_meeting):
        messages.error(request, "Both parties must confirm meetup/agreement before starting payment.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)

    if request.method == 'POST':
        provider_code = (request.POST.get('tracking_provider') or '').strip().lower()
        tracking_link = (request.POST.get('tracking_link') or '').strip()
        delivery_notes = (request.POST.get('delivery_notes') or '').strip()

        if provider_code not in THIRD_PARTY_PROVIDER_CODES:
            messages.error(request, "Please select a valid third-party provider.")
            return redirect('marketplace:payment_third_party_delivery', transaction_id=transaction_id)

        is_valid_link, validation_error = _is_valid_tracking_link(tracking_link, provider=provider_code)
        if not is_valid_link:
            messages.error(request, validation_error)
            return redirect('marketplace:payment_third_party_delivery', transaction_id=transaction_id)

        if len(delivery_notes) < 12:
            messages.error(request, "Please add delivery coordination notes (at least 12 characters).")
            return redirect('marketplace:payment_third_party_delivery', transaction_id=transaction_id)

        request.session['payment_details_third_party_delivery'] = {
            'provider': provider_code,
            'tracking_link': tracking_link,
            'delivery_notes': delivery_notes,
        }

        if not is_sensitive_recent(request.session, request.user):
            return _start_sensitive_payment_step_up(
                request,
                transaction_id=transaction_id,
                action_payload={
                    'kind': 'third_party_delivery',
                    'transaction_id': transaction_id,
                },
            )

        delivery_details = request.session.pop('payment_details_third_party_delivery', None) or {}
        return _finalize_third_party_delivery_payment(request, transaction, delivery_details)

    payment = getattr(transaction, 'payment', None)
    saved_details = request.session.get('payment_details_third_party_delivery', {})

    context = {
        'transaction': transaction,
        'payment_method': 'third_party_delivery',
        'tracking_provider': saved_details.get('provider') or (payment.third_party_provider if payment else ''),
        'tracking_link': saved_details.get('tracking_link') or (payment.third_party_tracking_link if payment else ''),
        'delivery_notes': saved_details.get('delivery_notes') or '',
    }
    return render(request, 'marketplace/payment_third_party_delivery.html', context)


@login_required
def payment_cash_arrangement(request, transaction_id):
    """Cash on hand arrangement page for when meeting in person."""
    try:
        transaction = get_object_or_404(Transaction, id=transaction_id, buyer=request.user)
    except:
        messages.error(request, "Transaction not found.")
        return redirect('marketplace:home')
    
    if transaction.status != 'confirmed':
        messages.error(request, "This transaction is not ready for payment.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)

    if 'in_person' not in _get_allowed_payment_methods(transaction.listing):
        messages.error(request, "In-person cash is not an allowed payment method for this listing.")
        return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

    if not (transaction.buyer_confirmed_meeting and transaction.seller_confirmed_meeting):
        messages.error(request, "Both parties must confirm meetup/agreement before starting payment.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)
    
    if request.method == 'POST':
        existing_payment = Payment.objects.filter(transaction=transaction).first()
        previous_payment_status = existing_payment.status if existing_payment else ''
        previous_manual_status = existing_payment.manual_verification_status if existing_payment else ''

        # Create payment record
        payment, created = Payment.objects.update_or_create(
            transaction=transaction,
            defaults={
                'stripe_charge_id': f'cash_{transaction.id}_{timezone.now().timestamp()}',
                'amount': transaction.price,
                'status': 'pending',
                'payment_method': 'in_person',
                'manual_verification_status': 'submitted',
                'manual_evidence_type': '',
                'manual_evidence_reference': '',
                'manual_evidence_notes': '',
                'manual_evidence_hash': '',
                'seller_acknowledged_at': None,
                'seller_acknowledged_by': None,
                'verified_at': None,
                'verified_by': None,
            }
        )

        if previous_manual_status != payment.manual_verification_status:
            _record_state_transition(
                request,
                entity_type='payment',
                transition_kind='manual_verification',
                transaction=transaction,
                payment=payment,
                from_state=previous_manual_status,
                to_state=payment.manual_verification_status,
                reason='manual_payment_submitted',
                details={'payment_method': 'in_person'},
            )

        if previous_payment_status != payment.status:
            _record_state_transition(
                request,
                entity_type='payment',
                transition_kind='payment_status',
                transaction=transaction,
                payment=payment,
                from_state=previous_payment_status,
                to_state=payment.status,
                reason='manual_payment_submitted',
                details={'payment_method': 'in_person'},
            )
        
        # Notify seller
        Notification.objects.create(
            user=transaction.seller,
            related_user=transaction.buyer,
            message=(
                f'{transaction.buyer.username} confirmed an in-person cash arrangement for ₱{transaction.price}. '
                'Both parties must upload meetup photo proof before payment can be verified.'
            ),
            notification_type='transaction',
            url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.id}),
        )

        messages.success(
            request,
            'Cash arrangement recorded. Upload meetup photo proof (both buyer and seller) before receipt can be issued.',
        )
        return redirect('marketplace:transaction_detail', transaction_id=transaction.id)
    
    context = {
        'transaction': transaction,
        'payment_method': 'in_person',
        'suggested_meetup_points': SUGGESTED_MEETUP_POINTS.get(
            transaction.listing.school.short_name if transaction.listing and transaction.listing.school else 'Public',
            SUGGESTED_MEETUP_POINTS['Public']
        ),
    }
    return render(request, 'marketplace/payment_cash_arrangement.html', context)


@login_required
def payment_other_arrangement(request, transaction_id):
    """Other arrangement page for custom payment methods."""
    try:
        transaction = get_object_or_404(Transaction, id=transaction_id, buyer=request.user)
    except:
        messages.error(request, "Transaction not found.")
        return redirect('marketplace:home')
    
    if transaction.status != 'confirmed':
        messages.error(request, "This transaction is not ready for payment.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)

    if 'other' not in _get_allowed_payment_methods(transaction.listing):
        messages.error(request, "Custom arrangements are not allowed for this listing.")
        return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

    if not (transaction.buyer_confirmed_meeting and transaction.seller_confirmed_meeting):
        messages.error(request, "Both parties must confirm meetup/agreement before starting payment.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)
    
    if request.method == 'POST':
        arrangement_details, validation_error = _validate_other_arrangement_details(
            request.POST.get('arrangement_details', '')
        )

        if validation_error:
            messages.error(request, validation_error)
            return redirect('marketplace:payment_other_arrangement', transaction_id=transaction_id)
        
        existing_payment = Payment.objects.filter(transaction=transaction).first()
        previous_payment_status = existing_payment.status if existing_payment else ''
        previous_manual_status = existing_payment.manual_verification_status if existing_payment else ''

        # Create payment record
        payment, created = Payment.objects.update_or_create(
            transaction=transaction,
            defaults={
                'stripe_charge_id': f'other_{transaction.id}_{timezone.now().timestamp()}',
                'amount': transaction.price,
                'status': 'pending',
                'payment_method': 'other',
                'manual_verification_status': 'submitted',
                'manual_evidence_type': '',
                'manual_evidence_reference': '',
                'manual_evidence_notes': '',
                'manual_evidence_hash': '',
                'seller_acknowledged_at': None,
                'seller_acknowledged_by': None,
                'verified_at': None,
                'verified_by': None,
            }
        )

        if previous_manual_status != payment.manual_verification_status:
            _record_state_transition(
                request,
                entity_type='payment',
                transition_kind='manual_verification',
                transaction=transaction,
                payment=payment,
                from_state=previous_manual_status,
                to_state=payment.manual_verification_status,
                reason='manual_payment_submitted',
                details={'payment_method': 'other'},
            )

        if previous_payment_status != payment.status:
            _record_state_transition(
                request,
                entity_type='payment',
                transition_kind='payment_status',
                transaction=transaction,
                payment=payment,
                from_state=previous_payment_status,
                to_state=payment.status,
                reason='manual_payment_submitted',
                details={'payment_method': 'other'},
            )
        
        # Create receipt with arrangement details in notes
        receipt = _create_receipt(transaction, payment)
        receipt.status = 'pending'
        receipt.notes = f"Custom Arrangement: {arrangement_details}"
        receipt.save()
        
        # Notify seller with the arrangement details
        Notification.objects.create(
            user=transaction.seller,
            related_user=transaction.buyer,
            message=f'{transaction.buyer.username} has proposed a custom arrangement for ₱{transaction.price}: {arrangement_details}. Please confirm in the transaction details.',
            notification_type='transaction',
            url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.id}),
        )
        
        messages.success(request, "Your arrangement has been sent to the seller. Your receipt has been saved. They will confirm shortly.")
        return redirect('marketplace:receipt_detail', receipt_id=receipt.id)
    
    context = {
        'transaction': transaction,
        'payment_method': 'other',
    }
    return render(request, 'marketplace/payment_other_arrangement.html', context)


@login_required
def receipt_detail(request, receipt_id):
    """Display a detailed receipt for a transaction."""
    try:
        receipt = get_object_or_404(Receipt, id=receipt_id)
    except:
        messages.error(request, "Receipt not found.")
        return redirect('marketplace:inbox')
    
    # Ensure user is either buyer or seller
    if request.user not in [receipt.buyer, receipt.seller]:
        messages.error(request, "You don't have permission to view this receipt.")
        return redirect('marketplace:inbox')
    
    context = {
        'receipt': receipt,
        'is_buyer': request.user == receipt.buyer,
        'is_seller': request.user == receipt.seller,
    }
    
    return render(request, 'marketplace/receipt_detail.html', context)


@login_required
def receipts_list(request):
    """List all receipts for the current user."""
    # Get receipts where user is buyer or seller, ordered by most recent
    receipts = Receipt.objects.filter(
        Q(buyer=request.user) | Q(seller=request.user)
    ).select_related('transaction', 'buyer', 'seller', 'payment').order_by('-created_at')
    
    # Filtering
    status_filter = request.GET.get('status', '')
    if status_filter:
        receipts = receipts.filter(status=status_filter)
    
    search_query = request.GET.get('q', '').strip()
    if search_query:
        receipts = receipts.filter(
            Q(listing_title__icontains=search_query) |
            Q(receipt_number__icontains=search_query) |
            Q(buyer__username__icontains=search_query) |
            Q(seller__username__icontains=search_query)
        )
    
    context = {
        'receipts': receipts,
        'status_filter': status_filter,
        'search_query': search_query,
    }
    
    return render(request, 'marketplace/receipts_list.html', context)



def about(request):
    return render(request, 'marketplace/about.html')

from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
class UserAppealsView(LoginRequiredMixin, ListView):
    template_name = 'marketplace/appeals.html'
    context_object_name = 'reports'
    def get_queryset(self):
        return UserReport.objects.filter(reported_user=self.request.user).order_by('-created_at')

@login_required
def appeal_submit(request, pk):
    report = get_object_or_404(UserReport, pk=pk, reported_user=request.user)
    if request.method == 'POST':
        text = request.POST.get('appeal_text')
        if text:
            report.appeal_requested = True
            report.appeal_text = text
            report.appeal_status = 'pending'
            report.save()
            messages.success(request, 'Your appeal has been submitted. Note that timeframe for appeals may take long.')
        return redirect('appeals')
    return render(request, 'marketplace/appeal_submit.html', {'report': report})
