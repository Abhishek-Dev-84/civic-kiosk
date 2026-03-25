import os
import re

TEMPLATE_DIR = r"c:\Users\ABHISHEK NANDA\Downloads\Kiosk\templates"
IGNORE_FILES = ['index.html', 'base.html', 'auth.html', 'otp.html'] 

def refactor_template(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    if "{% extends 'base.html' %}" in content:
        return False

    # Extract title
    title_match = re.search(r'<title>(.*?)</title>', content)
    title = title_match.group(1) if title_match else ""

    # Extract extra styles
    extra_styles = ""
    head_match = re.search(r'<head>(.*?)</head>', content, re.DOTALL)
    if head_match:
        styles = re.findall(r'<style>(.*?)</style>', head_match.group(1), re.DOTALL)
        if styles:
            for style in styles:
                # Remove common base styles
                cleaned_style = re.sub(r'(\*|body|\.header|\.voice-corner|\.back-btn|\.timeout-warning|\.loading-overlay|\.message|\.security-note).*?\}', '', style, flags=re.DOTALL)
                # Try to clean up empty lines
                cleaned_style = os.linesep.join([s for s in cleaned_style.splitlines() if s.strip()])
                if cleaned_style.strip():
                    extra_styles += cleaned_style + "\n"

    # Extract scripts
    extra_scripts = ""
    scripts = re.findall(r'<script.*?>(.*?)</script>', content, re.DOTALL)
    for script in scripts:
        if "kiosk_core.js" in script or "voice.js" in script:
            continue
        # Remove common boilerplate JS from old templates
        clean_script = script
        clean_script = re.sub(r'// ================= SECURITY ENHANCEMENTS =================.*?(?=// =====)', '', clean_script, flags=re.DOTALL)
        clean_script = re.sub(r'// Disable keyboard shortcuts.*?(?=\n\n)', '', clean_script, flags=re.DOTALL)
        clean_script = re.sub(r'// ===== SESSION TIMER =====.*?resetSessionTimer\(\);', '', clean_script, flags=re.DOTALL)
        clean_script = re.sub(r'let sessionTimer;.*?startSessionTimer\(\);\s*\}', '', clean_script, flags=re.DOTALL)
        if clean_script.strip():
            extra_scripts += clean_script + "\n"

    # Extract body content (everything between body tags, excluding scripts)
    body_match = re.search(r'<body.*?>(.*?)</body>', content, re.DOTALL)
    if not body_match:
        return False
        
    body_content = body_match.group(1)
    
    # Remove script tags from body content since we extracted them
    body_content = re.sub(r'<script.*?>.*?</script>', '', body_content, flags=re.DOTALL)

    # REMOVE COMMON ELEMENTS FROM BODY
    # 1. CSRF Token
    body_content = re.sub(r'<input type="hidden" id="csrf_token".*?>', '', body_content)
    body_content = re.sub(r'{%\s*csrf_token\s*%}', '', body_content)
    
    # 2. Header
    body_content = re.sub(r'<div class="header">.*?</div>\s*</div>\s*</div>', '', body_content, flags=re.DOTALL)
    body_content = re.sub(r'<div class="header">.*?<img src="https://www.cdac.in.*?>\s*</div>\s*</div>', '', body_content, flags=re.DOTALL)
    
    # 3. Voice Corner
    body_content = re.sub(r'<div class="voice-corner">.*?</div>\s*</div>', '', body_content, flags=re.DOTALL)
    
    # 4. Back Button
    body_content = re.sub(r'<div class="back-btn".*?>.*?</div>', '', body_content, flags=re.DOTALL)
    body_content = re.sub(r'<a href=".*?" class="back-btn".*?>.*?</a>', '', body_content, flags=re.DOTALL)
    
    # 5. Timeout Warning
    body_content = re.sub(r'<div id="timeoutWarning".*?>.*?</div>', '', body_content, flags=re.DOTALL)
    
    # 6. Messages
    body_content = re.sub(r'{%\s*if messages\s*%}.*?{%\s*endif\s*%}', '', body_content, flags=re.DOTALL)
    body_content = re.sub(r'<div id="messageContainer".*?>.*?</div>', '', body_content, flags=re.DOTALL)
    
    # 7. Security Note
    body_content = re.sub(r'<div class="security-note">.*?</div>', '', body_content, flags=re.DOTALL)
    
    # 8. Loading Overlays
    body_content = re.sub(r'<div id="loadingOverlay".*?>.*?</div>', '', body_content, flags=re.DOTALL)
    body_content = re.sub(r'<div id="globalLoadingOverlay".*?>.*?</div>', '', body_content, flags=re.DOTALL)

    # Clean up empty lines
    body_content = os.linesep.join([s for s in body_content.splitlines() if s.strip()])

    # Build new template
    new_template = "{% extends 'base.html' %}\n{% load i18n static %}\n\n"
    if title:
        new_template += "{% block title %}" + title + "{% endblock %}\n\n"
        
    if extra_styles.strip():
        new_template += "{% block extra_head %}\n<style>\n" + extra_styles.strip() + "\n</style>\n{% endblock %}\n\n"
        
    new_template += "{% block content %}\n"
    # Wrap in kiosk-container if it's not already
    if 'class="kiosk-container"' not in body_content and 'class="main"' not in body_content:
        new_template += '<div class="kiosk-container">\n<div class="content-wrapper">\n'
        new_template += body_content + "\n"
        new_template += '</div>\n</div>\n'
    else:
        new_template += body_content + "\n"
    new_template += "{% endblock %}\n\n"
    
    if extra_scripts.strip():
        new_template += "{% block extra_scripts %}\n<script>\n" + extra_scripts.strip() + "\n</script>\n{% endblock %}\n"

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_template)
    return True

if __name__ == '__main__':
    count = 0
    for filename in os.listdir(TEMPLATE_DIR):
        if filename.endswith('.html') and filename not in IGNORE_FILES:
            filepath = os.path.join(TEMPLATE_DIR, filename)
            try:
                if refactor_template(filepath):
                    count += 1
                    print(f"Refactored: {filename}")
            except Exception as e:
                print(f"Error {filename}: {e}")
    print(f"Total refactored: {count}")
