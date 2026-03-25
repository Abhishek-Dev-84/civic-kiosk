from django.contrib import admin
from django.urls import path, include
from django.conf.urls.i18n import set_language
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.http import HttpResponse

urlpatterns = [
    # Language switch URL outside patterns
    path('set-language/', set_language, name='set_language'),
    # Favicon stub to avoid 404 handler rendering
    path('favicon.ico', lambda request: HttpResponse(status=204)),
]

handler404 = 'display.views.custom_404'
# Use a custom handler to ensure the kiosk never shows raw Django errors.
handler500 = 'display.views.custom_500'

urlpatterns += i18n_patterns(
    path('admin/', admin.site.urls),
    path('', include('display.urls')),
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
