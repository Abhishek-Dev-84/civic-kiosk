"""
URL configuration for Kiosk project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.i18n import set_language

urlpatterns = [
    path('admin/', admin.site.urls),

    # Language switch URL
    path('set-language/', set_language, name='set_language'),
]

# Wrap your app URLs inside i18n_patterns
urlpatterns += i18n_patterns(
    path('', include('display.urls')),
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)