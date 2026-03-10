import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth import login

logger = logging.getLogger(__name__)
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse
import json
from datetime import datetime, timedelta
from django.db.models import Q, Count, Sum
from django.utils import timezone
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
    ProfilePost,
    ProfilePostComment,
    SocialMedia,
    Payment,
    Receipt,
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
)
from .utils import get_similar_listings_price_stats
import stripe
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

HERO_IMAGE_URLS = [
    'https://i.pinimg.com/originals/f0/a2/ea/f0a2eae1ff2863183dad317ab7b019df.jpg',
    'https://cdn.coconuts.co/coconuts/wp-content/uploads/2016/11/ubelt-2.jpg',
    'https://images.summitmedia-digital.com/spotph/images/2019/08/02/img-9953-1564737431.jpg',
    'https://th.bing.com/th/id/R.730eb9d6ab1e84c2e14d4c3a826600cb?rik=VxNJkin1Psi1QQ&riu=http%3a%2f%2fphotos.wikimapia.org%2fp%2f00%2f08%2f40%2f55%2f72_full.jpg&ehk=A%2fDQfdbcJANOjmKmnTm2E0yXelYacYoh2zSW4hD0f38%3d&risl=&pid=ImgRaw&r=0',
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

    campus = request.GET.get('campus')
    if campus:
        listings = listings.filter(campus=campus)

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
        condition, brand, size, author, attribute
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
    listing_with_image = Listing.objects.filter(is_sold=False, image__isnull=False)
    for slug, title, subtitle in CATEGORY_OVERVIEW:
        card_listing = listing_with_image.filter(category__slug=slug).order_by('-created_at').first()
        image_url = card_listing.image.url if card_listing and card_listing.image else None
        category_cards.append({
            'slug': slug,
            'name': title,
            'subtitle': subtitle,
            'image': image_url,
        })

    forum_posts = ForumPost.objects.filter(is_hidden=False).select_related('author', 'listing')[:3]

    return {
        'listings': listings,
        'newly_listed': newly_listed,
        'categories': categories,
        'schools': schools,
        'condition_choices': Listing.CONDITION_CHOICES,
        'campus_choices': Listing.CAMPUS_CHOICES,
        'query': q,
        'selected_category': category_slug,
        'selected_school': school_id,
        'min_price': min_price or '',
        'max_price': max_price or '',
        'condition': condition or '',
        'campus': campus or '',
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
            
            # Log in the user with the correct backend
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, 'Welcome! Your account has been created.')
            return redirect('marketplace:home')
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
        
    form = ListingForm(instance=listing, initial={'category': category})
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
        form = ListingForm(request.POST, request.FILES)
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
        form = ListingForm(initial=initial)

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
        form = ListingForm(request.POST, request.FILES, instance=listing)
        if form.is_valid():
            form.save()
            messages.success(request, 'Listing updated.')
            return redirect(listing.get_absolute_url())
    else:
        form = ListingForm(instance=listing)

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
    listing.save()
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
    if is_profile_owner and is_owner:
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
        'buyer_transactions': buyer_transactions,
        'seller_transactions': seller_transactions,
        'social_media_accounts': social_media_accounts,
    }
    
    return render(request, 'marketplace/public_profile.html', context)


