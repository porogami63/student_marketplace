"""Custom template filters and tags for the marketplace."""
from django import template
import re

register = template.Library()


@register.filter
def extract_social_url(contact_info, platform):
    """
    Extract the URL/handle for a specific social media platform from contact_info.
    
    contact_info format: "facebook:url\ninstagram:url\ntwitter:url"
    Returns the URL/handle for the given platform, or # if not found.
    """
    if not contact_info:
        return '#'
    
    try:
        # List of known platforms to help parse corrupted data
        known_platforms = ['facebook', 'instagram', 'twitter', 'discord', 'whatsapp', 'telegram', 'linkedin', 'viber', 'x']
        
        # First, try normal parsing with newlines
        lines = contact_info.split('\n')
        for line in lines:
            line = line.strip()
            if line and ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                
                if key == platform.lower() and value:
                    # Check if value is already a clean URL/handle
                    if not any(f'{p}:' in value for p in known_platforms):
                        # Clean value, construct URL
                        return construct_social_url(platform, value)
        
        # If normal parsing didn't work, try to extract from corrupted data
        # Look for the pattern platform_name:value
        platform_lower = platform.lower()
        
        # Find where this platform starts
        search_pattern = f'{platform_lower}:'
        start_idx = contact_info.lower().find(search_pattern)
        
        if start_idx != -1:
            # Start after the platform name and colon
            value_start = start_idx + len(search_pattern)
            value_end = len(contact_info)
            
            # First check for newline after value (most reliable boundary)
            newline_idx = contact_info.find('\n', value_start)
            if newline_idx != -1:
                value_end = newline_idx
            
            # Then look for the next platform marker (another platform name followed by :)
            for other_platform in known_platforms:
                if other_platform != platform_lower:
                    next_platform_pattern = f'{other_platform}:'
                    next_idx = contact_info.lower().find(next_platform_pattern, value_start)
                    if next_idx != -1 and next_idx < value_end:
                        value_end = next_idx
            
            # Extract and clean the value
            value = contact_info[value_start:value_end].strip()
            
            if value:
                # Remove trailing platform marker if present
                for other_platform in known_platforms:
                    if f'{other_platform}:' in value:
                        idx = value.lower().find(f'{other_platform}:')
                        value = value[:idx].strip()
                        break
                
                if value:
                    return construct_social_url(platform, value)
    
    except Exception as e:
        pass
    
    return '#'


def construct_social_url(platform, value):
    """Construct a full URL from a platform name and value/handle."""
    platform = platform.lower().strip()
    value = value.strip()
    
    if not value:
        return '#'
    
    # If it's already a full URL, return as-is
    if value.startswith('http://') or value.startswith('https://'):
        return value
    
    # Remove leading @ if present in the input
    clean_value = value
    if clean_value.startswith('@'):
        clean_value = clean_value[1:]
    
    # Remove leading + for phone numbers (WhatsApp/Viber)
    if clean_value.startswith('+'):
        clean_phone = clean_value[1:]
    else:
        clean_phone = clean_value
    
    try:
        if platform == 'facebook':
            return f'https://www.facebook.com/{clean_value}'
        elif platform == 'instagram':
            return f'https://www.instagram.com/{clean_value}'
        elif platform == 'twitter':
            return f'https://www.twitter.com/{clean_value}'
        elif platform == 'x':
            return f'https://www.x.com/{clean_value}'
        elif platform == 'linkedin':
            if '/in/' in clean_value:
                return f'https://www.linkedin.com/{clean_value}'
            else:
                return f'https://www.linkedin.com/in/{clean_value}'
        elif platform == 'discord':
            # Discord accepts both user IDs and usernames
            return f'https://discord.com/users/{clean_value}'
        elif platform == 'whatsapp':
            return f'https://wa.me/{clean_phone}'
        elif platform == 'telegram':
            return f'https://t.me/{clean_value}'
        elif platform == 'viber':
            if value.startswith('+'):
                return f'viber://contact?number={value}'
            else:
                return f'viber://chat?number={value}'
        else:
            return '#'
    except Exception as e:
        return '#'


@register.filter
def payment_method_display(payment_method):
    """Convert payment method code to human-readable format."""
    payment_method_map = {
        'credit_card': 'Credit Card',
        'gcash': 'GCash',
        'bank_transfer': 'Bank Transfer',
        'in_person': 'In-Person Cash',
        'third_party_delivery': 'Third-Party Delivery',
        'other': 'Other Arrangement',
    }
    return payment_method_map.get(payment_method, payment_method)
