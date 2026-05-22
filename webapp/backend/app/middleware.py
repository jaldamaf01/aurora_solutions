# webapp/backend/app/middleware.py
import os
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .logging_jsonl import JsonlWriter, get_log_path


def _get_client_ip(request: Request) -> str:
    # Detrás de Nginx, la IP real suele ir en X-Forwarded-For
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # puede venir "ip1, ip2, ip3"
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.writer = JsonlWriter(get_log_path())
        self.student_id = os.getenv("STUDENT_ID", "unknown")

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = None
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            end = time.perf_counter()
            latency_ms = round((end - start) * 1000, 2)

            event = {
                "student_id": self.student_id,
                "source": "server",
                "event_type": "server_request",
                "page": request.url.path,
                "request_path": request.url.path,
                "method": request.method,
                "status_code": int(status_code),
                "latency_ms": latency_ms,
                "ip": _get_client_ip(request),
                "user_agent": request.headers.get("user-agent"),
                "query": request.url.query or "",
            }

            # Evitar registrar el propio endpoint de health demasiado si molesta:
            # (puedes comentar esto)
            # if request.url.path == "/health":
            #     return

            self.writer.append(event)