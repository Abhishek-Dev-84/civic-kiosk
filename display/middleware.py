# display/middleware.py
from django.shortcuts import redirect
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta
import logging
from .models import UserSession, AuditLog

logger = logging.getLogger(__name__)


class KioskSessionMiddleware:
    """
    Middleware for kiosk-specific session management
    - Auto-logout after 5 minutes of inactivity
    - Single active session enforcement
    - Session activity tracking
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip for non-authenticated paths
        if not request.session.get('aadhaar_verified') or request.path in ['/', '/auth/', '/otp/', '/resend-otp/']:
            return self.get_response(request)

        # Check for inactivity timeout (5 minutes)
        last_activity = request.session.get('last_activity')
        if last_activity:
            try:
                inactive_time = datetime.now() - datetime.fromisoformat(last_activity)
                if inactive_time.total_seconds() > 300:  # 5 minutes
                    # Logout user
                    consumer_id = request.session.get('consumer_id')
                    if consumer_id:
                        # Deactivate session
                        UserSession.objects.filter(
                            consumer_id=consumer_id,
                            session_key=request.session.session_key
                        ).update(is_active=False)
                    
                    # Clear session
                    request.session.flush()
                    messages.warning(request, 'Session expired due to inactivity')
                    return redirect('auth')
            except:
                pass  # If date parsing fails, continue

        # Update last activity
        request.session['last_activity'] = datetime.now().isoformat()
        
        # Check for forced logout from other sessions
        if request.session.session_key:
            from django.core.cache import cache
            if cache.get(f'force_logout_{request.session.session_key}'):
                request.session.flush()
                messages.warning(request, 'You have been logged out from another session')
                return redirect('auth')

        return self.get_response(request)


class AuditLogMiddleware:
    """
    Middleware to log all user actions
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Log all POST requests (data modifications)
        if request.method == 'POST' and request.session.get('consumer_id'):
            self.log_action(request, response)

        return response

    def log_action(self, request, response):
        """Log user action to database"""
        try:
            consumer_id = request.session.get('consumer_id')
            if not consumer_id:
                return

            # Don't log OTP pages for privacy
            if 'otp' in request.path:
                return

            # Limit data size
            post_data = dict(request.POST)
            
            # Remove sensitive data
            sensitive_fields = ['otp', 'password', 'pin', 'cvv', 'card_number']
            for field in sensitive_fields:
                if field in post_data:
                    post_data[field] = '***'

            # Create audit log
            AuditLog.objects.create(
                consumer_id=consumer_id,
                action=request.path,
                model_name='View',
                object_id='',
                changes={
                    'method': request.method,
                    'data': str(post_data)[:500],  # Limit size
                    'response_code': response.status_code
                },
                ip_address=self.get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
            )
        except Exception as e:
            logger.error(f"Audit log error: {e}")

    def get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR', '0.0.0.0')


class KioskSecurityMiddleware:
    """
    Kiosk-specific security measures
    - Block access to admin from kiosk
    - Add security headers
    - Prevent browser features that could be misused
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Block access to admin panel from kiosk (if user agent indicates kiosk)
        if request.path.startswith('/admin/'):
            user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
            if 'kiosk' in user_agent or 'touch' in user_agent:
                from django.http import HttpResponseForbidden
                return HttpResponseForbidden("Access Denied")

        # Add security headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'same-origin'
        
        # Prevent caching of sensitive pages
        if request.path.startswith(('/auth/', '/otp/', '/menu/')):
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'

        return response