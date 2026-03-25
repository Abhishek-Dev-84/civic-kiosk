/**
 * Kiosk Core JavaScript Library
 * Handling Security, UI Interactivity, Loading States, Session Timeouts and Form Submissions.
 */

const KioskCore = (function() {
    // Config
    let config = {
        sessionDuration: 240000,     // 4 minutes
        warningTime: 60000,          // 1 minute before expiry
        csrfToken: '',
        logoutUrl: '/',
        languageCode: 'en'
    };

    let sessionTimer;
    let timeoutWarningTimer;
    let isSubmitting = false;

    // --- Loading Overlay ---
    const LoadingState = {
        show: function(text) {
            const overlay = document.getElementById('globalLoadingOverlay');
            const textEl = document.getElementById('globalLoadingText');
            if (overlay) {
                if (text && textEl) textEl.textContent = text;
                overlay.classList.add('active');
            }
        },
        hide: function() {
            const overlay = document.getElementById('globalLoadingOverlay');
            if (overlay) overlay.classList.remove('active');
        }
    };

    // --- Session Management ---
    const SessionManager = {
        startTimer: function() {
            clearTimeout(sessionTimer);
            clearTimeout(timeoutWarningTimer);
            
            sessionTimer = setTimeout(() => {
                this.showWarning();
            }, config.sessionDuration - config.warningTime);
        },
        
        resetTimer: function() {
            if (document.getElementById('timeoutWarning')?.classList.contains('active')) {
                return; // Don't auto-reset if warning is showing
            }
            this.startTimer();
        },
        
        showWarning: function() {
            const warning = document.getElementById('timeoutWarning');
            if (warning) {
                warning.classList.add('active');
                timeoutWarningTimer = setTimeout(() => {
                    window.location.href = config.logoutUrl;
                }, config.warningTime);
            }
        },
        
        extendSession: function() {
            const warning = document.getElementById('timeoutWarning');
            if (warning) warning.classList.remove('active');
            this.startTimer();
            // Ping server to keep session alive
            fetch(window.location.href, { method: 'HEAD' }).catch(e => console.error(e));
        }
    };

    // --- Security & UI Hardening ---
    const Security = {
        init: function() {
            // Disable specific keyboard shortcuts
            document.addEventListener('keydown', function(e) {
                if (e.key === 'F12' || 
                    (e.ctrlKey && e.shiftKey && (e.key === 'I' || e.key === 'J')) ||
                    (e.ctrlKey && e.key === 'U')) {
                    e.preventDefault();
                    return false;
                }
                // Prevent backspace nav
                if (e.key === 'Backspace' && !e.target.matches('input, textarea, [contenteditable]')) {
                    e.preventDefault();
                }
            });

            // Disable Right Click
            document.addEventListener('contextmenu', e => e.preventDefault());

            // Auto-hide cursor on touch devices to avoid ghost cursors
            let cursorTimeout;
            document.addEventListener('touchstart', function() {
                document.body.style.cursor = 'default';
                clearTimeout(cursorTimeout);
                cursorTimeout = setTimeout(() => { document.body.style.cursor = 'none'; }, 3000);
            });

            // Prevent double tap zoom
            let lastTouchEnd = 0;
            document.addEventListener('touchend', function(e) {
                const now = (new Date()).getTime();
                if (now - lastTouchEnd <= 300) e.preventDefault();
                lastTouchEnd = now;
            }, false);

            // Hide messages after 5 seconds
            setTimeout(() => {
                document.querySelectorAll('.message').forEach(msg => {
                    msg.style.opacity = '0';
                    setTimeout(() => msg.remove(), 500);
                });
            }, 5000);
        }
    };

    // --- Form & Button Handling (Prevent Multiple Clicks) ---
    const FormHandler = {
        init: function() {
            document.querySelectorAll('form').forEach(form => {
                form.addEventListener('submit', function(e) {
                    if (isSubmitting) {
                        e.preventDefault();
                        return false;
                    }
                    
                    const isValid = typeof form.checkValidity === 'function' ? form.checkValidity() : true;
                    if (isValid) {
                        isSubmitting = true;
                        
                        // Disable submit button inside the form
                        const submitBtns = form.querySelectorAll('button[type="submit"], input[type="submit"]');
                        submitBtns.forEach(btn => {
                            btn.disabled = true;
                            if (btn.tagName === 'BUTTON') {
                                btn.dataset.originalText = btn.innerHTML;
                                btn.innerHTML = 'Processing...';
                                btn.style.opacity = '0.7';
                            }
                        });

                        LoadingState.show();
                    }
                });
            });

            // For standalone interactive buttons that cause wait
            document.querySelectorAll('.btn-click-wait').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    if (isSubmitting) {
                        e.preventDefault();
                        e.stopPropagation();
                        return;
                    }
                    if (this.tagName === 'A' || !this.closest('form')) {
                        isSubmitting = true;
                        this.style.pointerEvents = 'none';
                        this.style.opacity = '0.7';
                        LoadingState.show();
                    }
                });
            });
        }
    };

    // --- Fetch/AJAX Interceptor ---
    const FetchInterceptor = {
        init: function() {
            const originalFetch = window.fetch;
            window.fetch = async function(...args) {
                // Ignore silent background pings
                const isBackground = typeof args[0] === 'string' && args[0].includes('ping');
                if (!isBackground) LoadingState.show();
                
                try {
                    const response = await originalFetch(...args);
                    if (!isBackground) LoadingState.hide();
                    return response;
                } catch (error) {
                    if (!isBackground) {
                        LoadingState.hide();
                        console.error('Network Error:', error);
                        // Could show a toast message here
                    }
                    throw error;
                }
            };
        }
    };

    // --- Initialization ---
    return {
        init: function(customConfig) {
            Object.assign(config, customConfig);
            
            // Setup Session Timer Events
            document.addEventListener('click', () => SessionManager.resetTimer());
            document.addEventListener('keypress', () => SessionManager.resetTimer());
            document.addEventListener('touchstart', () => SessionManager.resetTimer());
            SessionManager.startTimer();

            // Bind UI Elements
            document.getElementById('btnExtendSession')?.addEventListener('click', () => SessionManager.extendSession());
            document.getElementById('btnLogoutSession')?.addEventListener('click', () => window.location.href = config.logoutUrl);
            document.getElementById('globalBackBtn')?.addEventListener('click', () => {
                LoadingState.show();
                window.history.back(); 
            });

            Security.init();
            FormHandler.init();
            FetchInterceptor.init();
        },
        
        showLoading: LoadingState.show,
        hideLoading: LoadingState.hide,
        preventSubmissions: () => { isSubmitting = true; },
        allowSubmissions: () => { isSubmitting = false; }
    };
})();
