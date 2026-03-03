# Civic_Kiosk
Smart Civic Services Kiosk is a digital self-service system that provides citizens quick access to essential government services such as bill payments, service applications, and information lookup. It ensures secure transactions, reduces queues, enhances transparency, and promotes efficient, paperless, and user-friendly public service delivery.

# 🏛️ **Civic Services Kiosk - Complete Project Documentation**

## 📋 **Table of Contents**
1. [Project Overview](#project-overview)
2. [Installation Guide](#installation-guide)
3. [Project Structure](#project-structure)
4. [Features & Services](#features--services)
5. [Internationalization (i18n)](#internationalization-i18n)
6. [Authentication Flow](#authentication-flow)
7. [Database & Sessions](#database--sessions)
8. [URL Structure](#url-structure)
9. [Templates & Styling](#templates--styling)
10. [Deployment Guide](#deployment-guide)

---

## 🎯 **Project Overview**

The **Civic Services Kiosk** is a Django-based self-service kiosk application that provides citizens with access to various government services including:

- **Gas Services** (LPG cylinder booking, subsidy, complaints)
- **Electricity Services** (bill payment, new connection, complaints)
- **Municipal Services** (birth/death certificates, property tax, marriage registration)
- **Document Upload** (QR code, pen drive, camera)
- **Multi-language Support** (English, Hindi, Odia, Bengali, Tamil, Telugu)

**Tech Stack:**
- Django 6.0.1
- Python 3.13+
- SQLite (development) / PostgreSQL (production)
- HTML5/CSS3 with kiosk-optimized UI
- JavaScript for interactive elements
- django-rosetta for translation management

---

## 🔧 **Installation Guide**

### Prerequisites
```bash
# Python 3.13 or higher required
python --version

# pip package manager
pip --version

# Git (optional)
git --version
```

### Step 1: Clone/Download Project
```bash
git clone <repository-url>
# or download and extract the ZIP file
cd Kiosk
```

### Step 2: Create Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Dependencies
```bash
pip install django==6.0.1
pip install python-dateutil  # For date calculations
pip install pillow  # For image handling
pip install django-rosetta  # For translation management
```

Or use requirements.txt:
```bash
pip install -r requirements.txt
```

### Step 4: Database Setup
```bash
# Run migrations
python manage.py migrate

# Create superuser (for admin access)
python manage.py createsuperuser
```

### Step 5: Create Translation Files
```bash
# Create message files for each language
python manage.py makemessages -l hi
python manage.py makemessages -l or
python manage.py makemessages -l bn
python manage.py makemessages -l ta
python manage.py makemessages -l te

# Compile translations
python manage.py compilemessages
```

### Step 6: Run Development Server
```bash
python manage.py runserver
```

Access the application at: `http://127.0.0.1:8000`

---

## 📁 **Project Structure**

```
Kiosk/
├── manage.py
├── db.sqlite3
├── locale/                  # Translation files
│   ├── hi/
│   ├── or/
│   ├── bn/
│   ├── ta/
│   └── te/
├── Kiosk/                   # Project settings
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── display/                 # Main application
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── models.py
│   ├── views.py            # All view logic (100+ functions)
│   ├── urls.py             # App-specific URLs
│   ├── middleware.py       # Custom middleware
│   └── templatetags/       # Custom template tags
├── static/                  # Static files
│   ├── css/
│   ├── js/
│   └── images/
├── templates/               # HTML templates
│   ├── index.html          # Language selection
│   ├── auth.html           # Aadhaar entry
│   ├── otp.html            # OTP verification
│   ├── menu.html           # Main services menu
│   ├── gas-*.html          # Gas service pages
│   ├── electricity-*.html  # Electricity service pages
│   └── ... (40+ templates)
└── media/                   # User uploaded files
```

---

## 🚀 **Features & Services**

### **1. Authentication System**
- Aadhaar number entry (12 digits)
- OTP generation and verification
- Session-based authentication
- 3-attempt limit for OTP

### **2. Gas Services** (7 modules)
- **New Connection** - Apply for new gas connection
- **Subsidy Management** - Check subsidy status
- **Bill Payment** - Pay gas bills
- **Complaint Registration** - Lodge gas-related complaints
- **Cylinder Booking** - Book LPG cylinders
- **Booking Status** - Track cylinder delivery
- **Consumer Lookup** - Find consumer details

### **3. Electricity Services** (9 modules)
- **Bill Payment** - Pay electricity bills
- **New Connection** - Apply for new connection
- **Complaint** - Report power issues
- **Load Enhancement** - Increase power load
- **Name Transfer** - Transfer ownership
- **Meter Replacement** - Request new meter
- **Duplicate Bill** - Get bill copy
- **Solar Net Metering** - Apply for solar
- **Service Status** - Check application status

### **4. Municipal Services** (9 modules)
- **Property Tax** - Pay property tax
- **Water Bill** - Pay water bills
- **Trade License** - Apply/renew license
- **Birth Certificate** - Register birth
- **Death Certificate** - Register death
- **Marriage Registration** - Register marriage
- **Building Plan** - Submit building plans
- **Grievance** - Lodge complaints
- **Professional Tax** - Pay professional tax

### **5. Document Upload** (3 methods)
- **QR Code Upload** - Scan and upload via phone
- **Pen Drive Upload** - Upload from USB drive
- **Camera Upload** - Capture documents live

---

## 🌐 **Internationalization (i18n)**

### Supported Languages
```python
LANGUAGES = [
    ('en', 'English'),
    ('hi', 'Hindi'),
    ('or', 'Odia'),
    ('bn', 'Bengali'),
    ('ta', 'Tamil'),
    ('te', 'Telugu'),
]
```

### How Translation Works

**1. In Templates:**
```html
{% load i18n %}
<title>{% trans "Civic Services Kiosk" %}</title>
<h1>{% trans "Enter Aadhaar" %}</h1>
<button>{% trans "Proceed" %}</button>
```

**2. In Python Views:**
```python
from django.utils.translation import gettext as _

messages.success(request, _('OTP sent successfully'))
```

**3. Generate Translation Files:**
```bash
# Create/update message files
python manage.py makemessages -l hi

# Edit the .po files in locale/hi/LC_MESSAGES/django.po
# Add translations for each msgid

# Compile to .mo files
python manage.py compilemessages
```

**4. Using django-rosetta (Admin Interface):**
- Access: `http://127.0.0.1:8000/rosetta/`
- Login with superuser credentials
- Select language to translate
- Edit translations in web interface

**5. Language Switching in Templates:**
```javascript
function setLanguage(langCode) {
    document.cookie = "django_language=" + langCode + "; path=/";
    window.location.href = '/' + langCode + '/auth/';
}
```

### Translation Statistics
- **Total translatable strings:** ~350
- **Template files:** 40+ HTML files
- **View files:** 100+ view functions
- **Common phrases:** Buttons, labels, error messages, service names

---

## 🔐 **Authentication Flow**

```
┌─────────────┐
│  /en/       │  Language Selection
│  index.html │  (Public - No login)
└──────┬──────┘
       │ Choose Language
       ▼
┌─────────────┐
│  /en/auth/  │  Enter 12-digit Aadhaar
│  auth.html  │  (Public - No login)
└──────┬──────┘
       │ Submit Aadhaar
       ▼
┌─────────────┐
│  /en/otp/   │  Enter 6-digit OTP
│  otp.html   │  (Public - No login)
└──────┬──────┘
       │ Verify OTP
       ▼
┌─────────────┐
│  /en/menu/  │  Main Services Menu
│  menu.html  │  (Protected - Requires aadhaar_verified)
└──────┬──────┘
       │ Select Service
       ▼
┌─────────────┐
│ Gas/Electricity/  │  Service Pages
│ Municipal etc.    │  (Protected - Requires aadhaar_verified)
└──────────────────┘
```

### Session Variables
```python
request.session['aadhaar_number'] = '123456789012'  # User's Aadhaar
request.session['otp'] = '123456'                   # Generated OTP
request.session['otp_attempts'] = 0                 # Failed attempts
request.session['aadhaar_verified'] = True          # Verification flag
```

### Security Features
- OTP expires after 2 minutes
- Max 3 failed attempts
- Session timeout after 2 minutes of inactivity
- CSRF protection on all forms
- X-Frame-Options: DENY

---

## 🗄️ **Database & Sessions**

### Models (if any)
The project currently uses session-based storage without database models. All data is stored in Django sessions.

### Session Configuration
```python
# settings.py
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 1209600  # 2 weeks
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
```

### Session Data Structure
```python
# Example session contents
{
    'aadhaar_number': '123456789012',
    'otp': '654321',
    'otp_attempts': 0,
    'aadhaar_verified': True,
    '_auth_user_id': 1,  # If using Django auth
    '_auth_user_backend': 'django.contrib.auth.backends.ModelBackend',
}
```

---

## 🔗 **URL Structure**

### Main URL Patterns (Kiosk/urls.py)
```python
```

## 🎨 **Templates & Styling**

### Template Structure
- **40+ HTML files** in templates directory
- **Master stylesheet** in each template (consistent design)
- **Kiosk-optimized** UI with large buttons and touch-friendly
- **Responsive design** for different screen sizes

### Key Templates

| Template | Purpose | Protected |
|----------|---------|-----------|
| `index.html` | Language selection | No |
| `auth.html` | Aadhaar entry | No |
| `otp.html` | OTP verification | No |
| `menu.html` | Main services menu | Yes |
| `gas-services.html` | Gas services menu | Yes |
| `electricity-services.html` | Electricity menu | Yes |
| `municipal-services.html` | Municipal menu | Yes |
| `gas-cylinder-booking.html` | Cylinder booking | Yes |
| `electricity-bill-payment.html` | Bill payment | Yes |
| `birth-certificate.html` | Birth registration | Yes |
| `under-development.html` | Coming soon page | Yes |

### Common UI Elements
- **Header** - Government of India emblem and logo
- **Voice button** - Top-right corner for voice assistance
- **Back button** - Top-left corner for navigation
- **Timeout warning** - Auto-logout after 2 minutes
- **Number boxes** - For Aadhaar/OTP entry
- **Keypad** - On-screen numeric keypad
- **Grid layout** - 2-3 column service cards
- **Success/Error messages** - Colored notifications

### CSS Features
- Full-screen kiosk mode (`100vw`, `100vh`)
- No scrolling (`overflow: hidden`)
- Touch-optimized (`user-select: none`)
- Box shadows for depth
- Active state animations
- Responsive grid layouts

---

## 🚢 **Deployment Guide**

### Development vs Production

**settings.py differences:**
```python
# Development
DEBUG = True
ALLOWED_HOSTS = ['*']

# Production
DEBUG = False
ALLOWED_HOSTS = ['your-domain.com', 'www.your-domain.com']
```

### Static Files
```bash
# Collect all static files
python manage.py collectstatic

# Static files will be in /staticfiles directory
```

### Database Setup for Production
```python
# settings.py - PostgreSQL example
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'kiosk_db',
        'USER': 'kiosk_user',
        'PASSWORD': 'secure_password',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```

### Server Setup (Ubuntu/Nginx/Gunicorn)

**1. Install requirements:**
```bash
sudo apt update
sudo apt install python3-pip python3-dev libpq-dev nginx
pip install gunicorn
```

**2. Configure Gunicorn:**
```bash
# Create gunicorn service
sudo nano /etc/systemd/system/gunicorn.service
```

```ini
[Unit]
Description=gunicorn daemon
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/home/ubuntu/Kiosk
ExecStart=/home/ubuntu/Kiosk/venv/bin/gunicorn --workers 3 --bind unix:/home/ubuntu/Kiosk/Kiosk.sock Kiosk.wsgi:application

[Install]
WantedBy=multi-user.target
```

**3. Configure Nginx:**
```bash
sudo nano /etc/nginx/sites-available/kiosk
```

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location = /favicon.ico { access_log off; log_not_found off; }
    
    location /static/ {
        root /home/ubuntu/Kiosk;
    }

    location /media/ {
        root /home/ubuntu/Kiosk;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/home/ubuntu/Kiosk/Kiosk.sock;
    }
}
```

**4. Enable site and restart:**
```bash
sudo ln -s /etc/nginx/sites-available/kiosk /etc/nginx/sites-enabled
sudo systemctl restart nginx
sudo systemctl start gunicorn
sudo systemctl enable gunicorn
```

### Docker Deployment (Optional)

**Dockerfile:**
```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput
RUN python manage.py compilemessages

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "Kiosk.wsgi:application"]
```

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DEBUG=False
      - DJANGO_SECRET_KEY=your-secret-key
    volumes:
      - ./staticfiles:/app/staticfiles
      - ./media:/app/media
```

---

## 🐛 **Common Issues & Solutions**

### 1. Redirect Loop on Language Selection
**Cause:** `@login_required` on auth view
**Solution:** Remove `@login_required` from auth, otp, resend_otp views

### 2. TemplateSyntaxError: 'trans' tag not found
**Cause:** `{% load i18n %}` missing or placed after trans tag
**Solution:** Add `{% load i18n %}` at the very top of template

### 3. OTP not appearing in console
**Cause:** Missing print statement
**Solution:** Check views.py for OTP print statements

### 4. Session not persisting
**Cause:** Session middleware order
**Solution:** Ensure SessionMiddleware is before LocaleMiddleware

### 5. Static files not loading
**Cause:** Wrong STATIC_URL or missing collectstatic
**Solution:** Run `python manage.py collectstatic`

### 6. Translation not working
**Cause:** .po files not compiled
**Solution:** Run `python manage.py compilemessages`

---

## 📊 **Project Statistics**

- **Total Views:** 100+
- **Total Templates:** 40+
- **Total URLs:** 50+
- **Total Translation Strings:** ~350
- **Supported Languages:** 6
- **Service Modules:** 30+
- **Lines of Code:** ~15,000

---

## 🔍 **Testing**

```bash
# Run all tests
python manage.py test

# Check for translation issues
python manage.py check --deploy

# Validate templates
python manage.py validate_templates
```

---

## 📚 **Additional Resources**

- [Django Documentation](https://docs.djangoproject.com/)
- [Django Internationalization](https://docs.djangoproject.com/en/6.0/topics/i18n/)
- [django-rosetta](https://django-rosetta.readthedocs.io/)
- [Font Awesome Icons](https://fontawesome.com/)
- [Emoji Cheat Sheet](https://www.webfx.com/tools/emoji-cheat-sheet/)

---

This documentation covers everything about the Civic Services Kiosk project - from installation to deployment, including the complete internationalization system. The project is fully functional with 6 languages supported and 30+ government services available to citizens through the kiosk interface.
