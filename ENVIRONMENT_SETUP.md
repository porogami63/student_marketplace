# Environment Configuration Guide

This guide explains how to set up your environment variables for the Student Marketplace, particularly for Gemini AI recommendations.

## Quick Setup (Development)

### 1. Create a `.env` file in the project root

```bash
# Linux/Mac
touch .env

# Windows PowerShell
New-Item -Path . -Name ".env" -ItemType "file"
```

### 2. Add your Gemini API Key

1. Get your API key from [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Add it to your `.env` file:

```
GEMINI_API_KEY=AIza_YOUR_API_KEY_HERE
```

### 3. Verify Installation

The project already supports loading `.env` files automatically. Just add your key and restart Django:

```bash
python manage.py runserver
```

## Getting Your Gemini API Key

1. Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Click "Create API Key" button
3. Select or create a Google Cloud project
4. Copy the generated API key (starts with `AIza...`)
5. Paste it in your `.env` file

## Environment Variables

### Required for Gemini AI

- `GEMINI_API_KEY` - Your Google Gemini API key (required for AI recommendations)

### Optional

- `DJANGO_SECRET_KEY` - Django secret key (defaults to development key)
- `DEBUG` - Debug mode (defaults to True)

## Testing Your Setup

### Test 1: Check if API key is loaded

```bash
python manage.py shell
```

```python
import os
api_key = os.getenv('GEMINI_API_KEY')
print(f"API Key loaded: {bool(api_key)}")
print(f"Key prefix: {api_key[:10] if api_key else 'None'}...")
```

### Test 2: Test Gemini API Connection

```bash
python manage.py shell
```

```python
import google.generativeai as genai
import os

api_key = os.getenv('GEMINI_API_KEY')
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content("Test message: respond with 'Success'")
    print(response.text)
else:
    print("ERROR: GEMINI_API_KEY not set")
```

### Test 3: Test Recommendations Endpoint

Make sure you're logged in first, then visit:
```
http://localhost:8000/marketplace/recommended/
```

Check browser console (F12) for any errors.

## Troubleshooting

### "GEMINI_API_KEY not set" Error

**Problem**: Recommendations show error or don't load

**Solutions**:
1. Verify `.env` file exists in project root (same directory as `manage.py`)
2. Check the `.env` file has the correct format:
   ```
   GEMINI_API_KEY=AIza_your_key_here
   ```
   (No quotes needed)
3. Restart Django: `python manage.py runserver`
4. Verify in Python shell:
   ```python
   import os
   print(os.getenv('GEMINI_API_KEY'))
   ```

### "HTTP 403 - Invalid API Key" Error

**Problem**: API returns forbidden error

**Solutions**:
1. Verify key is correct (copy again from Google AI Studio)
2. Key may have been revoked - generate a new one
3. Ensure key has access to Generative AI API

### "HTTP 429 - Rate Limited" Error

**Problem**: Too many requests to Gemini API

**Solutions**:
1. Check usage in [Google Cloud Console](https://console.cloud.google.com/billing)
2. Set up billing alert
3. Upgrade account tier if needed
4. Recommendations include natural rate limiting (cached for 1 hour)

## Production Deployment

For production environments, use your platform's secret management:

### AWS
- Use AWS Secrets Manager
- Add to Lambda environment variables
- Or use Systems Manager Parameter Store

### Heroku
```bash
heroku config:set GEMINI_API_KEY=AIza_your_key_here
```

### Docker
```dockerfile
ENV GEMINI_API_KEY=${GEMINI_API_KEY}
```

Or pass at runtime:
```bash
docker run -e GEMINI_API_KEY=AIza_your_key_here ...
```

### Azure
- Use Azure Key Vault
- Reference in App Service configuration

## Security Best Practices

1. ✅ Keep `.env` in `.gitignore` (already configured)
2. ✅ Never commit API keys to version control
3. ✅ Rotate keys regularly (delete old ones)
4. ✅ Use per-environment keys when possible
5. ✅ Monitor API usage for unusual activity
6. ✅ Use service accounts instead of personal keys

## More Information

- [Gemini API Setup Guide](./GEMINI_API_SETUP.md)
- [Design Recommendations](./DESIGN_RECOMMENDATIONS.md)
- [Google AI Studio](https://makersuite.google.com/app/apikey)
- [Google Cloud Console](https://console.cloud.google.com)
