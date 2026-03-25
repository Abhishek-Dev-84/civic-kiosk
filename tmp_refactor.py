import os
import re

# We will refactor auth.html, index.html, and a few others manually because their structure is unique.
# But for all the internal pages (e.g. electricity-*.html, gas-*.html, etc.), they follow a rigid pattern.

TEMPLATE_DIR = r"c:\Users\ABHISHEK NANDA\Downloads\Kiosk\templates"

# Files to ignore during automated refactor because they need special care:
# index.html, base.html, 404.html, under-development.html (maybe)
IGNORE_FILES = ['index.html', 'base.html'] 

def refactor_template(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Determine what this file is. Is it already refactored?
    if "{% extends 'base.html' %}" in content:
        return False

    # Standard header tags extraction
    head_content_match = re.search(r'<head>(.*?)</head>', content, re.DOTALL)
    body_content_match = re.search(r'<div class="kiosk-container">\s*<div class="content-wrapper">(.*?)</div>\s*</div>', content, re.DOTALL)
    
    # If the file doesn't have the standard kiosk-container, we can't do a brainless replace.
    if not body_content_match:
        # Fallback: Just grab the body contents excluding the header/controls.
        # This is riskier.
        body_content_match = re.search(r'<body>(.*?)<script>', content, re.DOTALL)
        if not body_content_match:
            return False

    extracted_body = body_content_match.group(1).strip()
    
    # Remove the standard static loading overlays or error messages if they were duplicated within the extracted body
    extracted_body = re.sub(r'<!-- Messages -->.*?{% endif %}\s*</div>', '', extracted_body, flags=re.DOTALL)
    extracted_body = re.sub(r'<div class="messages">.*?</div>\s*</div>', '', extracted_body, flags=re.DOTALL)
    extracted_body = re.sub(r'<div id="loader".*?</div>', '', extracted_body, flags=re.DOTALL)
    
    # Build new content
    new_content = "{% extends 'base.html' %}\n{% load i18n static %}\n\n"
    
    # Add title
    title_match = re.search(r'<title>(.*?)</title>', content)
    if title_match:
        new_content += "{% block title %}" + title_match.group(1) + "{% endblock %}\n\n"
        
    # Extra styles
    if head_content_match:
        # Extract <style>
        styles = re.findall(r'<style>(.*?)</style>', head_content_match.group(1), re.DOTALL)
        if styles:
            new_content += "{% block extra_head %}\n<style>\n"
            for style in styles:
                # remove generic styles that base.html has
                cleaned_style = re.sub(r'(\*|body|\.header|\.kiosk-container|\.content-wrapper|h1|\.timeout-warning|\.loading-overlay).*?\}', '', style, flags=re.DOTALL)
                new_content += cleaned_style + "\n"
            new_content += "</style>\n{% endblock %}\n\n"
            
    new_content += "{% block content %}\n"
    new_content += extracted_body + "\n"
    new_content += "{% endblock %}\n\n"
    
    # Extract specific scripts
    scripts = re.findall(r'<script>(.*?)</script>', content, re.DOTALL)
    if scripts:
        new_content += "{% block extra_scripts %}\n<script>\n"
        for script in scripts:
            # remove generic session timer and security stuff
            clean_script = script
            clean_script = re.sub(r'// Session timer.*?resetSessionTimer\(\);\s*\}', '', clean_script, flags=re.DOTALL)
            clean_script = re.sub(r'let sessionTimer;.*?startSessionTimer\(\);\s*\}', '', clean_script, flags=re.DOTALL)
            clean_script = re.sub(r'document\.addEventListener\(\'keydown\'.*?\}\);', '', clean_script, flags=re.DOTALL)
            clean_script = re.sub(r'// Disable right-click.*?preventDefault\(\)\);', '', clean_script, flags=re.DOTALL)
            new_content += clean_script + "\n"
        new_content += "</script>\n{% endblock %}\n"

    # Save refactored template
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
        
    return True

if __name__ == '__main__':
    count = 0
    for filename in os.listdir(TEMPLATE_DIR):
        if filename.endswith('.html') and filename not in IGNORE_FILES:
            filepath = os.path.join(TEMPLATE_DIR, filename)
            try:
                success = refactor_template(filepath)
                if success:
                    count += 1
            except Exception as e:
                print(f"Failed to refactor {filename}: {e}")
                
    print(f"Successfully refactored {count} templates.")
