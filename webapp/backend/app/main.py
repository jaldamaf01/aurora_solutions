# webapp/backend/app/main.py
import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .models import TrackEvent
from .logging_jsonl import JsonlWriter, get_log_path, utc_now_iso, dt_from_iso
from .middleware import RequestLoggingMiddleware

app = FastAPI(title="Aurora Clickstream Collector", version="1.0.0")

# Middleware server-side (log de todas las requests)
app.add_middleware(RequestLoggingMiddleware)

# Writer para eventos client-side (/track)
writer = JsonlWriter(get_log_path())

# Identificador del alumno (se pondrá en entorno, Nginx/systemd o .env)
STUDENT_ID = os.getenv("STUDENT_ID", "unknown")


@app.get("/health")
def health():
    return {"status": "ok", "service": "aurora-clickstream", "student_id": STUDENT_ID}


@app.post("/track")
async def track(ev: TrackEvent, request: Request):
    """
    Recibe eventos del front y los escribe en JSONL.
    Normaliza campos mínimos (timestamp/dt/student_id/source).
    """
    data = ev.to_event_dict()

    # Asegurar student_id
    if not data.get("student_id"):
        data["student_id"] = STUDENT_ID

    # Asegurar source client (aunque venga mal)
    data["source"] = "client"

    # Asegurar timestamp/dt
    if not data.get("timestamp"):
        data["timestamp"] = utc_now_iso()
    if not data.get("dt"):
        data["dt"] = dt_from_iso(data["timestamp"])

    # Si page no viene, usa path de la request (por si algún cliente lo omite)
    if not data.get("page"):
        data["page"] = request.headers.get("referer") or request.url.path

    # IP y user-agent pueden enriquecer los eventos client-side también (opcional)
    xff = request.headers.get("x-forwarded-for")
    ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "unknown")
    data.setdefault("ip", ip)
    data.setdefault("user_agent", request.headers.get("user-agent"))

    writer.append(data)
    return JSONResponse({"status": "ok"})


# Manejo mínimo de errores (opcional)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": str(exc)}
    )