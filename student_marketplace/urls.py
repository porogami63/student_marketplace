from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static

from marketplace.admin_site import security_admin_site

urlpatterns = [
    path('admin/', security_admin_site.urls),
    path('backoffice/', RedirectView.as_view(url='/admin/', permanent=False)),
    path('accounts/', include('allauth.urls')),
    path('', include('marketplace.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
