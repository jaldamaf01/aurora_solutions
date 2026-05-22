#!/usr/bin/env python3
# simulators/replay_clickstream.py
"""
Genera masa de eventos clickstream en formato JSON Lines (JSONL), repartidos en N días.
- Escribe directamente en un fichero JSONL (por defecto el mismo que lee CloudWatch Agent).
- No requiere tocar FastAPI: es "replay/generación masiva" para alcanzar >=200k eventos.

Opcionalmente puede generar también eventos server-side sintéticos (server_request)
para que haya datos de latencia/status en el mismo JSONL (útil para CloudWatch queries).

Uso típico (volumen):
  python3 simulators/replay_clickstream.py \
    --student-id alu01 \
    --days 7 \
    --n-events 200000 \
    --events-json ./webapp/frontend/data/events.json \
    --campaigns-csv ./output_business/campaigns.csv \
    --out /var/log/aurora/aurora_clickstream.jsonl \
    --append

Ejemplo con server events sintéticos:
  python3 simulators/replay_clickstream.py ... --include-server 1
"""

import argparse
import json
import os
import random
import csv
from datetime import datetime, timedelta, timezone
from hashlib import sha256


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
]

PAGES = ["/", "/events.html", "/event_detail.html", "/checkout.html", "/purchase_ok.html"]

EVENT_TYPES_FUNNEL = [
    "page_view",
    "view_event_list",
    "view_event_detail",
    "begin_checkout",
    "purchase",
]

def parse_args():
    ap = argparse.ArgumentParser(description="Replay/generador masivo de clickstream JSONL")
    ap.add_argument("--student-id", required=True)
    ap.add_argument("--seed", type=int, default=None, help="Semilla (si no, se deriva de student_id)")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--start-date", default=None, help="YYYY-MM-DD. Si no, hoy-(days-1)")
    ap.add_argument("--n-events", type=int, default=200000, help="Nº total de eventos a generar (client-side + extras)")
    ap.add_argument("--events-json", required=True, help="Ruta a events.json (catálogo que usa la web)")
    ap.add_argument("--campaigns-csv", required=True, help="Ruta a campaigns.csv (para utm_campaign)")
    ap.add_argument("--out", default="/var/log/aurora/aurora_clickstream.jsonl")
    ap.add_argument("--append", action="store_true", help="Append en lugar de sobrescribir")
    ap.add_argument("--include-server", type=int, default=1, help="1=generar server_request sintéticos; 0=no")
    ap.add_argument("--bot-rate", type=float, default=0.01, help="Porcentaje de sesiones con patrón 'bot' (0-0.1)")
    ap.add_argument("--peak-hour", type=int, default=21, help="Hora pico (0-23) para simular concentraciones")
    return ap.parse_args()

def derive_seed(student_id: str) -> int:
    h = sha256(student_id.encode("utf-8")).hexdigest()
    return int(h[:8], 16)

