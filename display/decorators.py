# display/decorators.py
from django.shortcuts import redirect
from django.contrib import messages
from django.core.cache import cache
from functools import wraps
import logging
from .utils.security import rate_limit_check, get_client_ip

logger = logging.getLogger(__name__)


def kiosk_login_required(view_func):
    """
    Decorator to require kiosk authentication
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.session.get('aadhaar_verified') or not request.session.get('otp_verified'):
            messages.error(request, 'Please login first')
            return redirect('auth')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def rate_limit(max_attempts=5, time_window=300, key_prefix='rate_limit'):
    """
    Decorator to rate limit views
    Fixed to handle LocMemCache which doesn't have ttl()
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Get client identifier (IP + user if authenticated)
            client_ip = get_client_ip(request)
            consumer_id = request.session.get('consumer_id', 'anonymous')
            rate_key = f"{key_prefix}:{consumer_id}:{client_ip}:{request.path}"
            
            # Check rate limit
            allowed, remaining, reset_time = rate_limit_check(rate_key, max_attempts, time_window)
            
            if not allowed:
                # For LocMemCache, we don't have reset_time, so show generic message
                if reset_time:
                    messages.error(request, f'Too many attempts. Please try again in {reset_time} seconds.')
                else:
                    messages.error(request, 'Too many attempts. Please try again later.')
                logger.warning(f"Rate limit exceeded for {client_ip} on {request.path}")
                return redirect(request.META.get('HTTP_REFERER', 'menu'))
            
            # Add rate limit info to request
            request.rate_limit_remaining = remaining
            request.rate_limit_reset = reset_time
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def prevent_concurrent_sessions(view_func):
    """
    Decorator to prevent concurrent sessions for same user
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        consumer_id = request.session.get('consumer_id')
        session_key = request.session.session_key
        
        if consumer_id and session_key:
            from .models import UserSession
            
            # Check for other active sessions
            other_sessions = UserSession.objects.filter(
                consumer_id=consumer_id,
                is_active=True
            ).exclude(session_key=session_key)
            
            if other_sessions.exists():
                # Notify user about other active sessions
                messages.warning(
                    request, 
                    'You have an active session on another device. Continuing here will log out the other session.'
                )
                request.has_other_sessions = True
            
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def log_activity(action_name=None):
    """
    Decorator to log user activity
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            response = view_func(request, *args, **kwargs)
            
            # Log activity if user is authenticated
            if request.session.get('consumer_id'):
                from .models import AuditLog
                
                try:
                    AuditLog.objects.create(
                        consumer_id=request.session.get('consumer_id'),
                        action=action_name or request.path,
                        model_name='View',
                        object_id='',
                        changes={'method': request.method},
                        ip_address=get_client_ip(request),
                        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
                    )
                except Exception as e:
                    logger.error(f"Failed to log activity: {e}")
            
            return response
        return _wrapped_view
    return decorator


def validate_csrf_token(view_func):
    """
    Custom CSRF validation for API endpoints
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.method == 'POST':
            # Get token from header or session
            header_token = request.headers.get('X-CSRFToken')
            session_token = request.session.get('csrf_token')
            
            if not header_token or not session_token or header_token != session_token:
                from django.http import JsonResponse
                return JsonResponse({'error': 'Invalid CSRF token'}, status=403)
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def require_minimum_load(min_load=1.0):
    """
    Decorator for load enhancement views to validate minimum load
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if request.method == 'POST':
                requested_load = request.POST.get('requested_load')
                if requested_load:
                    try:
                        load_value = float(requested_load)
                        if load_value < min_load:
                            messages.error(request, f'Minimum load required is {min_load} kW')
                            return redirect(request.path)
                    except ValueError:
                        messages.error(request, 'Invalid load value')
                        return redirect(request.path)
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def kiosk_maintenance_mode(view_func):
    """
    Decorator to check if kiosk is in maintenance mode
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Check if maintenance mode is enabled in cache
        if cache.get('kiosk_maintenance_mode', False):
            # Allow access to specific IPs (admin/staff)
            allowed_ips = cache.get('maintenance_allowed_ips', [])
            client_ip = get_client_ip(request)
            
            if client_ip not in allowed_ips:
                from django.shortcuts import render
                return render(request, 'maintenance.html', status=503)
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view