from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class CSRFHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            # Only enforce CSRF check if cookies are present in the request
            if request.cookies:
                if "x-requested-with" not in request.headers:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF verification failed: missing X-Requested-With header"}
                    )
        return await call_next(request)
