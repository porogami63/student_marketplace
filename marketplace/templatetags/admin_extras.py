from django import template

register = template.Library()


@register.filter
def humanize_key(value):
    """Turn snake_case keys into a readable title.

    Example: "https_enforced" -> "Https Enforced"
    """
    if value is None:
        return ''
    text = str(value).replace('_', ' ').strip()
    # Collapse repeated whitespace
    text = ' '.join(text.split())
    return text.title()
