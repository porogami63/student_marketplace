from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static

from marketplace.admin_site import security_admin_site
from marketplace import auth_views

urlpatterns = [
    path('admin/', security_admin_site.urls),
    path('backoffice/', RedirectView.as_view(url='/admin/', permanent=False)),
    path('accounts/email-2fa/', auth_views.email_2fa_verify, name='account_email_2fa_verify'),
    path('accounts/email-2fa/resend/', auth_views.email_2fa_resend, name='account_email_2fa_resend'),
    path('accounts/email-2fa/sensitive/', auth_views.email_2fa_sensitive_verify, name='account_email_2fa_sensitive_verify'),
    path('accounts/email-2fa/sensitive/resend/', auth_views.email_2fa_sensitive_resend, name='account_email_2fa_sensitive_resend'),
    path('accounts/', include('allauth.urls')),
    path('', include('marketplace.urls')),
]

if settings.DEBUG or getattr(settings, 'SERVE_MEDIA_IN_PRODUCTION', False):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
