"""
URL configuration for Kiosk project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import set_language

urlpatterns = [

    # Admin
    path('admin/', admin.site.urls),

    # Language switch
    path('set-language/', set_language, name='set_language'),

    # Main app
    path('', include('display.urls')),

]

# Serve media and static in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)