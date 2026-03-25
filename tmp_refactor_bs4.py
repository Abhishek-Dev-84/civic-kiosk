import os
from bs4 import BeautifulSoup
import re

TEMPLATE_DIR = r"c:\Users\ABHISHEK NANDA\Downloads\Kiosk\templates"
TARGET_FILES = ['auth.html', 'otp.html', 'menu.html']

def extract_styles(soup):
    styles_text = ""
    for style_tag in soup.find_all('style'):
        content = style_tag.string
        if content:
            content = re.sub(r'(?s)(?:\*|body|html|\.header|\.header-left|\.header-right|\.voice-corner|\.voice-corner-btn|\.voice-corner-text|\.back-btn|\.timeout-warning|\.success-message|\.error-message|\.loading-overlay|\.loader|@keyframes pulse|@keyframes slideInLeft|@keyframes slideOutLeft|#csrf_token|\.security-note)[\s,]*\{[^}]*\}', '', content)
            
            content = '\n'.join([line for line in content.split('\n') if line.strip()])
            if content.strip():
                styles_text += content + "\n\n"
        style_tag.decompose()
    return styles_text

def extract_scripts(soup):
    scripts_text = ""
    for script_tag in soup.find_all('script'):
        if script_tag.get('src'):
            continue
            
        content = script_tag.string
        if content:
            content = re.sub(r'// ================= SECURITY ENHANCEMENTS =================.*?// ================= (LANGUAGE MAP|TEXT TO SPEECH|VOICE CONTROL)', '', content, flags=re.DOTALL)
            content = re.sub(r'// ===== SESSION TIMER =====.*?function resetSessionTimer\(\) \{.*?\}', '', content, flags=re.DOTALL)
            content = '\n'.join([line for line in content.split('\n') if line.strip()])
            if content.strip():
                scripts_text += content + "\n\n"
        script_tag.decompose()
    return scripts_text

def refactor_template(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        html = f.read()

    if "{% extends 'base.html' %}" in html:
        return False

    soup = BeautifulSoup(html, 'html.parser')
    
    title_tag = soup.find('title')
    title = title_tag.string if title_tag else ""
    
    extra_styles = extract_styles(soup)
    extra_scripts = extract_scripts(soup)
    
    main_container = soup.find('div', class_='kiosk-container')
    if not main_container:
        main_container = soup.find('div', class_='main')
        
    if not main_container:
        main_container = soup.find('body')
        if not main_container: return False
        
    for cls in ['header', 'voice-corner', 'back-btn', 'message-container', 'success-message', 'timeout-warning', 'security-note', 'loading-overlay']:
        for el in main_container.find_all('div', class_=cls): el.decompose()
    for el in main_container.find_all('a', class_='back-btn'): el.decompose()
    for el in main_container.find_all('div', id='timeoutWarning'): el.decompose()
    for el in main_container.find_all('div', id='loadingOverlay'): el.decompose()
    for el in main_container.find_all('div', id='voiceStatusIndicator'): el.decompose()
        
    for csrf in main_container.find_all('input', {'name': 'csrfmiddlewaretoken'}): csrf.decompose()
    for csrf in main_container.find_all('input', id='csrf_token'): csrf.decompose()
        
    inner_html = ""
    if main_container.name == 'body':
        for child in main_container.children: inner_html += str(child)
    else:
        cw = main_container.find('div', class_='content-wrapper')
        if cw:
            for child in cw.children: inner_html += str(child)
        else:
            for child in main_container.children: inner_html += str(child)

    inner_html = re.sub(r'{%\s*csrf_token\s*%}', '', inner_html)
    inner_html = re.sub(r'{%\s*if messages\s*%}.*?{%\s*endif\s*%}', '', inner_html, flags=re.DOTALL)
    inner_html = '\n'.join([line for line in inner_html.split('\n') if line.strip()])

    new_template = "{% extends 'base.html' %}\n{% load i18n static %}\n\n"
    if title: new_template += "{% block title %}" + title + "{% endblock %}\n\n"
    if extra_styles: new_template += "{% block extra_head %}\n<style>\n" + extra_styles + "\n</style>\n{% endblock %}\n\n"
    new_template += "{% block content %}\n" + inner_html + "\n{% endblock %}\n\n"
    if extra_scripts: new_template += "{% block extra_scripts %}\n<script>\n" + extra_scripts + "\n</script>\n{% endblock %}\n"

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_template)
    return True

if __name__ == '__main__':
    for filename in TARGET_FILES:
        filepath = os.path.join(TEMPLATE_DIR, filename)
        if os.path.exists(filepath):
            try:
                if refactor_template(filepath):
                    print(f"Refactored: {filename}")
            except Exception as e:
                print(f"Error {filename}: {e}")
