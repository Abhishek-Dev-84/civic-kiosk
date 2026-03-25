import os
import re

TEMPLATE_DIR = r"c:\Users\ABHISHEK NANDA\Downloads\Kiosk\templates"

def add_csrf_to_forms(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find all POST forms
    def replacer(match):
        form_tag = match.group(0)
        # Check if already has it
        # Actually it's easier to just insert it if it's not there.
        # But we stripped it globally, so it's probably not there immediately after.
        return form_tag + "\n    {% csrf_token %}"

    # Only replace if there isn't a csrf token already near it (within 50 chars)
    # We stripped them all so it should be safe to just inject.
    
    # regex for <form ... method="POST" ...>
    new_content = re.sub(r'(?i)<form[^>]*?method=["\']POST["\'][^>]*>', replacer, content)
    
    # We might end up with double but since I stripped it, it should be fine.
    # Let's clean up multiples just in case:
    new_content = re.sub(r'(?i)({%\s*csrf_token\s*%}\s*){2,}', '{% csrf_token %}\n', new_content)

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    return False

if __name__ == '__main__':
    count = 0
    for filename in os.listdir(TEMPLATE_DIR):
        if filename.endswith('.html'):
            filepath = os.path.join(TEMPLATE_DIR, filename)
            try:
                if add_csrf_to_forms(filepath):
                    count += 1
            except Exception as e:
                print(f"Error {filename}: {e}")
    print(f"Added CSRF to {count} files")
