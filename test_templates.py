import os
import sys
import django
from django.template.loader import get_template

sys.path.append(r"c:\Users\ABHISHEK NANDA\Downloads\Kiosk")
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Kiosk.settings')
django.setup()

template_dir = r"c:\Users\ABHISHEK NANDA\Downloads\Kiosk\templates"

with open(r"c:\Users\ABHISHEK NANDA\Downloads\Kiosk\template_errors.txt", "w", encoding="utf-8") as out:
    for filename in os.listdir(template_dir):
        if filename.endswith(".html"):
            try:
                get_template(filename)
            except Exception as e:
                out.write(f"[{filename}] ERROR: {e}\n")
print("Done writing errors")
