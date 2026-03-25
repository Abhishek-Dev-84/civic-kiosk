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


class KioskLoaderMiddleware:
    """
    Inject a small, UI-neutral loader script into HTML responses.

    This avoids editing dozens of templates while still enabling:
    - loader overlay on click/submit/navigation
    - basic double-click prevention
    - lightweight skeleton placeholder insertion (no layout changes)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            content_type = (response.get("Content-Type") or "").lower()
            if "text/html" not in content_type:
                return response
            if not hasattr(response, "content"):
                return response

            body = response.content or b""
            marker = b"</body>"
            if marker not in body:
                return response

            # Avoid injecting twice (e.g. internal redirects).
            if b"id=\"kiosk-global-loader\"" in body:
                return response

            injection = b"""
<script>
(function(){
  try {
    const LOADER_ID = 'kiosk-global-loader';
    const SKELETON_CLASS = 'kiosk-skeleton-row';

    function ensureStyles(){
      if (document.getElementById('kiosk-global-loader-styles')) return;
      const style = document.createElement('style');
      style.id = 'kiosk-global-loader-styles';
      style.textContent = `
        #${LOADER_ID}{
          position:fixed; inset:0; z-index:999999;
          display:none; align-items:center; justify-content:center;
          background: rgba(255,255,255,0.70);
          backdrop-filter: blur(2px);
          cursor: progress;
        }
        #${LOADER_ID} .kiosk-spinner{
          width:54px; height:54px; border-radius:50%;
          border:6px solid #1e5fbf; border-top-color: #ff9933;
          animation: kiosk-spin 0.9s linear infinite;
          box-shadow: 0 8px 30px rgba(0,0,0,0.08);
        }
        @keyframes kiosk-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        #${LOADER_ID} .kiosk-loader-text{
          margin-top:12px; font: 700 18px/1.2 'Segoe UI', system-ui, sans-serif; color:#1e5fbf;
          text-align:center; padding: 0 12px;
        }
        .${SKELETON_CLASS}{
          height: 14px; border-radius: 10px; background: #e9f2ff; margin: 8px 0;
          position: relative; overflow: hidden;
        }
        .${SKELETON_CLASS}::after{
          content:'';
          position:absolute; top:0; left:-40%;
          width:40%; height:100%;
          background: linear-gradient(90deg, transparent, rgba(30,95,191,0.18), transparent);
          animation: kiosk-skeleton-shimmer 1.0s ease-in-out infinite;
        }
        @keyframes kiosk-skeleton-shimmer {
          from { transform: translateX(0); }
          to { transform: translateX(250%); }
        }
      `;
      document.head.appendChild(style);
    }

    function ensureOverlay(){
      ensureStyles();
      let el = document.getElementById(LOADER_ID);
      if (!el){
        el = document.createElement('div');
        el.id = LOADER_ID;
        el.innerHTML = '<div>' +
          '<div class=\"kiosk-spinner\"></div>' +
          '<div class=\"kiosk-loader-text\">Loading...</div>' +
          '<div class=\"kiosk-skeleton-box\" style=\"width:80%; max-width:420px;\"></div>' +
        '</div>';
        document.body.appendChild(el);
      }
      return el;
    }

    let disabledButtons = [];

    function showLoader(){
      const overlay = ensureOverlay();
      overlay.style.display = 'flex';
      // Disable multiple clicks / pointer events.
      document.documentElement.style.pointerEvents = 'none';
      overlay.style.pointerEvents = 'auto';

      // Skeleton rows rendered INSIDE the loader (no DOM replacement => no event handler loss).
      const skBox = overlay.querySelector('.kiosk-skeleton-box');
      if (skBox){
        skBox.innerHTML = '';
        for (let i=0;i<6;i++){
          const row = document.createElement('div');
          row.className = '${SKELETON_CLASS}';
          row.style.width = (70 + Math.floor(Math.random()*25)) + '%';
          skBox.appendChild(row);
        }
      }
    }

    function hideLoader(){
      const overlay = document.getElementById(LOADER_ID);
      if (overlay) overlay.style.display = 'none';
      document.documentElement.style.pointerEvents = '';

      // Restore disabled buttons for pages that don't fully navigate.
      for (const btn of disabledButtons){
        try {
          if (btn && typeof btn.disabled !== 'undefined') btn.disabled = false;
        } catch (_) {}
      }
      disabledButtons = [];
    }

    window.KioskLoader = { show: showLoader, hide: hideLoader };

    // Click-based navigation (covers most kiosk cards/buttons).
    document.addEventListener('click', function(e){
      const a = e.target && e.target.closest ? e.target.closest('a') : null;
      const btn = e.target && e.target.closest ? e.target.closest('button,[role=\"button\"],.dept-card,.menu-card,.back-btn') : null;
      if (!a && !btn) return;
      if (e.defaultPrevented) return;
      if (btn && (btn.disabled || btn.getAttribute('aria-disabled') === 'true')) return;
      if (btn && btn.type === 'button') {
        // Many buttons use onclick/window.location; show loader anyway.
      }
      showLoader();
      // Prevent double-click: best-effort disable/lock for short time.
      if (btn && typeof btn.disabled !== 'undefined' && !btn.disabled){
        disabledButtons.push(btn);
        btn.disabled = true;
      }
    }, true);

    // Form submissions
    document.addEventListener('submit', function(e){
      try { showLoader(); } catch(_) {}
    }, true);

  } catch(err){
    // Never break page if loader injection fails.
    console.warn('KioskLoader init failed', err);
  }
})();
</script>
            """

            response.content = body.replace(marker, injection + marker)
        except Exception:
            # Emergency rule: never fail template rendering because of loader injection.
            return response

        return response