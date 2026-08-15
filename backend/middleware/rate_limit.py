"""
Rate limiting middleware for QuantPlatform.
Integrates slowapi for rate limiting based on remote IP address.
"""
from slowapi.middleware import SlowAPIMiddleware
from backend.core.limiter import limiter
