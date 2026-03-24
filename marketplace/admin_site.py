"""Custom Admin Site with Backoffice dashboard.

This provides a single admin portal (separate URL space) that consolidates:
- Django model admin (all registered models)
- Moderation overview metrics
- Security/compliance monitoring (AuditLog, LoginAttempt, compliance checks)
"""

import json

from datetime import timedelta

from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered
from django.contrib.auth.models import User
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path, reverse
from django.utils import timezone

from .models import (
    ForumPost,
    ForumReply,
    Listing,
    ModerationLog,
    Transaction,
)
from .security import AuditLog, LoginAttempt


class SecurityAdminSite(admin.AdminSite):
    """Custom admin site with enhanced security dashboard"""
    
    site_header = 'UBXchange Backoffice'
    site_title = 'Backoffice'
    index_title = 'Backoffice Dashboard'
    index_template = 'admin/security_admin/index.html'
    
    def get_urls(self):
        """Add custom security dashboard URL"""
        urls = super().get_urls()
        custom_urls = [
            path('security/', self.admin_view(self.security_dashboard), name='security_dashboard'),
            path('security/audit-logs/', self.admin_view(self.audit_logs_view), name='audit_logs'),
            path('security/login-attempts/', self.admin_view(self.login_attempts_view), name='login_attempts'),
            path('security/compliance/', self.admin_view(self.compliance_view), name='compliance'),
            path('security/audit-report.json', self.admin_view(self.audit_report_download), name='audit_report_download'),
        ]
        return custom_urls + urls
    
    def index(self, request, extra_context=None):
        """Override admin index to show security dashboard"""
        if extra_context is None:
            extra_context = {}

        extra_context.update(self.get_security_metrics())
        extra_context.update(self.get_moderation_metrics())
        extra_context['quick_links'] = self.get_quick_links(request)
        extra_context['quick_link_groups'] = self.get_quick_link_groups(request)

        # Lightweight compliance snapshot for the landing page.
        try:
            from .security import check_ferpa_compliance, check_pci_dss_compliance
            extra_context['compliance_snapshot'] = {
                'ferpa': check_ferpa_compliance().get('overall_status', 'UNKNOWN'),
                'pci_dss': check_pci_dss_compliance().get('overall_status', 'UNKNOWN'),
            }
        except Exception:
            extra_context['compliance_snapshot'] = {'ferpa': 'UNKNOWN', 'pci_dss': 'UNKNOWN'}

        # Recent security events (helps validate the dashboard is updating).
        extra_context['recent_security_events'] = AuditLog.objects.order_by('-timestamp')[:10]
        
        return super().index(request, extra_context)
    
    def get_security_metrics(self):
        """Calculate security metrics for dashboard"""
        now = timezone.now()
        
        # Time windows
        last_24h = now - timedelta(hours=24)
        last_7d = now - timedelta(days=7)
        
        # Audit logs metrics
        total_events = AuditLog.objects.count()
        critical_events = AuditLog.objects.filter(severity='critical').count()
        errors_24h = AuditLog.objects.filter(
            severity='error',
            timestamp__gte=last_24h
        ).count()
        
        # Login attempt metrics
        failed_logins_24h = LoginAttempt.objects.filter(
            success=False,
            attempt_time__gte=last_24h
        ).count()
        successful_logins_24h = LoginAttempt.objects.filter(
            success=True,
            attempt_time__gte=last_24h
        ).count()
        
        # Lock suspicious users (3+ failed attempts in 30 minutes)
        thirty_min_ago = now - timedelta(minutes=30)
        suspicious_users = LoginAttempt.objects.filter(
            success=False,
            attempt_time__gte=thirty_min_ago
        ).values('user').annotate(
            count=Count('id')
        ).filter(count__gte=3)
        
        return {
            'security_metrics': {
                'total_events': total_events,
                'critical_events': critical_events,
                'errors_24h': errors_24h,
                'failed_logins_24h': failed_logins_24h,
                'successful_logins_24h': successful_logins_24h,
                'suspicious_users_count': suspicious_users.count(),
                'critical_level': 'HIGH' if critical_events > 5 else 'MEDIUM' if critical_events > 0 else 'LOW',
            }
        }

    def audit_report_download(self, request):
        """Download a JSON security audit report (default: last 90 days)."""
        from .security import generate_security_audit_report

        days_param = request.GET.get('days', '').strip()
        try:
            days = int(days_param) if days_param else 90
            if days < 1:
                days = 1
            if days > 365:
                days = 365
        except ValueError:
            days = 90

        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        report = generate_security_audit_report(start_date=start_date, end_date=end_date)

        payload = json.dumps(report, indent=2, sort_keys=True)
        filename = f"security_audit_report_{start_date.date().isoformat()}_{end_date.date().isoformat()}.json"
        response = HttpResponse(payload, content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    def get_moderation_metrics(self):
        """Calculate moderation/business overview metrics for the backoffice."""
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        month_start = today_start - timedelta(days=30)

        completed = Transaction.objects.filter(status='completed')
        total_revenue = completed.aggregate(s=Sum('price'))['s'] or 0
        today_revenue = completed.filter(completed_at__gte=today_start).aggregate(s=Sum('price'))['s'] or 0
        week_revenue = completed.filter(completed_at__gte=week_start).aggregate(s=Sum('price'))['s'] or 0
        month_revenue = completed.filter(completed_at__gte=month_start).aggregate(s=Sum('price'))['s'] or 0

        tx_counts = Transaction.objects.values('status').annotate(cnt=Count('id'))
        status_counts = {s['status']: s['cnt'] for s in tx_counts}

        user_count = User.objects.count()
        new_users_week = User.objects.filter(date_joined__gte=week_start).count()

        listing_count = Listing.objects.filter(is_sold=False).count()
        forum_post_count = ForumPost.objects.filter(is_hidden=False).count()
        hidden_forum_count = ForumPost.objects.filter(is_hidden=True).count() + ForumReply.objects.filter(is_hidden=True).count()

        recent_logs = ModerationLog.objects.select_related('actor').order_by('-created_at')[:10]

        return {
            'moderation_metrics': {
                'total_revenue': total_revenue,
                'today_revenue': today_revenue,
                'week_revenue': week_revenue,
                'month_revenue': month_revenue,
                'status_counts': status_counts,
                'user_count': user_count,
                'new_users_week': new_users_week,
                'listing_count': listing_count,
                'forum_post_count': forum_post_count,
                'hidden_forum_count': hidden_forum_count,
            },
            'recent_moderation_logs': recent_logs,
        }

    def get_quick_links(self, request):
        """Common admin destinations (changelists) shown on the dashboard."""

        def _safe_reverse(name):
            try:
                return reverse(name, current_app=self.name)
            except Exception:
                return ''

        return {
            'Users': _safe_reverse('admin:auth_user_changelist'),
            'Profiles': _safe_reverse('admin:marketplace_profile_changelist'),
            'Listings': _safe_reverse('admin:marketplace_listing_changelist'),
            'Transactions': _safe_reverse('admin:marketplace_transaction_changelist'),
            'Payments': _safe_reverse('admin:marketplace_payment_changelist'),
            'Receipts': _safe_reverse('admin:marketplace_receipt_changelist'),
            'Forum Posts': _safe_reverse('admin:marketplace_forumpost_changelist'),
            'Forum Replies': _safe_reverse('admin:marketplace_forumreply_changelist'),
            'Messages': _safe_reverse('admin:marketplace_message_changelist'),
            'Moderation Logs': _safe_reverse('admin:marketplace_moderationlog_changelist'),
            'Audit Logs': _safe_reverse('admin:marketplace_auditlog_changelist'),
            'Login Attempts': _safe_reverse('admin:marketplace_loginattempt_changelist'),
            'Security Interface': _safe_reverse('admin:security_dashboard'),
            'Compliance Status': _safe_reverse('admin:compliance'),
            'Audit Report (JSON)': _safe_reverse('admin:audit_report_download'),
        }

    def get_quick_link_groups(self, request):
        """Grouped quick links for the Backoffice dashboard."""

        quick_links = self.get_quick_links(request)

        groups = [
            {
                'title': 'Operations',
                'subtitle': 'Core admin destinations',
                'labels': [
                    'Users',
                    'Profiles',
                    'Listings',
                    'Transactions',
                    'Payments',
                    'Receipts',
                    'Messages',
                ],
            },
            {
                'title': 'Community',
                'subtitle': 'Forum & engagement',
                'labels': ['Forum Posts', 'Forum Replies'],
            },
            {
                'title': 'Security',
                'subtitle': 'Monitoring & logs',
                'labels': ['Security Interface', 'Compliance Status', 'Audit Report (JSON)', 'Audit Logs', 'Login Attempts', 'Moderation Logs'],
            },
        ]

        used = set()
        grouped = []
        for group in groups:
            items = []
            for label in group['labels']:
                url = quick_links.get(label) or ''
                if url:
                    items.append({'label': label, 'url': url})
                    used.add(label)
            grouped.append({
                'title': group['title'],
                'subtitle': group['subtitle'],
                'items': items,
            })

        other_items = []
        for label, url in quick_links.items():
            if label in used:
                continue
            if url:
                other_items.append({'label': label, 'url': url})

        grouped.append({
            'title': 'Other',
            'subtitle': 'Everything else',
            'items': other_items,
        })

        return grouped
    
    def security_dashboard(self, request):
        """Display comprehensive security dashboard"""
        from .security import check_ferpa_compliance, check_pci_dss_compliance
        
        context = {
            'title': 'Security Dashboard',
            'subtitle': 'Real-time Security Monitoring & Compliance Status',
            'site_header': self.site_header,
        }
        
        # Add security metrics
        context.update(self.get_security_metrics())
        
        # Add compliance status
        try:
            ferpa_status = check_ferpa_compliance()
            context['ferpa_status'] = ferpa_status
        except:
            context['ferpa_status'] = {'status': 'ERROR'}
        
        try:
            pci_status = check_pci_dss_compliance()
            context['pci_status'] = pci_status
        except:
            context['pci_status'] = {'status': 'ERROR'}
        
        # Recent critical events
        recent_critical = AuditLog.objects.filter(
            severity__in=['critical', 'error']
        ).order_by('-timestamp')[:10]
        context['recent_critical_events'] = recent_critical

        return render(request, 'admin/security_admin/security_dashboard.html', context)
    
    def audit_logs_view(self, request):
        """Display audit logs summary"""
        context = {
            'title': 'Audit Logs',
            'subtitle': 'Security Event Log (FERPA, PCI DSS Compliance)',
            'site_header': self.site_header,
        }
        
        # Get stats
        now = timezone.now()
        last_7d = now - timedelta(days=7)
        
        event_stats = AuditLog.objects.filter(
            timestamp__gte=last_7d
        ).values('event_type').annotate(
            count=Count('id')
        ).order_by('-count')
        
        severity_stats = AuditLog.objects.filter(
            timestamp__gte=last_7d
        ).values('severity').annotate(
            count=Count('id')
        ).order_by('-count')
        
        context['event_stats'] = event_stats
        context['severity_stats'] = severity_stats
        context['total_logs'] = AuditLog.objects.count()
        context['logs_7d'] = AuditLog.objects.filter(timestamp__gte=last_7d).count()

        return render(request, 'admin/security_admin/audit_logs.html', context)
    
    def login_attempts_view(self, request):
        """Display login attempt tracking"""
        context = {
            'title': 'Login Attempts',
            'subtitle': 'Account Lockout Monitoring (NIST AC-7)',
            'site_header': self.site_header,
        }
        
        now = timezone.now()
        last_24h = now - timedelta(hours=24)
        
        # Suspicious IPs
        suspicious_ips = LoginAttempt.objects.filter(
            success=False,
            attempt_time__gte=last_24h
        ).values('ip_address').annotate(
            count=Count('id')
        ).filter(count__gte=5).order_by('-count')
        
        context['suspicious_ips'] = suspicious_ips
        context['failed_24h'] = LoginAttempt.objects.filter(
            success=False,
            attempt_time__gte=last_24h
        ).count()
        context['successful_24h'] = LoginAttempt.objects.filter(
            success=True,
            attempt_time__gte=last_24h
        ).count()

        return render(request, 'admin/security_admin/login_attempts.html', context)
    
    def compliance_view(self, request):
        """Display compliance status summary"""
        from .security import (
            check_ferpa_compliance,
            check_pci_dss_compliance,
            check_nist_compliance,
            check_iso27001_compliance,
            generate_security_audit_report
        )
        
        context = {
            'title': 'Compliance Status',
            'subtitle': 'FERPA, PCI DSS, NIST, ISO 27001 Compliance Status',
            'site_header': self.site_header,
        }
        
        try:
            context['ferpa_compliance'] = check_ferpa_compliance()
        except Exception as e:
            context['ferpa_compliance'] = {'status': 'ERROR', 'error': str(e)}
        
        try:
            context['pci_compliance'] = check_pci_dss_compliance()
        except Exception as e:
            context['pci_compliance'] = {'status': 'ERROR', 'error': str(e)}
        
        try:
            context['audit_report'] = generate_security_audit_report()
        except Exception as e:
            context['audit_report'] = {'status': 'ERROR', 'error': str(e)}

        try:
            context['nist_compliance'] = check_nist_compliance()
        except Exception as e:
            context['nist_compliance'] = {'overall_status': 'ERROR', 'error': str(e)}

        try:
            context['iso27001_compliance'] = check_iso27001_compliance()
        except Exception as e:
            context['iso27001_compliance'] = {'overall_status': 'ERROR', 'error': str(e)}

        return render(request, 'admin/security_admin/compliance_status.html', context)


# Create instance of custom admin site
security_admin_site = SecurityAdminSite(name='security_admin')

# Ensure default admin registrations are loaded, then mirror them into the backoffice site.
admin.autodiscover()

for model, model_admin in admin.site._registry.items():
    try:
        security_admin_site.register(model, model_admin.__class__)
    except AlreadyRegistered:
        pass

# Register standard admin site - users can access either
admin.site.site_header = 'UBXchange Admin'
admin.site.index_title = 'Welcome to UBXchange Admin Portal'
