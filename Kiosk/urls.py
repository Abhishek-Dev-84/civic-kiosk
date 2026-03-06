from django.contrib import admin
from django.urls import path, include
from django.conf.urls.i18n import i18n_patterns, set_language
from django.conf import settings
from django.conf.urls.static import static

# Language switch URL
urlpatterns = [
    path('set-language/', set_language, name='set_language'),
]

# URLs with language prefix (/en/, /hi/, etc.)
urlpatterns += i18n_patterns(
    path('admin/', admin.site.urls),
    path('', include('display.urls')),
)

# Serve media and static files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)