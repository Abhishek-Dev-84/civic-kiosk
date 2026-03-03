# display/middleware.py
from django.shortcuts import redirect

class CleanNextParamMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Block ANY query parameters on auth pages
        if 'auth' in request.path and request.GET:
            # Redirect to clean auth URL without any parameters
            if request.path.startswith('/en/'):
                return redirect('/en/auth/')
            else:
                return redirect('/auth/')
        
        response = self.get_response(request)
        return response