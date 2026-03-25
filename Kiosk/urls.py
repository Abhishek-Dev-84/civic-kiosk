from django.contrib import admin
from django.urls import path, include
from django.conf.urls.i18n import set_language
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns

urlpatterns = [
    # Language switch URL outside patterns
    path('set-language/', set_language, name='set_language'),
]

handler404 = 'display.views.custom_404'
# We don't have custom_500 yet, we will just use Django's default for 500 which automatically renders 500.html

urlpatterns += i18n_patterns(
    path('admin/', admin.site.urls),
    path('', include('display.urls')),
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)