def ensure_dir(path: str):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def load_events(events_json_path: str):
    with open(events_json_path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    events = obj.get("events", [])
    # normaliza
    cleaned = []
    for e in events:
        try:
            cleaned.append({
                "event_id": int(e["event_id"]),
                "base_price": float(e.get("base_price", 20.0)),
                "name": e.get("name", ""),
                "city": e.get("city", ""),
                "category": e.get("category", "")
            })
        except Exception:
            pass
    if not cleaned:
        raise ValueError("events.json no contiene eventos válidos")
    return cleaned

def load_campaigns(campaigns_csv_path: str):
    campaigns = []
    with open(campaigns_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            utm = (r.get("utm_campaign") or "").strip()
            if utm:
                campaigns.append(utm)
    if not campaigns:
        # si todo está vacío por errores intencionados, usa fallback
        campaigns = ["direct", "spring_sale_fallback"]
    return campaigns

def dt_from_ts(ts: datetime) -> str:
    return ts.date().isoformat()

def iso(ts: datetime) -> str:
    return ts.isoformat()

def random_ip(rng: random.Random, is_bot: bool):
    # IPs "normales" vs IP "bot" persistente
    if is_bot:
        return f"10.9.{rng.randint(0, 10)}.{rng.randint(1, 10)}"
    return f"{rng.randint(1, 223)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"

def biased_timestamp(rng: random.Random, day_start: datetime, peak_hour: int):
    """
    Genera timestamp con más probabilidad alrededor de peak_hour.
    (Distribución simple por mezcla de normales truncadas)
    """
    # mezcla: 70% alrededor del pico, 30% uniforme
    if rng.random() < 0.7:
        # normal alrededor del pico
        h = int(max(0, min(23, rng.gauss(mu=peak_hour, sigma=2.5))))
        m = rng.randint(0, 59)
        s = rng.randint(0, 59)
    else:
        h = rng.randint(0, 23)
        m = rng.randint(0, 59)
        s = rng.randint(0, 59)
    return day_start.replace(hour=h, minute=m, second=s)

def make_session_id(rng: random.Random):
    token = "".join(rng.choice("0123456789abcdef") for _ in range(10))
    return f"sess_{token}_{rng.randint(100000,999999)}"

def choose_campaign_for_session(rng: random.Random, campaigns: list):
    # 60% con campaña, 40% directo (None)
    if rng.random() < 0.60:
        return rng.choice(campaigns)
    return None

def funnel_for_session(rng: random.Random):
    """
    Define cuántos eventos y qué secuencia produce una sesión.
    Aproximación realista:
    - siempre hay page_view + view_event_list
    - parte visita detalle
    - parte inicia checkout
    - parte compra
    """
    seq = ["page_view", "view_event_list"]

    # 75% visita detalle
    if rng.random() < 0.75:
        seq.append("view_event_detail")

        # 35% inicia checkout si vio detalle
        if rng.random() < 0.35:
            seq.append("begin_checkout")

            # 55% compra si inició checkout
            if rng.random() < 0.55:
                seq.append("purchase")

    # añade algunos clicks extra (ruido)
    extra_clicks = rng.randint(0, 3)
    return seq, extra_clicks

def write_line(f, obj: dict):
    f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")

def build_client_event(student_id, ts, session_id, event_type, page,
                       event_id=None, utm_campaign=None, referrer=None,
                       action=None, element_id=None, amount=None, ip=None, user_agent=None):
    return {
        "student_id": student_id,
        "timestamp": iso(ts),
        "dt": dt_from_ts(ts),
        "session_id": session_id,
        "event_type": event_type,
        "source": "client",
        "page": page,
        "action": action,
        "element_id": element_id,
        "event_id": event_id,
        "utm_campaign": utm_campaign,
        "referrer": referrer,
        "amount": amount,
        "ip": ip,
        "user_agent": user_agent
    }

def build_server_event(student_id, ts, session_id, request_path, method, status_code, latency_ms, ip, user_agent, query=""):
    return {
        "student_id": student_id,
        "timestamp": iso(ts),
        "dt": dt_from_ts(ts),
        "session_id": session_id,  # útil para joins aunque sea server-side
        "event_type": "server_request",
        "source": "server",
        "page": request_path,
        "request_path": request_path,
        "method": method,
        "status_code": int(status_code),
        "latency_ms": float(latency_ms),
        "ip": ip,
        "user_agent": user_agent,
        "query": query
    }

def main():
    args = parse_args()
    seed = args.seed if args.seed is not None else derive_seed(args.student_id)
    rng = random.Random(seed)

    # Fechas base
    if args.start_date:
        start_day = datetime.fromisoformat(args.start_date).replace(tzinfo=timezone.utc)
    else:
        today = datetime.now(timezone.utc).date()
        start_day = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) - timedelta(days=args.days - 1)

    events = load_events(args.events_json)
    campaigns = load_campaigns(args.campaigns_csv)

    ensure_dir(args.out)
    mode = "a" if args.append else "w"

    # Aproximación: generamos sesiones y distribuimos eventos hasta alcanzar n_events
    # Cada sesión genera: funnel + clicks extra (+ server events opcionales)
    total_written = 0
    sessions = 0

    # referrer dummy (se puede mejorar)
    possible_referrers = ["https://google.com", "https://instagram.com", "https://tiktok.com", "https://newsletter.example", None]

    with open(args.out, mode, encoding="utf-8") as f:
        while total_written < args.n_events:
            sessions += 1
            # Día aleatorio dentro del rango
            day_offset = rng.randint(0, args.days - 1)
            day_start = (start_day + timedelta(days=day_offset)).replace(hour=0, minute=0, second=0)

            is_bot = (rng.random() < args.bot_rate)
            session_id = make_session_id(rng)
            utm = choose_campaign_for_session(rng, campaigns)
            ref = rng.choice(possible_referrers)
            ua = rng.choice(USER_AGENTS)
            ip = random_ip(rng, is_bot)

            seq, extra_clicks = funnel_for_session(rng)

            # selecciona un evento para la sesión (si visita detalle/checkout/compra)
            chosen_event = rng.choice(events)
            event_id = chosen_event["event_id"]
            base_price = chosen_event["base_price"]

            # genera secuencia con timestamps ligeramente crecientes
            t = biased_timestamp(rng, day_start, args.peak_hour)

            for et in seq:
                if total_written >= args.n_events:
                    break

                if et == "page_view":
                    page = "/"
                elif et == "view_event_list":
                    page = "/events.html"
                elif et == "view_event_detail":
                    page = "/event_detail.html"
                elif et == "begin_checkout":
                    page = "/checkout.html"
                elif et == "purchase":
                    page = "/purchase_ok.html"
                else:
                    page = "/"

                # client event
                amount = base_price if et == "purchase" else None
                ev = build_client_event(
                    student_id=args.student_id,
                    ts=t,
                    session_id=session_id,
                    event_type=et,
                    page=page,
                    event_id=(event_id if et in ["view_event_detail", "begin_checkout", "purchase"] else None),
                    utm_campaign=utm,
                    referrer=ref,
                    action=("load" if et == "page_view" else et),
                    element_id=None,
                    amount=amount,
                    ip=ip,
                    user_agent=ua
                )
                write_line(f, ev)
                total_written += 1

                # server synthetic event (opcional)
                if args.include_server == 1 and total_written < args.n_events:
                    # simula status/latencia; bots generan más requests y algo más de errores
                    if is_bot and rng.random() < 0.05:
                        status = rng.choice([429, 403, 500])
                    else:
                        status = 200 if rng.random() < 0.98 else rng.choice([404, 500])

                    base_latency = rng.uniform(20, 250)
                    if et in ["begin_checkout", "purchase"]:
                        base_latency *= rng.uniform(1.2, 2.2)
                    if status >= 400:
                        base_latency *= rng.uniform(0.8, 1.6)

                    se = build_server_event(
                        student_id=args.student_id,
                        ts=t + timedelta(milliseconds=rng.randint(5, 80)),
                        session_id=session_id,
                        request_path=page,
                        method="GET",
                        status_code=status,
                        latency_ms=round(base_latency, 2),
                        ip=ip,
                        user_agent=ua,
                        query=(f"utm_campaign={utm}" if (utm and et in ["page_view", "view_event_list"]) else "")
                    )
                    write_line(f, se)
                    total_written += 1

                # avanza tiempo dentro de sesión
                t = t + timedelta(seconds=rng.randint(2, 45))

            # clicks extra (ruido)
            for _ in range(extra_clicks):
                if total_written >= args.n_events:
                    break
                t = t + timedelta(seconds=rng.randint(1, 20))
                # click normalmente en list/detail
                page = rng.choice(["/events.html", "/event_detail.html"])
                clicked_event_id = event_id if page == "/event_detail.html" else None
                ev = build_client_event(
                    student_id=args.student_id,
                    ts=t,
                    session_id=session_id,
                    event_type="click",
                    page=page,
                    event_id=clicked_event_id,
                    utm_campaign=utm,
                    referrer=ref,
                    action="click",
                    element_id=rng.choice(["btn-checkout", "link-detail", "nav-events", "nav-home"]),
                    amount=None,
                    ip=ip,
                    user_agent=ua
                )
                write_line(f, ev)
                total_written += 1

        f.flush()

    print("✅ Replay completado")
    print(f" - student_id: {args.student_id}")
    print(f" - seed: {seed}")
    print(f" - days: {args.days} (start: {start_day.date().isoformat()})")
    print(f" - out: {args.out} (mode={'append' if args.append else 'overwrite'})")
    print(f" - include_server: {args.include_server}")
    print(f" - total_events_written: {total_written}")
    print(f" - approx_sessions: {sessions}")


if __name__ == "__main__":
    main()