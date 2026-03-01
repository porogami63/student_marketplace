# Google OAuth Setup Guide for U-Belt Student Marketplace

Your Django project is now configured with Google OAuth via django-allauth. Follow these steps to complete the setup.

## Step 1: Create Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Navigate to "APIs & Services" > "Credentials"
4. Click "Create Credentials" > "OAuth client ID"
5. Choose "Web application"
6. Add authorized redirect URIs:
   - Development: `http://localhost:8000/accounts/google/login/callback/`
   - Production: `https://yourdomain.com/accounts/google/login/callback/`
7. Copy your **Client ID** and **Client Secret**

## Step 2: Add Google OAuth to Django Admin

1. Run your development server:
   ```bash
   python manage.py runserver
   ```

2. Go to `http://localhost:8000/admin/` and login with your admin account

3. Navigate to **Sites** and make sure your site domain matches your development/production URL:
   - Development: `localhost:8000`
   - Production: `yourdomain.com`

4. Go to **Social applications** and click "Add"

5. Fill in the form:
   - **Provider:** Google
   - **Name:** Google
   - **Client id:** (paste your Client ID from Google Cloud Console)
   - **Secret key:** (paste your Client Secret)
   - **Sites:** Select your site from the right panel

6. Click Save

## Step 3: Test Google Login

1. Go to `http://localhost:8000/accounts/login/`
2. You should see a "Sign in with Google" button
3. Click it and complete the Google authentication flow
4. You'll be redirected back and logged in!

## How It Works

When a user logs in with Google:
1. They're redirected to Google's login page
2. After authentication, they're redirected back to your site
3. If it's their first time, a new user account is created automatically
4. A Profile is automatically created for the user
5. Their Google avatar URL is saved in their Profile
6. Their full name from Google is populated in their Profile

## Features Enabled

✅ **Auto-signup** - Users can sign up via Google  
✅ **Profile Creation** - Automatic profile generation  
✅ **Avatar Sync** - Google profile picture URL is saved  
✅ **Name Population** - Full name is pulled from Google account  
✅ **Email Verification** - Optional (can be required in settings)  

## Settings Configuration

The following django-allauth settings are configured in `settings.py`:

```python
SOCIALACCOUNT_AUTO_SIGNUP = True           # Auto-create user accounts
SOCIALACCOUNT_QUERY_EMAIL = True           # Request email from Google
ACCOUNT_SIGNUP_REDIRECT_URL = LOGIN_REDIRECT_URL  # Redirect after signup
ACCOUNT_EMAIL_VERIFICATION = 'optional'    # Email verification is optional
```

## Troubleshooting

### "The redirect_uri parameter does not match any registered URI"
- Make sure you added the exact callback URL in Google Cloud Console
- Check that your Site domain in Django admin matches your dev/production URL

### User created but profile not updating
- Check that signals are loaded in `marketplace/apps.py`
- Profile creation is automatic via the `create_user_profile` signal

### Avatar not showing
- Make sure `google_avatar_url` is populated in the Profile
- In your templates, use `{{ user.profile.google_avatar_url }}` to display the avatar

### Email not being collected
- Ensure `SOCIALACCOUNT_QUERY_EMAIL = True` is set in settings.py
- The Google OAuth scope includes `'email'`

## Next Steps

1. **Customize the login/signup experience** - Edit `templates/account/login.html`
2. **Require email verification** - Change `ACCOUNT_EMAIL_VERIFICATION = 'mandatory'`
3. **Add more OAuth providers** - Install additional allauth providers (GitHub, Facebook, etc.)
4. **Deploy to production** - Update ALLOWED_HOSTS, SECRET_KEY, DEBUG, and database settings

## Useful Links

- [django-allauth Documentation](https://django-allauth.readthedocs.io/)
- [Google OAuth Documentation](https://developers.google.com/identity/protocols/oauth2)
- [Django Security Best Practices](https://docs.djangoproject.com/en/stable/topics/security/)
