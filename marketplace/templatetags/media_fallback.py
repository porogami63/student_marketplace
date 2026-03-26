from __future__ import annotations

from pathlib import Path

from django import template
from django.conf import settings

register = template.Library()


@register.filter
def media_or_static(media_field, static_fallback_prefix: str = "media/") -> str:
    """Return a URL for a FileField/ImageField with a static fallback.

    Order:
    1) If the field has a usable `.url`, return it (normal MEDIA_URL path).
    2) If not, try a static fallback under `STATIC_URL/<static_fallback_prefix><relative_name>`.
       This supports the workflow where existing `media/` is copied into `static/media/`.
    3) Otherwise return empty string.

    `static_fallback_prefix` should usually be "media/".
    """

    if not media_field:
        return ""

    name = getattr(media_field, "name", "") or ""
    # Try primary URL first.
    try:
        url = getattr(media_field, "url", "")
        if url:
            return url
    except Exception:
        pass

    if not name:
        return ""

    # Static fallback: STATIC_ROOT is used on Render after collectstatic,
    # but locally we can still generate the URL regardless.
    static_url = settings.STATIC_URL.rstrip("/") + "/"
    prefix = (static_fallback_prefix or "").lstrip("/")
    return static_url + prefix + name.lstrip("/")


@register.filter
def has_media_or_static(media_field, static_fallback_prefix: str = "media/") -> bool:
    """Best-effort existence check for template conditionals.

    We avoid hitting storage backends during template render where possible.
    If file storage can't be checked, we return True if a name is present.
    """

    if not media_field:
        return False

    name = getattr(media_field, "name", "") or ""
    if not name:
        return False

    # If storage supports `exists`, use it.
    storage = getattr(media_field, "storage", None)
    if storage is not None and hasattr(storage, "exists"):
        try:
            return bool(storage.exists(name))
        except Exception:
            pass

    # Try local filesystem check for common FileSystemStorage.
    try:
        media_root = Path(getattr(settings, "MEDIA_ROOT", ""))
        if media_root:
            if (media_root / name).exists():
                return True
    except Exception:
        pass

    # Static fallback presence check (works locally if static/media exists).
    try:
        base_dir = Path(getattr(settings, "BASE_DIR", "."))
        static_path = base_dir / "static" / (static_fallback_prefix or "") / name
        if static_path.exists():
            return True
    except Exception:
        pass

    # Last resort: assume present if name exists.
    return True
