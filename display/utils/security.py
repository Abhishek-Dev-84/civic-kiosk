# display/utils/security.py
import hashlib
import secrets
import re
from datetime import datetime, timedelta
from django.core.cache import cache
from django.core.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)


def generate_secure_otp(length=6):
    """
    Generate cryptographically secure OTP
    Uses secrets module for true randomness
    """
    return ''.join(secrets.choice('0123456789') for _ in range(length))


def hash_otp(otp):
    """
    Hash OTP for secure storage
    Uses SHA-256 with salt
    """
    salt = secrets.token_hex(8)
    hash_obj = hashlib.sha256(f"{otp}{salt}".encode())
    return f"{salt}${hash_obj.hexdigest()}"


def verify_otp_hash(stored_hash, provided_otp):
    """
    Verify OTP against stored hash
    Format: salt$hash
    """
    try:
        salt, hash_value = stored_hash.split('$')
        computed_hash = hashlib.sha256(f"{provided_otp}{salt}".encode()).hexdigest()
        return computed_hash == hash_value
    except:
        return False


def rate_limit_check(key, max_attempts=5, time_window=300):
    """
    Check rate limit for a given key
    Returns (is_allowed, attempts_left, reset_time)
    
    Fixed to work with all cache backends (including LocMemCache)
    """
    attempts = cache.get(key, 0)
    
    if attempts >= max_attempts:
        # For LocMemCache, we need to estimate remaining time
        # Since ttl() isn't available, we'll return None for reset_time
        return False, 0, None
    
    # Increment attempts
    cache.set(key, attempts + 1, timeout=time_window)
    remaining = max_attempts - (attempts + 1)
    return True, remaining, time_window


def validate_aadhaar(aadhaar_number):
    """
    Validate Aadhaar number format and checksum
    Uses Verhoeff algorithm for checksum validation
    """
    # Remove spaces if any
    aadhaar = aadhaar_number.replace(' ', '')
    
    # Check length and digits
    if not aadhaar.isdigit() or len(aadhaar) != 12:
        return False, "Aadhaar must be 12 digits"
    
    # Verhoeff algorithm implementation
    # d - check digit
    # Table d
    verhoeff_table_d = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
        [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
        [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
        [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
        [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
        [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
        [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
        [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
        [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
    ]
    
    # Table p
    verhoeff_table_p = [
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
        [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
        [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
        [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
        [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
        [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
        [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]
    ]
    
    # Table inv
    verhoeff_table_inv = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]
    
    try:
        # Reverse the number
        aadhaar_rev = aadhaar[::-1]
        check = 0
        
        for i, digit_char in enumerate(aadhaar_rev):
            digit = int(digit_char)
            check = verhoeff_table_d[check][verhoeff_table_p[i % 8][digit]]
        
        return verhoeff_table_inv[check] == 0, "Valid Aadhaar"
    except:
        return False, "Invalid Aadhaar checksum"


def sanitize_input(value, max_length=None):
    """
    Sanitize user input to prevent XSS attacks
    """
    if value is None:
        return ""
    
    # Convert to string
    value = str(value)
    
    # Remove any HTML tags
    import re
    value = re.sub(r'<[^>]*>', '', value)
    
    # Remove JavaScript event handlers
    value = re.sub(r'on\w+="[^"]*"', '', value, flags=re.IGNORECASE)
    value = re.sub(r"on\w+='[^']*'", '', value, flags=re.IGNORECASE)
    
    # Remove javascript: links
    value = re.sub(r'javascript:', '', value, flags=re.IGNORECASE)
    
    # Trim whitespace
    value = value.strip()
    
    # Truncate if max_length specified
    if max_length and len(value) > max_length:
        value = value[:max_length]
    
    return value


def mask_sensitive_data(data, fields_to_mask=None):
    """
    Mask sensitive data for logging
    """
    if fields_to_mask is None:
        fields_to_mask = ['aadhaar', 'mobile', 'phone', 'email', 'card', 'cvv', 'pin', 'otp']
    
    if isinstance(data, dict):
        masked = {}
        for key, value in data.items():
            key_lower = key.lower()
            if any(field in key_lower for field in fields_to_mask):
                if value and len(str(value)) > 4:
                    masked[key] = str(value)[-4:].rjust(len(str(value)), '*')
                else:
                    masked[key] = '***'
            elif isinstance(value, (dict, list)):
                masked[key] = mask_sensitive_data(value, fields_to_mask)
            else:
                masked[key] = value
        return masked
    elif isinstance(data, list):
        return [mask_sensitive_data(item, fields_to_mask) for item in data]
    else:
        return data


def generate_csrf_token():
    """
    Generate a secure CSRF token
    """
    return secrets.token_urlsafe(32)


def validate_file_extension(filename, allowed_extensions=None):
    """
    Validate file extension against allowed list
    """
    if allowed_extensions is None:
        allowed_extensions = ['.pdf', '.jpg', '.jpeg', '.png', '.dwg']
    
    import os
    ext = os.path.splitext(filename)[1].lower()
    return ext in allowed_extensions, ext


def validate_file_size(file_obj, max_size_mb=25):
    """
    Validate file size
    """
    max_size_bytes = max_size_mb * 1024 * 1024
    return file_obj.size <= max_size_bytes, file_obj.size


def get_client_ip(request):
    """
    Get client IP address from request
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def log_security_event(request, event_type, details):
    """
    Log security events
    """
    from ..models import AuditLog
    
    try:
        consumer_id = request.session.get('consumer_id')
        AuditLog.objects.create(
            consumer_id=consumer_id,
            action=f'SECURITY_{event_type}',
            model_name='Security',
            object_id='',
            changes={'details': details},
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
        )
    except Exception as e:
        logger.error(f"Failed to log security event: {e}")