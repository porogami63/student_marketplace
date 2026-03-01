"""Utility functions for the marketplace."""
from decimal import Decimal
from django.db.models import Avg, Count, Q

from .models import Listing as ListingModel

STOP_WORDS = frozenset({'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'ed', '1st', '2nd', '3rd'})


def get_similar_listings_price_stats(listing):
    """
    Get price statistics for similar listings.
    Returns dict with avg_price, count, tip (overpriced/fair/great_deal), or None if not enough data.
    """
    if not listing.category:
        return None

    # Get words from title (excluding stop words and short words)
    title_words = {
        w.lower() for w in listing.title.split()
        if len(w) > 2 and w.lower() not in STOP_WORDS
    }

    # Find similar listings: same category, not sold, exclude self
    base_qs = ListingModel.objects.filter(
        category=listing.category,
        is_sold=False
    ).exclude(pk=listing.pk)

    # Try to find listings with overlapping title words (more specific)
    similar_qs = base_qs.none()
    if title_words:
        word_filters = Q()
        for word in title_words:
            word_filters |= Q(title__icontains=word)
        similar_qs = base_qs.filter(word_filters)

    # Use similar-by-title if we have 2+ matches, else use category average
    qs = similar_qs if similar_qs.count() >= 2 else base_qs

    agg = qs.aggregate(avg=Avg('price'), count=Count('id'))

    if agg['count'] < 2 or agg['avg'] is None:
        return None

    avg_price = agg['avg']
    count = agg['count']

    price = listing.price
    diff_pct = float((price - avg_price) / avg_price) if avg_price else 0

    if diff_pct > 0.15:
        tip = 'overpriced'
    elif diff_pct < -0.15:
        tip = 'great_deal'
    else:
        tip = 'fair'

    return {
        'avg_price': Decimal(str(round(float(avg_price), 2))),
        'count': count,
        'tip': tip,
    }
