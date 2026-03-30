from __future__ import annotations

import mimetypes
import shutil
import ssl
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand

from marketplace.models import Profile


HERO_IMAGE_SOURCES = [
    (
        "ubelt-street-crossing.jpg",
        "https://cdn.coconuts.co/coconuts/wp-content/uploads/2016/11/ubelt-2.jpg",
    ),
    (
        "ubelt-main-road.jpg",
        "https://images.summitmedia-digital.com/spotph/images/2019/08/02/img-9953-1564737431.jpg",
    ),
    (
        "ubelt-mendiola-arch.jpg",
        "https://i.pinimg.com/originals/f0/a2/ea/f0a2eae1ff2863183dad317ab7b019df.jpg",
    ),
    (
        "ubelt-campus-park.jpg",
        "https://th.bing.com/th/id/R.730eb9d6ab1e84c2e14d4c3a826600cb?rik=VxNJkin1Psi1QQ&riu=http%3a%2f%2fphotos.wikimapia.org%2fp%2f00%2f08%2f40%2f55%2f72_full.jpg&ehk=A%2fDQfdbcJANOjmKmnTm2E0yXelYacYoh2zSW4hD0f38%3d&risl=&pid=ImgRaw&r=0",
    ),
]


class Command(BaseCommand):
    help = (
        "Download hero images and sync profile media into MEDIA_ROOT and static/media "
        "for safer Render deployments."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-hero",
            action="store_true",
            help="Skip downloading/syncing hero images.",
        )
        parser.add_argument(
            "--skip-profiles",
            action="store_true",
            help="Skip syncing profile avatars/header images.",
        )
        parser.add_argument(
            "--force-hero",
            action="store_true",
            help="Re-download hero images even if local files already exist.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would happen without writing files or saving models.",
        )

    def handle(self, *args, **options):
        self.media_root = Path(settings.MEDIA_ROOT)
        self.base_dir = Path(settings.BASE_DIR)
        self.static_media_root = self.base_dir / "static" / "media"

        self.stats = {
            "hero_downloaded": 0,
            "hero_skipped": 0,
            "hero_failed": 0,
            "hero_recovered": 0,
            "profile_total": 0,
            "avatar_downloaded_from_google": 0,
            "avatar_restored_from_static": 0,
            "avatar_mirrored_to_static": 0,
            "header_restored_from_static": 0,
            "header_mirrored_to_static": 0,
            "profile_errors": 0,
        }

        dry_run = options["dry_run"]
        force_hero = options["force_hero"]

        self.stdout.write(self.style.NOTICE("Starting media sync for Render..."))

        if not options["skip_hero"]:
            self._sync_hero_images(force_hero=force_hero, dry_run=dry_run)

        if not options["skip_profiles"]:
            self._sync_profile_media(dry_run=dry_run)

        self.stdout.write("\nSummary:")
        for key, value in self.stats.items():
            self.stdout.write(f"  - {key}: {value}")

        if self.stats["hero_failed"] == 0 and self.stats["profile_errors"] == 0:
            self.stdout.write(self.style.SUCCESS("Media sync completed successfully."))
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Media sync completed with warnings. Check output above for failures."
                )
            )

    def _sync_hero_images(self, force_hero: bool, dry_run: bool):
        self.stdout.write("\nSyncing hero images...")
        for file_name, url in HERO_IMAGE_SOURCES:
            rel_path = Path("hero") / file_name
            media_path = self.media_root / rel_path

            if media_path.exists() and not force_hero:
                if self._is_valid_image_file(media_path):
                    self.stats["hero_skipped"] += 1
                    self._mirror_to_static(rel_path, dry_run=dry_run)
                    continue

                self.stdout.write(
                    self.style.WARNING(
                        f"  ! Existing hero file is invalid, re-downloading: {media_path.name}"
                    )
                )

            try:
                data, content_type = self._download_url(url)
                if not self._is_supported_image_payload(data, content_type):
                    raise ValueError(
                        f"non-image payload received (content-type: {content_type or 'unknown'})"
                    )
            except Exception as exc:
                self.stats["hero_failed"] += 1
                self.stdout.write(self.style.WARNING(f"  ! Failed to download {url}: {exc}"))
                continue

            if dry_run:
                self.stdout.write(f"  - Would save hero image: {media_path}")
                self.stats["hero_downloaded"] += 1
                continue

            media_path.parent.mkdir(parents=True, exist_ok=True)
            media_path.write_bytes(data)

            if not self._is_valid_image_file(media_path):
                self.stats["hero_failed"] += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  ! Saved hero image is invalid, removing: {media_path.name}"
                    )
                )
                media_path.unlink(missing_ok=True)
                continue

            self.stats["hero_downloaded"] += 1
            self.stdout.write(self.style.SUCCESS(f"  + Saved hero image: {media_path.name}"))
            self._mirror_to_static(rel_path, dry_run=dry_run)

        self._recover_missing_or_invalid_hero_images(dry_run=dry_run)

    def _recover_missing_or_invalid_hero_images(self, dry_run: bool):
        expected = [Path("hero") / file_name for file_name, _ in HERO_IMAGE_SOURCES]
        valid_sources = [
            rel_path
            for rel_path in expected
            if self._is_valid_image_file(self.media_root / rel_path)
        ]

        if not valid_sources:
            return

        fallback_source = valid_sources[0]
        fallback_abs = self.media_root / fallback_source

        for rel_path in expected:
            target_abs = self.media_root / rel_path
            if self._is_valid_image_file(target_abs):
                continue

            if dry_run:
                self.stdout.write(
                    f"  - Would recover hero image {rel_path.name} from {fallback_source.name}"
                )
                self.stats["hero_recovered"] += 1
                continue

            target_abs.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fallback_abs, target_abs)
            self._mirror_to_static(rel_path, dry_run=dry_run)
            self.stats["hero_recovered"] += 1
            self.stdout.write(
                self.style.WARNING(
                    f"  ! Recovered missing/invalid hero image {rel_path.name} from fallback {fallback_source.name}"
                )
            )

    def _is_valid_image_file(self, file_path: Path) -> bool:
        if not file_path.exists() or not file_path.is_file():
            return False

        try:
            data = file_path.read_bytes()
        except Exception:
            return False

        guessed_type, _ = mimetypes.guess_type(file_path.name)
        return self._is_supported_image_payload(data, guessed_type or "")

    def _is_supported_image_payload(self, data: bytes, content_type: str) -> bool:
        if not data:
            return False

        clean_type = (content_type or "").split(";", 1)[0].strip().lower()
        if clean_type.startswith("text/") or "html" in clean_type:
            return False

        if data.startswith(b"\xff\xd8\xff"):
            return True
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return True
        if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return True

        return False

    def _sync_profile_media(self, dry_run: bool):
        self.stdout.write("\nSyncing profile avatar/header media...")
        profiles = Profile.objects.select_related("user").all()
        self.stats["profile_total"] = profiles.count()

        for profile in profiles:
            try:
                self._sync_profile_avatar(profile, dry_run=dry_run)
                self._sync_profile_header(profile, dry_run=dry_run)
            except Exception as exc:
                self.stats["profile_errors"] += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  ! Profile {profile.user.pk} ({profile.user.username}) failed: {exc}"
                    )
                )

    def _sync_profile_avatar(self, profile: Profile, dry_run: bool):
        avatar_name = profile.avatar.name if profile.avatar else ""

        # Restore missing media file from static/media if possible.
        if avatar_name:
            restored = self._restore_missing_media_from_static(avatar_name, dry_run=dry_run)
            if restored:
                self.stats["avatar_restored_from_static"] += 1

            if (self.media_root / avatar_name).exists():
                mirrored = self._mirror_to_static(Path(avatar_name), dry_run=dry_run)
                if mirrored:
                    self.stats["avatar_mirrored_to_static"] += 1
            return

        # If no local avatar exists, try downloading google avatar URL to media.
        google_url = (profile.google_avatar_url or "").strip()
        if not google_url:
            return

        data, content_type = self._download_url(google_url)
        if not self._is_supported_image_payload(data, content_type):
            self.stdout.write(
                self.style.WARNING(
                    f"  ! Google avatar for user {profile.user.username} is not a valid image payload"
                )
            )
            return

        ext = self._guess_extension(google_url, content_type)
        rel_path = Path("avatars") / f"google_user_{profile.user.pk}{ext}"

        if dry_run:
            self.stdout.write(
                f"  - Would download Google avatar for user {profile.user.username}: {rel_path}"
            )
            self.stats["avatar_downloaded_from_google"] += 1
            return

        abs_path = self.media_root / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(data)

        profile.avatar.name = rel_path.as_posix()
        profile.save(update_fields=["avatar"])

        self.stats["avatar_downloaded_from_google"] += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"  + Downloaded Google avatar for user {profile.user.username} -> {rel_path.name}"
            )
        )

        mirrored = self._mirror_to_static(rel_path, dry_run=dry_run)
        if mirrored:
            self.stats["avatar_mirrored_to_static"] += 1

    def _sync_profile_header(self, profile: Profile, dry_run: bool):
        header_name = profile.header_image.name if profile.header_image else ""
        if not header_name:
            return

        restored = self._restore_missing_media_from_static(header_name, dry_run=dry_run)
        if restored:
            self.stats["header_restored_from_static"] += 1

        if (self.media_root / header_name).exists():
            mirrored = self._mirror_to_static(Path(header_name), dry_run=dry_run)
            if mirrored:
                self.stats["header_mirrored_to_static"] += 1

    def _restore_missing_media_from_static(self, file_name: str, dry_run: bool) -> bool:
        rel_path = Path(file_name)
        media_path = self.media_root / rel_path
        static_path = self.static_media_root / rel_path

        if media_path.exists() or not static_path.exists():
            return False

        if dry_run:
            self.stdout.write(f"  - Would restore media file from static: {rel_path}")
            return True

        media_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(static_path, media_path)
        return True

    def _mirror_to_static(self, rel_path: Path, dry_run: bool) -> bool:
        src = self.media_root / rel_path
        if not src.exists():
            return False

        dst = self.static_media_root / rel_path

        if dry_run:
            self.stdout.write(f"  - Would mirror media to static: {rel_path}")
            return True

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True

    def _download_url(self, url: str) -> tuple[bytes, str]:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        contexts = [ssl.create_default_context(), ssl._create_unverified_context()]
        last_error = None

        for context in contexts:
            try:
                with urlopen(request, timeout=30, context=context) as response:
                    content_type = response.headers.get("Content-Type", "")
                    return response.read(), content_type
            except Exception as exc:
                last_error = exc

        raise RuntimeError(last_error)

    def _guess_extension(self, url: str, content_type: str) -> str:
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
            return suffix

        if content_type:
            clean_type = content_type.split(";", 1)[0].strip()
            guessed = mimetypes.guess_extension(clean_type) or ""
            guessed = guessed.lower()
            if guessed in {".jpg", ".jpeg", ".png", ".webp"}:
                return guessed

        return ".jpg"
