import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Kiosk.settings")

from django.core.wsgi import get_wsgi_application

app = get_wsgi_application()