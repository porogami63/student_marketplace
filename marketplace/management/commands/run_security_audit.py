import os
import sys
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = 'Runs a comprehensive security audit on the application configuration.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('========================================='))
        self.stdout.write(self.style.SUCCESS('      SECURITY AUDIT INITIATED           '))
        self.stdout.write(self.style.SUCCESS('=========================================\n'))

        checks = [
            {
                "name": "DEBUG Mode Configuration",
                "status": not getattr(settings, 'DEBUG', True),
                "detail_pass": "DEBUG is set to False.",
                "detail_fail": "DEBUG is set to True. This is highly dangerous in production!"
            },
            {
                "name": "Secret Key Strength",
                "status": len(getattr(settings, 'SECRET_KEY', '')) >= 50,
                "detail_pass": "Secret key meets length requirements.",
                "detail_fail": "Secret key is too short or missing."
            },
            {
                "name": "Allowed Hosts Configured",
                "status": len(getattr(settings, 'ALLOWED_HOSTS', [])) > 0 and '*' not in getattr(settings, 'ALLOWED_HOSTS', []),
                "detail_pass": "ALLOWED_HOSTS is properly restricted.",
                "detail_fail": "ALLOWED_HOSTS is empty or contains wildcard '*'."
            },
            {
                "name": "Secure Session Cookies",
                "status": getattr(settings, 'SESSION_COOKIE_SECURE', False),
                "detail_pass": "SESSION_COOKIE_SECURE is enabled.",
                "detail_fail": "SESSION_COOKIE_SECURE is disabled."
            },
            {
                "name": "Secure CSRF Cookies",
                "status": getattr(settings, 'CSRF_COOKIE_SECURE', False),
                "detail_pass": "CSRF_COOKIE_SECURE is enabled.",
                "detail_fail": "CSRF_COOKIE_SECURE is disabled."
            },
            {
                "name": "X-Frame-Options",
                "status": getattr(settings, 'X_FRAME_OPTIONS', '') == 'DENY',
                "detail_pass": "X_FRAME_OPTIONS is set to DENY.",
                "detail_fail": "X_FRAME_OPTIONS is not fully restrictive."
            }
        ]

        passed = 0
        for check in checks:
            if check["status"]:
                self.stdout.write(self.style.SUCCESS(f"[PASS] {check['name']}"))
                self.stdout.write(f"       {check['detail_pass']}\n")
                passed += 1
            else:
                self.stdout.write(self.style.WARNING(f"[WARN] {check['name']}"))
                self.stdout.write(f"       {check['detail_fail']}\n")

        self.stdout.write('-----------------------------------------')
        self.stdout.write(
            self.style.SUCCESS(f"Audit Complete: {passed} out of {len(checks)} checks passed.") 
            if passed == len(checks) else 
            self.style.WARNING(f"Audit Complete: {passed} out of {len(checks)} checks passed. Please review warnings.")
        )
        self.stdout.write('=========================================\n')
