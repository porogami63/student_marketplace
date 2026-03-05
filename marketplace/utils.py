"""Utility functions for the marketplace."""
from decimal import Decimal
from django.db.models import Avg, Count, Q
import os
import logging

from .models import Listing as ListingModel

logger = logging.getLogger(__name__)

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


def get_gemini_recommendations(user_profile, favorite_listings, available_listings, max_recommendations=5):
    """
    Use Google Gemini API to generate personalized item recommendations.
    
    Args:
        user_profile: User's profile object with preferences
        favorite_listings: QuerySet or list of user's favorite listings
        available_listings: QuerySet of available listings to recommend from
        max_recommendations: Number of recommendations to generate
    
    Returns:
        List of recommended listing IDs and brief AI-generated explanations
    """
    try:
        import google.generativeai as genai
    except ImportError:
        logger.warning("google-generativeai not installed. Returning empty recommendations.")
        return []
    
    # Check if API key is available
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        logger.warning("GEMINI_API_KEY not set in environment variables.")
        return []
    
    try:
        genai.configure(api_key=api_key)
        
        # Prepare favorite listing data
        favorites_info = []
        for fav in favorite_listings[:5]:  # Use last 5 favorites
            if hasattr(fav, 'listing'):
                listing = fav.listing
            else:
                listing = fav
            
            favorites_info.append(f"- {listing.title} (₱{listing.price}, Category: {listing.category.name if listing.category else 'Unknown'})")
        
        # Prepare available listings data (sample of available items)
        available_info = []
        available_sample = available_listings.values('id', 'title', 'price', 'category__name', 'description')[:20]
        for listing in available_sample:
            category = listing['category__name'] or 'Unknown'
            description = (listing['description'] or '')[:100]  # First 100 chars
            available_info.append(f"ID {listing['id']}: {listing['title']} (₱{listing['price']}, {category}) - {description}")
        
        # Create the prompt for Gemini
        user_school = user_profile.school.name if user_profile.school else "Unknown"
        prompt = f"""You are a smart marketplace recommendation system. Analyze the user's preferences and recommend the best items.

User Profile:
- School: {user_school}
- Year Level: {user_profile.get_year_level_display() if user_profile.year_level else 'Not specified'}
- Verified: {'Yes' if user_profile.verification_tier != 'grey' else 'No'}

User's Favorite Listings:
{chr(10).join(favorites_info) if favorites_info else 'No favorites yet'}

Available Listings to Recommend From:
{chr(10).join(available_info)}

Based on the user's favorites and profile, recommend the top {max_recommendations} listing IDs from the available listings that would best match their interests. 
Only recommend items that are NOT already favorited.
Respond in this exact format (one recommendation per line):
ID: <number> - Reason: <brief explanation of why this matches their interests>"""
        
        # Call Gemini API
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        
        # Parse the response
        recommendations = []
        if response and response.text:
            for line in response.text.strip().split('\n'):
                if 'ID:' in line:
                    try:
                        # Extract ID from "ID: 123 - Reason: ..."
                        parts = line.split('ID:')[1].split('-')
                        listing_id = int(parts[0].strip())
                        reason = parts[1].replace('Reason:', '').strip() if len(parts) > 1 else ''
                        
                        # Verify listing exists in available_listings
                        if available_listings.filter(id=listing_id).exists():
                            recommendations.append({
                                'id': listing_id,
                                'reason': reason[:200]  # Limit reason to 200 chars
                            })
                    except (ValueError, IndexError):
                        continue
        
        return recommendations[:max_recommendations]
    
    except Exception as e:
        logger.error(f"Error getting Gemini recommendations: {str(e)}")
        return []

def get_gemini_chat_response(user_message, available_listings=None, user_profile=None, conversation_history=None):
    """
    Get a response from Gemini AI for item recommendation chat.
    
    Args:
        user_message: User's question or message
        available_listings: QuerySet of available listings to consider
        user_profile: User's profile for personalization
        conversation_history: List of previous messages for context
    
    Returns:
        Dict with 'response' (text), 'recommendations' (listing IDs), or error info
    """
    try:
        import google.generativeai as genai
    except ImportError:
        logger.warning("google-generativeai not installed.")
        return {'error': 'AI service not available'}
    
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        logger.warning("GEMINI_API_KEY not set")
        return {'error': 'API key not configured'}
    
    try:
        genai.configure(api_key=api_key)
        
        # Prepare listings context
        if not available_listings:
            from .models import Listing
            available_listings = Listing.objects.filter(is_sold=False)
        
        listings_info = []
        listings_sample = available_listings.select_related('category', 'school').values_list(
            'id', 'title', 'price', 'category__name', 'school__name', 'description'
        )[:50]  # Prepare context with up to 50 listings
        
        for listing in listings_sample:
            listing_id, title, price, category, school, description = listing
            desc_preview = (description or '')[:80]
            school_str = f" ({school})" if school else ""
            listings_info.append(
                f"ID {listing_id}: {title}{school_str} - ₱{price} ({category}) - {desc_preview}"
            )
        
        # Build the system prompt
        profile_context = ""
        if user_profile:
            school_name = user_profile.school.name if user_profile.school else "Unknown"
            profile_context = f"\nUser's school: {school_name}\nUser verification status: {'Verified' if user_profile.verification_tier != 'grey' else 'Not verified'}"
        
        system_prompt = f"""You are a helpful marketplace assistant for UBXchange - a student marketplace app. 
You help users find items to buy from a list of available listings.

Available Listings in the Marketplace:
{chr(10).join(listings_info)}

User Context:{profile_context}

Guidelines:
1. Be friendly and conversational
2. When a user asks about items, search through the available listings
3. Recommend specific listings by their title and ID when relevant
4. Always include the listing ID (e.g., "ID 123") when mentioning items
5. Provide prices and be helpful with comparisons
6. If no exact match, suggest closest alternatives
7. Be concise but helpful
8. Format recommended items as: "ID [number]: [title] - ₱[price]"
9. Never make up listings that don't exist
10. Focus on helping the user find what they're looking for"""
        
        # Prepare conversation history for context
        messages = []
        if conversation_history:
            for msg in conversation_history[-10:]:  # Keep last 10 messages for context
                messages.append({
                    'role': msg.get('role', 'user'),
                    'parts': [msg.get('content', '')]
                })
        
        # Add current user message
        messages.append({
            'role': 'user',
            'parts': [user_message]
        })
        
        # Call Gemini with chat
        model = genai.GenerativeModel('gemini-2.5-flash', system_instruction=system_prompt)
        response = model.generate_content(messages)
        
        if not response or not response.text:
            return {'error': 'Failed to generate response'}
        
        response_text = response.text
        
        # Extract listing IDs mentioned in the response
        import re
        id_pattern = r'ID\s+(\d+)'
        mentioned_ids = [int(m) for m in re.findall(id_pattern, response_text)]
        
        # Validate IDs exist in our listings
        valid_ids = []
        if mentioned_ids:
            if not available_listings:
                from .models import Listing
                available_listings = Listing.objects.filter(is_sold=False)
            
            available_ids = set(available_listings.values_list('id', flat=True))
            valid_ids = [id for id in mentioned_ids if id in available_ids]
        
        return {
            'response': response_text,
            'recommendations': valid_ids[:5],  # Up to 5 recommendations per response
            'message_role': 'assistant'
        }
    
    except Exception as e:
        logger.error(f"Error in Gemini chat: {str(e)}")
        return {'error': f'Error: {str(e)[:100]}'}