@login_required
def leave_review(request, username):
    """Leave a vouch for a seller."""
    seller = get_object_or_404(User, username=username)
    
    if seller == request.user:
        messages.error(request, "You can't vouch for yourself.")
        return redirect('marketplace:public_profile', username=username)
    
    # Check if user has already left feedback
    existing_review = Review.objects.filter(reviewer=request.user, seller=seller).first()
    
    if request.method == 'POST':
        is_vouch_str = request.POST.get('is_vouch', 'true')
        is_vouch = is_vouch_str.lower() == 'true'
        comment = request.POST.get('comment', '')
        
        if existing_review:
            old_is_vouch = existing_review.is_vouch
            existing_review.is_vouch = is_vouch
            existing_review.comment = comment
            existing_review.save()
            # Adjust vouch count if vouch status changed
            if is_vouch and not old_is_vouch:
                seller.profile.vouch_count += 1
                seller.profile.update_verification_tier()
                seller.profile.save()
            elif not is_vouch and old_is_vouch:
                seller.profile.vouch_count = max(0, seller.profile.vouch_count - 1)
                seller.profile.update_verification_tier()
                seller.profile.save()
            messages.success(request, 'Your vouch has been updated.')
        else:
            review = Review.objects.create(
                reviewer=request.user,
                seller=seller,
                is_vouch=is_vouch,
                comment=comment
            )
            # Increment vouch count if it's a vouch
            if is_vouch:
                seller.profile.vouch_count += 1
                seller.profile.update_verification_tier()
                seller.profile.save()
            messages.success(request, 'Your vouch has been posted!')
        
        return redirect('marketplace:public_profile', username=username)
    
    context = {
        'seller': seller,
        'existing_review': existing_review,
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

    # WTS: Can't buy own listing
    # WTB: Can't offer own listing (request.user can't be the one who posted the WTB)
    if not is_wtb and listing.seller == request.user:
        messages.error(request, "You can't buy your own listing!")
        return redirect(listing.get_absolute_url())
    
    if is_wtb and listing.seller == request.user:
        messages.error(request, "You can't provide an item to your own WTB listing!")
        return redirect(listing.get_absolute_url())
    
    # Can't buy/provide sold listings
    if listing.is_sold:
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
        form = PurchaseForm(request.POST)
        if form.is_valid():
            transaction = Transaction.objects.create(
                buyer=buyer,
                seller=seller,
                listing=listing,
                price=offer_amount if offer_amount else listing.price,
                exchange_method=form.cleaned_data['exchange_method'],
                notes=form.cleaned_data['notes'],
                status='pending'
            )
            
            # Create notification for the other party
            if is_wtb:
                # WTB: notify the seller (request.user) that buyer wants to confirm
                notified_user = seller
                notification_message = f"{buyer.username} is ready to buy your {listing.title} for ₱{transaction.price:,.2f}"
            else:
                # WTS: notify the seller (listing.seller) that buyer wants to buy
                notified_user = seller
                notification_message = f"{buyer.username} wants to buy {listing.title}"
            
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
        form = PurchaseForm()
    
    return render(request, 'marketplace/purchase_form.html', {
        'form': form,
        'listing': listing,
        'seller': seller if is_wtb else listing.seller,
        'meetup_points': SUGGESTED_MEETUP_POINTS,
        'offer_amount': offer_amount,
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
                from django.utils import timezone
                from django.urls import reverse

                transaction = confirm_form.save(commit=False)
                transaction.status = 'confirmed'
                transaction.confirmed_at = timezone.now()
                transaction.save()

                # Take listing down if it's confirmed (meetup phase)
                if transaction.listing:
                    transaction.listing.is_sold = True
                    transaction.listing.save()
                
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

        # Any party sending a message within the transaction
        elif action == 'message':
            message_form = MessageForm(request.POST)
            if message_form.is_valid():
                from django.urls import reverse

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
            transaction = form.save(commit=False)
            transaction.status = 'confirmed'
            transaction.confirmed_at = timezone.now()
            transaction.save()
            
            # Mark listing as sold
            if transaction.listing:
                transaction.listing.is_sold = True
                transaction.listing.save()

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

    # Require POST to prevent CSRF via GET links
    if request.method != 'POST':
        return redirect('marketplace:transaction_detail', transaction_id=transaction.pk)

    from django.urls import reverse
    if request.user == transaction.buyer:
        transaction.buyer_completed = True
        status_msg = "You've marked this purchase as successful."
        other_party = transaction.seller
        other_msg = f"{request.user.username} (Buyer) confirmed the exchange. Please confirm on your end."
    else:
        transaction.seller_completed = True
        status_msg = "You've marked this sale as successful."
        other_party = transaction.buyer
        other_msg = f"{request.user.username} (Seller) confirmed the exchange. Please confirm on your end."
    
    if transaction.buyer_completed and transaction.seller_completed:
        from django.utils import timezone
        transaction.status = 'completed'
        transaction.completed_at = timezone.now()
        
        if transaction.listing:
            transaction.listing.is_sold = True
            transaction.listing.save()
            
        seller_profile = getattr(transaction.seller, 'profile', None) or Profile.objects.filter(user=transaction.seller).first()
        buyer_profile = getattr(transaction.buyer, 'profile', None) or Profile.objects.filter(user=transaction.buyer).first()
        
        if seller_profile:
            seller_profile.total_sold += 1
            seller_profile.update_verification_tier()
            seller_profile.save()

        if buyer_profile:
            buyer_profile.update_verification_tier()
            buyer_profile.save()

        # Notify both
        Notification.objects.create(
            user=transaction.seller,
            message="Mutual confirmation received! Sale fully completed.",
            notification_type='transaction',
            url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.pk})
        )
        Notification.objects.create(
            user=transaction.buyer,
            message="Mutual confirmation received! You can now leave a review.",
            notification_type='transaction',
            url=reverse('marketplace:leave_review', kwargs={'username': transaction.seller.username})
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
        from django.utils import timezone
        # Restore listing to available if it was marked sold during confirmation
        if transaction.status == 'confirmed' and transaction.listing:
            transaction.listing.is_sold = False
            transaction.listing.save()

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
        if amount:
            try:
                amount = float(amount)
                other_user = conversation.participants.exclude(id=request.user.id).first()
                
                body = f"OFFER: ₱{amount:,.2f}"
                msg = Message.objects.create(
                    conversation=conversation,
                    sender=request.user,
                    body=body,
                    is_offer=True,
                    offer_amount=amount,
                    offer_status='pending'
                )
                
                Notification.objects.create(
                    user=other_user,
                    related_user=request.user,
                    message=f"New offer for {conversation.listing.title if conversation.listing else 'an item'}: ₱{amount:,.2f}",
                    notification_type='offer',
                    url=reverse('marketplace:conversation', kwargs={'pk': conversation.pk})
                )
                
                messages.success(request, f"Offer of ₱{amount:,.2f} sent!")
            except ValueError:
                messages.error(request, "Invalid offer amount.")
                
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
        message.body = f"ACCEPTED OFFER: ₱{message.offer_amount:,.2f}"
        
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
        message.body = f"DECLINED OFFER: ₱{message.offer_amount:,.2f}"
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


def mod_dashboard(request):
    """Moderation dashboard: overview, quick stats, recent activity."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        messages.error(request, 'Access denied.')
        return redirect('marketplace:home')

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
            ModerationLog.objects.create(actor=request.user, action=log_action, target_model=content_type, target_id=pk, reason=reason)
            messages.success(request, f'{content_type.capitalize()} hidden.')
        elif action == 'restore':
            obj.is_hidden = False
            obj.moderation_notes = ''
            obj.save()
            log_action = 'restore_forum_post' if content_type == 'post' else 'restore_forum_reply'
            ModerationLog.objects.create(actor=request.user, action=log_action, target_model=content_type, target_id=pk, reason=reason)
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
            ModerationLog.objects.create(actor=request.user, action='hide_message', target_model='message', target_id=pk, reason=reason)
            messages.success(request, 'Message hidden.')
        elif action == 'restore':
            msg.is_hidden = False
            msg.moderation_notes = ''
            msg.save()
            ModerationLog.objects.create(actor=request.user, action='restore_message', target_model='message', target_id=pk, reason=reason)
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

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_note':
            transaction.admin_notes = request.POST.get('admin_notes', '')
            transaction.save()
            ModerationLog.objects.create(actor=request.user, action='add_transaction_note', target_model='transaction', target_id=transaction_id, reason=transaction.admin_notes[:200])
            messages.success(request, 'Note saved.')
        elif action == 'flag':
            transaction.flagged_for_review = True
            transaction.save()
            ModerationLog.objects.create(actor=request.user, action='flag_transaction', target_model='transaction', target_id=transaction_id, reason=request.POST.get('reason', ''))
            messages.success(request, 'Transaction flagged for review.')
        elif action == 'unflag':
            transaction.flagged_for_review = False
            transaction.save()
            ModerationLog.objects.create(actor=request.user, action='unflag_transaction', target_model='transaction', target_id=transaction_id, reason='')
            messages.success(request, 'Flag removed.')
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
                ModerationLog.objects.create(actor=request.user, action='admin_cancel_transaction', target_model='transaction', target_id=transaction_id, reason=reason)
                messages.success(request, 'Transaction cancelled by admin. Reason logged for audit.')
        return redirect('marketplace:mod_transaction_detail', transaction_id=transaction_id)

    return render(request, 'marketplace/mod/transaction_detail.html', {
        'transaction': transaction,
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
    return render(request, 'marketplace/mod/mod_log.html', {'logs': logs})


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

    # Check if payment is already completed
    if hasattr(transaction, 'payment') and transaction.payment.status == 'completed':
        messages.info(request, "This transaction has already been paid.")
        return redirect('marketplace:transaction_detail', transaction_id=transaction_id)

    if request.method == 'GET':
        # Prepare context for GET request
        exchange_method = request.GET.get('method', transaction.exchange_method)
        
        context = {
            'transaction': transaction,
            'exchange_method': exchange_method,
            'stripe_public_key': settings.STRIPE_PUBLIC_KEY,
        }

        # ALWAYS create PaymentIntent for credit card transactions
        # This ensures clientSecret is available even if user changes payment method on frontend
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

        # Route to appropriate payment method page
        if exchange_method == 'credit_card':
            # The frontend sends the PaymentIntent ID after confirmCardPayment succeeds
            payment_intent_id = request.POST.get('payment_intent_id', '').strip()
            if not payment_intent_id or not payment_intent_id.startswith('pi_'):
                messages.error(request, "Invalid payment details. Please try again.")
                return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

            try:
                intent = stripe.PaymentIntent.retrieve(payment_intent_id)

                # Verify this PaymentIntent belongs to the correct transaction (prevent spoofing)
                if intent.metadata.get('transaction_id') != str(transaction.id):
                    messages.error(request, "Payment reference mismatch. Please contact support.")
                    return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

                if intent.status == 'succeeded':
                    payment, created = Payment.objects.update_or_create(
                        transaction=transaction,
                        defaults={
                            'stripe_charge_id': intent.id,
                            'amount': transaction.price,
                            'status': 'completed',
                            'payment_method': 'credit_card',
                        }
                    )

                    # Create receipt for credit card payment
                    receipt = _create_receipt(transaction, payment)
                    receipt.status = 'confirmed'
                    receipt.confirmed_at = timezone.now()
                    receipt.save()

                    transaction.status = 'confirmed'
                    transaction.confirmed_at = timezone.now()
                    transaction.save()

                    # Notify seller
                    Notification.objects.create(
                        user=transaction.seller,
                        related_user=transaction.buyer,
                        message=f'{transaction.buyer.username} paid ₱{transaction.price} via credit card for {transaction.listing.title if transaction.listing else "your item"}',
                        notification_type='transaction',
                        url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.id}),
                    )

                    messages.success(request, "Payment successful! Your receipt has been saved to your inbox.")
                    return redirect('marketplace:receipt_detail', receipt_id=receipt.id)
                else:
                    messages.error(request, f"Payment not completed. Status: {intent.status}")
                    return redirect('marketplace:payment_cancel', transaction_id=transaction_id)

            except stripe.error.CardError as e:
                messages.error(request, f"Card error: {e.user_message}")
                return redirect('marketplace:payment_cancel', transaction_id=transaction_id)
            except stripe.error.StripeError as e:
                messages.error(request, f"Payment error: {str(e)}")
                return redirect('marketplace:payment_cancel', transaction_id=transaction_id)

        elif exchange_method == 'gcash':
            return redirect('marketplace:payment_gcash', transaction_id=transaction_id)
        
        elif exchange_method == 'bank_transfer':
            return redirect('marketplace:payment_bank_transfer', transaction_id=transaction_id)
        
        elif exchange_method == 'in_person':
            return redirect('marketplace:payment_cash_arrangement', transaction_id=transaction_id)
        
        elif exchange_method == 'other':
            return redirect('marketplace:payment_other_arrangement', transaction_id=transaction_id)
        
        else:
            messages.error(request, "Invalid payment method selected.")
            return redirect('marketplace:payment_checkout', transaction_id=transaction_id)

    return render(request, 'marketplace/payment_checkout.html', {'transaction': transaction})


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
    processing_fee = 0
    if payment and payment.payment_method == 'credit_card':
        processing_fee = float(transaction.price) * 0.02
    
    total_amount = float(transaction.price) + processing_fee
    
    receipt, created = Receipt.objects.get_or_create(
        transaction=transaction,
        defaults={
            'payment': payment,
            'receipt_number': receipt_number,
            'buyer': transaction.buyer,
            'seller': transaction.seller,
            'listing_title': transaction.listing.title if transaction.listing else 'Item',
            'listing_price': transaction.price,
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
    
    if request.method == 'POST':
        # Create payment record
        payment, created = Payment.objects.update_or_create(
            transaction=transaction,
            defaults={
                'stripe_charge_id': f'gcash_{transaction.id}_{timezone.now().timestamp()}',
                'amount': transaction.price,
                'status': 'completed',
                'payment_method': 'gcash',
            }
        )
        
        # Create receipt
        receipt = _create_receipt(transaction, payment)
        receipt.status = 'confirmed'
        receipt.confirmed_at = timezone.now()
        receipt.save()
        
        # Notify seller
        Notification.objects.create(
            user=transaction.seller,
            related_user=transaction.buyer,
            message=f'{transaction.buyer.username} paid ₱{transaction.price} via GCash for {transaction.listing.title if transaction.listing else "your item"}',
            notification_type='transaction',
            url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.id}),
        )
        
        messages.success(request, "Payment recorded! Your receipt has been saved to your inbox.")
        return redirect('marketplace:receipt_detail', receipt_id=receipt.id)
    
    context = {
        'transaction': transaction,
        'payment_method': 'gcash',
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
    
    if request.method == 'POST':
        # Get seller's bank details from profile or use placeholder
        seller_bank_info = transaction.seller.profile.contact_info or "Bank details to be provided by seller"
        
        # Create payment record
        payment, created = Payment.objects.update_or_create(
            transaction=transaction,
            defaults={
                'stripe_charge_id': f'bank_{transaction.id}_{timezone.now().timestamp()}',
                'amount': transaction.price,
                'status': 'pending',  # Pending until seller confirms receipt
                'payment_method': 'bank_transfer',
            }
        )
        
        # Create receipt
        receipt = _create_receipt(transaction, payment)
        receipt.status = 'pending'
        receipt.save()
        
        # Notify seller
        Notification.objects.create(
            user=transaction.seller,
            related_user=transaction.buyer,
            message=f'{transaction.buyer.username} has initiated a bank transfer of ₱{transaction.price} for {transaction.listing.title if transaction.listing else "your item"}. Please confirm receipt.',
            notification_type='transaction',
            url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.id}),
        )
        
        messages.success(request, "Bank transfer request registered. Your receipt has been saved. The seller will confirm receipt.")
        return redirect('marketplace:receipt_detail', receipt_id=receipt.id)
    
    context = {
        'transaction': transaction,
        'payment_method': 'bank_transfer',
        'seller_phone': transaction.seller.profile.phone or '',
        'seller_name': transaction.seller.profile.display_name or transaction.seller.username,
    }
    return render(request, 'marketplace/payment_bank_transfer.html', context)


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
    
    if request.method == 'POST':
        # Create payment record
        payment, created = Payment.objects.update_or_create(
            transaction=transaction,
            defaults={
                'stripe_charge_id': f'cash_{transaction.id}_{timezone.now().timestamp()}',
                'amount': transaction.price,
                'status': 'completed',
                'payment_method': 'in_person',
            }
        )
        
        # Create receipt
        receipt = _create_receipt(transaction, payment)
        receipt.status = 'confirmed'
        receipt.confirmed_at = timezone.now()
        receipt.save()
        
        # Notify seller
        Notification.objects.create(
            user=transaction.seller,
            related_user=transaction.buyer,
            message=f'{transaction.buyer.username} is ready to meet and pay ₱{transaction.price} in cash for {transaction.listing.title if transaction.listing else "your item"}',
            notification_type='transaction',
            url=reverse('marketplace:transaction_detail', kwargs={'transaction_id': transaction.id}),
        )
        
        messages.success(request, "Cash meeting arrangement confirmed. Your receipt has been saved to your inbox.")
        return redirect('marketplace:receipt_detail', receipt_id=receipt.id)
    
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
    
    if request.method == 'POST':
        arrangement_details = request.POST.get('arrangement_details', '').strip()
        
        if not arrangement_details:
            messages.error(request, "Please provide details of your arrangement with the seller.")
            return redirect('marketplace:payment_other_arrangement', transaction_id=transaction_id)
        
        # Create payment record
        payment, created = Payment.objects.update_or_create(
            transaction=transaction,
            defaults={
                'stripe_charge_id': f'other_{transaction.id}_{timezone.now().timestamp()}',
                'amount': transaction.price,
                'status': 'pending',
                'payment_method': 'other',
            }
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



