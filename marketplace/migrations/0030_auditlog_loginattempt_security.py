# Generated migration for Security & Compliance Models
# AuditLog and LoginAttempt models for FERPA, PCI DSS, NIST, ISO 27001 compliance

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('marketplace', '0029_update_logo_paths_to_static'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(
                    choices=[
                        ('login_attempt', 'Login Attempt'),
                        ('login_success', 'Login Success'),
                        ('login_failure', 'Login Failure'),
                        ('account_lockout', 'Account Lockout'),
                        ('unauthorized_access', 'Unauthorized Access'),
                        ('data_access', 'Data Access'),
                        ('payment_attempt', 'Payment Attempt'),
                        ('payment_success', 'Payment Success'),
                        ('payment_failure', 'Payment Failure'),
                        ('account_deleted', 'Account Deleted'),
                        ('permission_granted', 'Permission Granted'),
                        ('permission_revoked', 'Permission Revoked'),
                        ('mfa_enabled', 'MFA Enabled'),
                        ('mfa_disabled', 'MFA Disabled'),
                        ('password_changed', 'Password Changed'),
                        ('api_call', 'API Call'),
                        ('data_export', 'Data Export'),
                        ('security_alert', 'Security Alert'),
                    ],
                    max_length=50
                )),
                ('severity', models.CharField(
                    choices=[
                        ('info', 'Informational'),
                        ('warning', 'Warning'),
                        ('error', 'Error'),
                        ('critical', 'Critical'),
                    ],
                    default='info',
                    max_length=20
                )),
                ('ip_address', models.GenericIPAddressField()),
                ('user_agent', models.TextField(blank=True)),
                ('resource', models.CharField(blank=True, max_length=255)),
                ('details', models.JSONField(default=dict)),
                ('timestamp', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Audit Log',
                'verbose_name_plural': 'Audit Logs',
            },
        ),
        migrations.CreateModel(
            name='LoginAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('attempt_time', models.DateTimeField(auto_now_add=True)),
                ('success', models.BooleanField(default=False)),
                ('ip_address', models.GenericIPAddressField()),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['event_type', 'timestamp'], name='marketplace_event_timestamp_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['user', 'timestamp'], name='marketplace_user_timestamp_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['severity', 'timestamp'], name='marketplace_severity_timestamp_idx'),
        ),
        migrations.AddIndex(
            model_name='loginattempt',
            index=models.Index(fields=['user', 'attempt_time'], name='marketplace_user_attempt_idx'),
        ),
    ]
