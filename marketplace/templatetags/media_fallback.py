from __future__ import annotations

from pathlib import Path

from django import template
from django.conf import settings

register = template.Library()


@register.filter
def media_path_or_static(value: str | None, static_fallback_prefix: str = "media/") -> str:
    """Convert a stored MEDIA_URL path into a STATIC_URL fallback.

    Used for cases where the DB stores a string path/URL (not a FileField), e.g.
    category card background images.

    - If value starts with MEDIA_URL (e.g. /media/xyz.jpg), return /static/media/xyz.jpg
    - If value starts with "media/", treat it similarly.
    - Otherwise return the value unchanged.
    """

    if not value:
        return ""

    value_str = str(value).strip()
    if not value_str:
        return ""

    media_url = getattr(settings, "MEDIA_URL", "/media/") or "/media/"
    if value_str.startswith(media_url):
        rel = value_str[len(media_url) :].lstrip("/")
        static_url = settings.STATIC_URL.rstrip("/") + "/"
        prefix = (static_fallback_prefix or "").lstrip("/")
        return static_url + prefix + rel

    if value_str.startswith("media/"):
        static_url = settings.STATIC_URL.rstrip("/") + "/"
        return static_url + value_str

    return value_str


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
    if not name:
        return ""

    static_url = settings.STATIC_URL.rstrip("/") + "/"
    prefix = (static_fallback_prefix or "").lstrip("/")
    static_fallback_url = static_url + prefix + name.lstrip("/")

    def _static_fallback_exists() -> bool:
        try:
            base_dir = Path(getattr(settings, "BASE_DIR", "."))
            static_path = base_dir / "static" / (static_fallback_prefix or "") / name
            return static_path.exists()
        except Exception:
            return False

    # If we're on FileSystemStorage (default), only use MEDIA_URL when the file
    # actually exists under MEDIA_ROOT.
    #
    # Important: only fall back to static/media if the static copy exists. This
    # avoids interfering with newly uploaded files that are present in MEDIA_ROOT
    # but (correctly) not present in static/media.
    storage = getattr(media_field, "storage", None)
    if storage is not None and storage.__class__.__name__ == "FileSystemStorage":
        try:
            media_root = Path(getattr(settings, "MEDIA_ROOT", ""))
            if media_root and not (media_root / name).exists():
                if _static_fallback_exists():
                    return static_fallback_url
        except Exception:
            # If we cannot verify, still attempt MEDIA_URL.
            pass

    # Try primary URL (MEDIA_URL) if appropriate.
    try:
        url = getattr(media_field, "url", "")
        if url and storage is not None:
            return url
        if url and storage is None and not (
            getattr(media_field, "storage", None) is not None
            and getattr(media_field.storage, "__class__", None) is not None
            and media_field.storage.__class__.__name__ == "FileSystemStorage"
        ):
            # Non-filesystem storages (e.g. S3) should keep using their native URLs.
            return url
    except Exception:
        pass

    # Static fallback: only if the static copy exists.
    if _static_fallback_exists():
        return static_fallback_url

    return ""


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
