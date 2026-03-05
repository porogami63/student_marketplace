# Gemini API Setup Guide

This document explains how to set up and configure the Google Generative AI (Gemini) API for the marketplace's AI-powered recommendation system.

## Overview

The marketplace uses Google's Gemini API to generate personalized product recommendations based on user preferences and browsing history. The AI analyzes:

- User's favorite items
- Item categories and descriptions
- User's school and profile information
- Browsing patterns

## Requirements

1. **Google Cloud Account** - A free account at [console.cloud.google.com](https://console.cloud.google.com)
2. **API Key** - From Google's Generative AI API
3. **Python Package** - `google-generativeai` (already in requirements.txt)

## Setup Steps

### 1. Get Your Gemini API Key

1. Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Click "Create API Key" button
3. Copy your API key (it starts with `AIza...`)
4. **Keep this key secure** - never commit it to version control

### 2. Configure Environment Variable

Add your API key to your environment:

**Option A: Using .env file (Development)**

Create a `.env` file in the project root:
```
GEMINI_API_KEY=your_api_key_here
```

Then load it in your Django settings or use python-dotenv:
```python
from dotenv import load_dotenv
load_dotenv()
```

**Option B: System Environment Variable (Production)**

```bash
# Linux/Mac
export GEMINI_API_KEY="your_api_key_here"

# Windows (Command Prompt)
set GEMINI_API_KEY=your_api_key_here

# Windows (PowerShell)
$env:GEMINI_API_KEY="your_api_key_here"

# Docker / Production servers
# Add to your deployment platform's secrets/environment variables
```

### 3. Install Dependencies

The `google-generativeai` package is already in `requirements.txt`. Install it:

```bash
pip install -r requirements.txt
```

## Testing the Setup

### Test API Connection

Run this in Django shell:
```bash
python manage.py shell
```

```python
import os
import google.generativeai as genai

api_key = os.getenv('GEMINI_API_KEY')
genai.configure(api_key=api_key)

model = genai.GenerativeModel('gemini-pro')
response = model.generate_content("Test message")
print(response.text)
```

If you see text output, your setup is working!

### Test Recommendations Endpoint

Once logged in:

```bash
curl http://localhost:8000/marketplace/api/recommendations/gemini/ \
  -H "Cookie: sessionid=your_session_id"
```

Or visit the URL in your browser (must be logged in as an authenticated user).

## How It Works

### Recommendation Flow

1. User is on **favorites page** or **home page**
2. JavaScript loads recommendations via `recommendations.js`
3. JavaScript calls `/api/recommendations/gemini/` endpoint
4. Backend collects user's favorite items & profile data
5. Gemini API analyzes preferences
6. Recommendations are returned with AI-generated explanations
7. Cards display in the UI with "AI Pick" badge

### Features

✨ **Smart Matching** - Analyzes category preferences and user profile
💡 **Personalized Reasons** - Explains why each item is recommended
🎯 **Real Listings** - Only recommends active, unsold items
🚀 **Async Loading** - Doesn't block page load
📱 **Responsive Design** - Works on mobile and desktop

## Pricing

As of March 2025:
- **Gemini 1.5 Pro**: $7.50 per million input tokens, $30 per million output tokens
- **Free Tier**: Limited API calls available for testing
- Typical recommendation call: ~3000-5000 tokens per request

Monitor your usage at [Google Cloud Console](https://console.cloud.google.com/billing)

## Troubleshooting

### "GEMINI_API_KEY not set"

**Problem**: Recommendations show error message
**Solution**: 
- Verify environment variable is set: `echo $GEMINI_API_KEY` (Linux/Mac)
- Check your `.env` file exists and is in correct format
- Restart your Django server after setting environment variable

### "HTTP 429 - Rate Limited"

**Problem**: Too many API requests
**Solution**:
- Check your quota in Google Cloud Console
- Upgrade your billing plan
- Implement request caching

### "Invalid API Key"

**Problem**: API returns 403 error
**Solution**:
- Verify key is correct (copy from [Google AI Studio](https://makersuite.google.com/app/apikey))
- Check key hasn't been revoked/rotated
- Ensure key has access to Generative AI API

### Recommendations Not Showing

**Problem**: Container is empty or shows "No recommendations"
**Solutions**:
1. Check browser console for JavaScript errors
2. Verify user has at least 1 favorite item
3. Check `GEMINI_API_KEY` is configured
4. Review Django logs: `python manage.py runserver`
5. Test API endpoint directly: `/api/recommendations/gemini/`

## Security Best Practices

1. **Never commit API key** - Add `.env` to `.gitignore`
2. **Use secrets in production** - AWS Secrets Manager, Azure Key Vault, etc.
3. **Rotate keys regularly** - Delete old keys from Google Cloud
4. **Monitor usage** - Set up billing alerts
5. **Rate limiting** - Add per-user request throttling if needed

```python
# In settings.py (optional - rate limiting)
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        'recommendations': '50/hour',  # Custom throttle for AI endpoint
    }
}
```

## Implementation Details

### `get_gemini_recommendations()` Function

Located in `marketplace/utils.py`

```python
def get_gemini_recommendations(user_profile, favorite_listings, available_listings, max_recommendations=5):
    """
    Generate AI-powered recommendations using Google Gemini.
    
    Args:
        user_profile: User's profile with school/year level info
        favorite_listings: User's saved listings
        available_listings: Pool of listings to recommend from
        max_recommendations: Number of recommendations to return
    
    Returns:
        List of dicts: {'id': int, 'reason': str}
    """
```

### API Endpoint

Location: `/marketplace/api/recommendations/gemini/`
Method: `GET`
Auth: Required (login_required)
Response:
```json
{
    "recommendations": [
        {
            "id": 123,
            "title": "Python Textbook",
            "price": 450.00,
            "image_url": "/media/listings/book.jpg",
            "category": "Textbooks",
            "school_name": "UST",
            "seller_name": "john_doe",
            "ai_reason": "Perfect match based on your engineering textbook preferences",
            "view_count": 42,
            "url": "/listings/123/"
        }
    ],
    "count": 1
}
```

## Disabling AI Recommendations

To disable Gemini recommendations temporarily:

**Option 1: Remove from template**

Comment out in `home.html` and `favorites.html`:

```html
<!-- <div id="gemini-recommendations"></div> -->
```

**Option 2: Disable in JavaScript**

In `static/js/recommendations.js`, change:

```javascript
// Comment out this line:
// recommender.fetchRecommendations();
```

**Option 3: Disable API endpoint**

Remove from `marketplace/urls.py`:

```python
# path('api/recommendations/gemini/', views.api_gemini_recommendations, name='api_gemini_recommendations'),
```

## Future Improvements

- [ ] Implement caching for recommendations (Redis)
- [ ] Add recommendation feedback (user votes on quality)
- [ ] A/B testing for different recommendation algorithms
- [ ] Scheduled recommendation pre-generation
- [ ] Multi-language support
- [ ] Category-specific prompts for better accuracy

## Support & Documentation

- [Google Generative AI Documentation](https://ai.google.dev/docs)
- [Gemini API Reference](https://ai.google.dev/api)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [Firebase/Google Cloud Docs](https://firebase.google.com/docs)

## License

This implementation uses Google's Generative AI API under the [terms of service](https://policies.google.com/terms).
