# Social Media Feature - New Implementation

## Overview

The social media feature has been completely redesigned with a **permanent, database-backed system** that allows users to easily add and manage multiple social media accounts on their profile.

## What's New

### ✅ Key Changes

1. **New `SocialMedia` Model** - Dedicated database table for storing social media accounts
   - Each user can have multiple social media accounts (one per platform)
   - Automatically generates clickable URLs based on platform
   - Permanent storage (no longer relying on browser localStorage)

2. **Clean User Interface**
   - Simple, intuitive form in profile settings
   - Add/remove social media accounts with one click
   - Visual feedback with platform icons and colors
   - Real-time updates without page refresh

3. **API Endpoints** (AJAX-based)
   - `POST /api/social-media/add/` - Add new social media account
   - `POST /api/social-media/remove/<platform>/` - Remove account
   - `GET /api/social-media/get/` - Fetch all accounts

## How to Use

### Adding Social Media Accounts

1. **Go to Your Profile Settings**
   - Click your profile icon → "View/Edit Profile"
   - Scroll to the "Social Media Accounts" section

2. **Add an Account**
   - Select a platform from the dropdown (Facebook, Instagram, Twitter, etc.)
   - Enter your handle/username or profile URL
   - Click "**+ Add**" (or press Enter)
   - The account will appear in the list below

3. **Remove an Account**
   - Click the "**Remove**" button next to any account
   - Confirm the action
   - Account is immediately removed

### Supported Platforms

- 📘 **Facebook** - facebook.com/yourname
- 📷 **Instagram** - @yourhandle or instagram.com/yourhandle
- 𝕏 **Twitter / X** - @yourhandle or twitter.com/yourhandle
- 💜 **Discord** - username#1234
- 💬 **WhatsApp** - +1234567890 or wa.me link
- 💼 **LinkedIn** - linkedin.com/in/yourname
- 📞 **Viber** - +1234567890 or viber link
- ✈️ **Telegram** - @yourhandle or t.me link

## Technical Details

### Database Schema

```
SocialMedia Model:
├── profile (ForeignKey → Profile)
├── platform (CharField) - One of the 8 platforms
├── handle (CharField) - Username or profile URL (max 255 chars)
├── created_at (DateTimeField) - Auto-set on creation
└── updated_at (DateTimeField) - Auto-updates on modification

Constraints:
- Unique together: (profile, platform)
  → One social media account per user per platform
```

### URLs Configuration

Added three new API endpoints in `urls.py`:
```python
path('api/social-media/add/', views.add_social_media, name='add_social_media'),
path('api/social-media/remove/<str:platform>/', views.remove_social_media, name='remove_social_media'),
path('api/social-media/get/', views.get_social_media, name='get_social_media'),
```

### Views/API Handlers

**`add_social_media(request)`**
- Method: POST
- Validates platform and handle
- Creates or updates SocialMedia record
- Returns: JSON with success status

**`remove_social_media(request, platform)`**
- Method: POST
- Deletes the social media record
- Returns: JSON with success status

**`get_social_media(request)`**
- Method: GET
- Returns all social media accounts for current user
- Includes generated URLs for each account
- Returns: JSON with list of accounts

### JavaScript Implementation

The template includes a self-contained JavaScript module that:
- ✅ Fetches accounts on page load
- ✅ Handles adding new accounts via AJAX
- ✅ Handles removing accounts via AJAX
- ✅ Provides real-time UI updates
- ✅ Shows loading states and error messages
- ✅ Validates input before submission

## Migration Applied

A new migration has been created and applied:
```
marketplace/migrations/0021_socialmedia.py
```

This creates the `marketplace_socialmedia` table with:
- Auto-incrementing ID
- Foreign key to Profile
- Platform choice field
- Handle text field
- Timestamps
- Unique constraint on (profile_id, platform)

## Admin Interface

Social media accounts can be managed via Django admin:
- **URL**: `/admin/marketplace/socialmedia/`
- **Features**:
  - View all accounts by user
  - Filter by platform
  - Search by username
  - Create/edit/delete accounts

## What Happens to Old Data?

The old `contact_info` field in the Profile model still exists (for backward compatibility), but is no longer used by the new social media system.

**Migration Path** (if needed):
The old localStorage-based system is completely replaced. If you want to populate the new SocialMedia table from existing contact_info data, a data migration can be created (contact developer).

## Security & Best Practices

1. **Validation**: Platform names and handles are validated on the server
2. **CSRF Protection**: All POST requests include CSRF tokens
3. **Authorization**: Only logged-in users can modify their own social media
4. **XSS Prevention**: All user input is properly escaped in templates
5. **Rate Limiting**: (Can be implemented if needed)

## Troubleshooting

### "Account not found" error
- The account may have been deleted
- Refresh the page and try again

### Duplicate accounts not allowed
- Each social media platform can only be added once per user
- Remove the old account if you want to update it

### Changes not saving
- Check browser console for error messages (F12)
- Ensure CSRF token is present in the page
- Verify you're logged in and have permission

### URL generation issues
- For custom URLs, paste the full profile URL instead of just the handle
- Examples:
  - Instagram: `instagram.com/username` or `@username`
  - LinkedIn: `linkedin.com/in/name` (will auto-detect)
  - WhatsApp: `wa.me/1234567890` (full link) or `+1234567890` (number)

## Future Enhancements

Potential improvements:
- [ ] Drag-to-reorder social media accounts
- [ ] Custom profile URLs/handles validation
- [ ] Social media profile verification icons
- [ ] Analytics on which social media drives the most messages
- [ ] Auto-linking social profiles to profile summary cards

## Support

For issues or questions about the social media feature:
1. Check this documentation
2. Review error messages in browser console
3. Check Django admin to verify data is being saved
4. Contact the development team with screenshots/error logs

---

**Version**: 1.0 (March 5, 2026)  
**Status**: ✅ Production Ready
