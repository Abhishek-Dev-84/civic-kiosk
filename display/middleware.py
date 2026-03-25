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


class KioskExceptionMiddleware:
    """
    Catch-all exception handler to prevent raw Django error pages in kiosk mode.
    Any exception should render the existing standalone `500.html`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except Exception:
            # Never leak exception details to the kiosk UI.
            try:
                from django.http import JsonResponse
                from django.shortcuts import render

                accept = (request.headers.get("accept") or "").lower()
                if "application/json" in accept:
                    return JsonResponse({"error": "Internal Server Error"}, status=500)

                return render(request, "500.html", status=500)
            except Exception:
                # Last-resort fallback.
                from django.http import HttpResponse

                return HttpResponse(status=500)


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
    let loaderStartTime = 0;
    const MIN_LOADER_MS = 500;
    let safetyTimer = null;

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
        #${LOADER_ID} > div{
          width:100%; display:flex; flex-direction:column;
          align-items:center; justify-content:center;
          text-align:center;
        }
        #${LOADER_ID} .kiosk-spinner{
          width:54px; height:54px; border-radius:50%;
          border:6px solid #1e5fbf; border-top-color: #ff9933;
          animation: kiosk-spin 0.9s linear infinite;
          box-shadow: 0 8px 30px rgba(0,0,0,0.08);
          display:block;
          margin:0 auto;
          transform: translateZ(0);
        }
        @keyframes kiosk-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        #${LOADER_ID} .kiosk-loader-text{
          margin-top:12px; font: 700 18px/1.2 'Segoe UI', system-ui, sans-serif; color:#1e5fbf;
          text-align:center; padding: 0 12px;
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
        '</div>';
        document.body.appendChild(el);
      }
      return el;
    }

    function showLoader(){
      loaderStartTime = Date.now();
      const overlay = ensureOverlay();
      overlay.style.display = 'flex';
      // Disable multiple clicks / pointer events.
      document.documentElement.style.pointerEvents = 'none';
      overlay.style.pointerEvents = 'auto';

      // Safety: never keep the loader stuck forever.
      if (safetyTimer) clearTimeout(safetyTimer);
      safetyTimer = setTimeout(() => {
        try { hideLoader(); } catch(_) {}
      }, 45000);
    }

    function hideLoader(){
      const overlay = document.getElementById(LOADER_ID);
      const elapsed = loaderStartTime ? (Date.now() - loaderStartTime) : MIN_LOADER_MS;
      const delay = loaderStartTime ? Math.max(0, MIN_LOADER_MS - elapsed) : 0;

      setTimeout(() => {
        if (overlay) overlay.style.display = 'none';
        document.documentElement.style.pointerEvents = '';
      }, delay);

      if (safetyTimer) clearTimeout(safetyTimer);
      safetyTimer = null;
    }

    window.KioskLoader = { show: showLoader, hide: hideLoader };

    // Ensure loader doesn't remain visible on refresh/back-forward.
    document.addEventListener('DOMContentLoaded', () => {
      try { hideLoader(); } catch(_) {}
    });
    window.addEventListener('pageshow', () => {
      try { hideLoader(); } catch(_) {}
    });
    window.addEventListener('load', () => {
      try { hideLoader(); } catch(_) {}
    });

    // Attach loader only to the actions that should trigger navigation/loading.
    // - Form submits
    // - Page navigation elements (cards/anchors/back buttons)
    document.addEventListener('DOMContentLoaded', function(){
      try {
        // Forms: loader on submit only (no loader on input clicks/typing).
        document.querySelectorAll('form').forEach(function(form){
          if (!form || form.dataset.kioskLoaderBound === '1') return;
          form.dataset.kioskLoaderBound = '1';
          form.addEventListener('submit', function(){
            try {
              if (form.dataset.kioskSubmitting === '1') return;
              form.dataset.kioskSubmitting = '1';
              showLoader();

              // Disable submit controls to prevent multiple submissions.
              const submits = form.querySelectorAll('button[type=\"submit\"], input[type=\"submit\"]');
              submits.forEach(function(el){
                if (el && typeof el.disabled !== 'undefined') el.disabled = true;
              });
            } catch(_) {}
          }, true);
        });

        // Navigation: show loader when these elements are clicked.
        const navSelector = '.dept-card,.menu-card,.back-btn,.home-btn,.lang-btn,a[href]';
        document.querySelectorAll(navSelector).forEach(function(el){
          if (!el || el.dataset.kioskNavBound === '1') return;
          el.dataset.kioskNavBound = '1';
          el.addEventListener('click', function(ev){
            try {
              // Ignore clicks inside form inputs/labels.
              const target = ev && ev.target;
              if (target && target.closest && target.closest('input,textarea,select,label,[contenteditable=\"true\"]')) return;
              showLoader();

              // Best-effort disable (only if the element supports it).
              if (typeof el.disabled !== 'undefined' && !el.disabled) el.disabled = true;
            } catch(_) {}
          }, true);
        });
      } catch(_) {}
    });

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