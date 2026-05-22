# webapp/backend/app/logging_jsonl.py
import json
import os
from datetime import datetime, timezone

try:
    import fcntl  # Linux only (Ubuntu OK)
except ImportError:
    fcntl = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dt_from_iso(ts: str) -> str:
    # ts ISO8601 -> YYYY-MM-DD (si falla, usa fecha actual)
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return d.date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


class JsonlWriter:
    """
    Escribe 1 JSON por línea en un fichero JSONL.
    - Garantiza que el directorio existe.
    - Usa bloqueo (fcntl) si está disponible.
    """

    def __init__(self, path: str):
        self.path = path
        self._ensure_dir()

    def _ensure_dir(self):
        directory = os.path.dirname(self.path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

    def append(self, event: dict):
        # Normaliza mínimos
        if "timestamp" not in event or not event["timestamp"]:
            event["timestamp"] = utc_now_iso()
        if "dt" not in event or not event["dt"]:
            event["dt"] = dt_from_iso(event["timestamp"])

        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"

        # Append atómico con lock (si existe)
        with open(self.path, "a", encoding="utf-8") as f:
            if fcntl is not None:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                except Exception:
                    pass
            f.write(line)
            f.flush()
            if fcntl is not None:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass


def get_log_path() -> str:
    return os.getenv("AURORA_LOG_PATH", "/var/log/aurora/aurora_clickstream.jsonl")