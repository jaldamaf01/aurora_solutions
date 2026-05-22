#!/usr/bin/env python3
# simulators/traffic_driver.py
"""
Genera tráfico real automatizado contra el backend (via Nginx/80):
- Envía POST /track con eventos client-side (simulados)
- El middleware del backend generará eventos server-side automáticamente en JSONL

Uso típico:
  python3 simulators/traffic_driver.py \
    --base-url http://<PUBLIC_IP> \
    --student-id alu01 \
    --events-json ./webapp/frontend/data/events.json \
    --campaigns-csv ./output_business/campaigns.csv \
    --sessions 300 \
    --max-actions 8 \
    --sleep-ms 80
"""

import argparse
import json
import random
import time
import csv
from datetime import datetime, timezone, timedelta
from hashlib import sha256

import requests


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
]

def parse_args():
    ap = argparse.ArgumentParser(description="Aurora traffic driver (real POST /track)")
    ap.add_argument("--base-url", required=True, help="Ej: http://1.2.3.4 (puerto 80)")
    ap.add_argument("--student-id", required=True)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--events-json", required=True)
    ap.add_argument("--campaigns-csv", required=True)
    ap.add_argument("--sessions", type=int, default=300, help="Número de sesiones a simular")
    ap.add_argument("--max-actions", type=int, default=8, help="Acciones máximas por sesión")
    ap.add_argument("--sleep-ms", type=int, default=80, help="Pausa entre acciones (ms)")
    ap.add_argument("--timeout", type=int, default=5)
    return ap.parse_args()

def derive_seed(student_id: str) -> int:
    h = sha256(student_id.encode("utf-8")).hexdigest()
    return int(h[:8], 16)

def iso_now():
    return datetime.now(timezone.utc).isoformat()

def dt_now():
    return datetime.now(timezone.utc).date().isoformat()

def load_events(path):
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    evs = obj.get("events", [])
    if not evs:
        raise ValueError("events.json sin eventos")
    cleaned = []
    for e in evs:
        cleaned.append({"event_id": int(e["event_id"]), "base_price": float(e.get("base_price", 20.0))})
    return cleaned

def load_campaigns(path):
    camps = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            utm = (r.get("utm_campaign") or "").strip()
            if utm:
                camps.append(utm)
    return camps if camps else [None]

def make_session_id(rng):
    token = "".join(rng.choice("0123456789abcdef") for _ in range(10))
    return f"sess_{token}_{rng.randint(100000,999999)}"

def choose_campaign(rng, camps):
    return rng.choice(camps) if rng.random() < 0.6 else None

def post_track(sess, base_url, payload, timeout):
    url = base_url.rstrip("/") + "/track"
    r = sess.post(url, json=payload, timeout=timeout)
    return r.status_code

def main():
    args = parse_args()
    seed = args.seed if args.seed is not None else derive_seed(args.student_id)
    rng = random.Random(seed)

    events = load_events(args.events_json)
    campaigns = load_campaigns(args.campaigns_csv)

    s = requests.Session()

    total_posts = 0
    total_ok = 0

    for _ in range(args.sessions):
        session_id = make_session_id(rng)
        ua = rng.choice(USER_AGENTS)
        utm = choose_campaign(rng, campaigns)

        headers = {"User-Agent": ua}
        # Nota: el backend cogerá ip real; aquí no la controlamos.

        # Secuencia simple de funnel realista
        chosen = rng.choice(events)
        event_id = chosen["event_id"]
        amount = chosen["base_price"]

        actions = [
            ("page_view", "/", None),
            ("view_event_list", "/events.html", None),
            ("view_event_detail", "/event_detail.html", event_id),
            ("begin_checkout", "/checkout.html", event_id),
        ]

        # Compra con cierta probabilidad
        if rng.random() < 0.50:
            actions.append(("purchase", "/purchase_ok.html", event_id))

        # clicks extra
        extra = rng.randint(0, max(0, args.max_actions - len(actions)))
        for _e in range(extra):
            actions.insert(rng.randint(1, len(actions)), ("click", rng.choice(["/events.html", "/event_detail.html"]), event_id if rng.random() < 0.5 else None))

        for (event_type, page, ev_id) in actions[:args.max_actions]:
            payload = {
                "student_id": args.student_id,
                "timestamp": iso_now(),
                "dt": dt_now(),
                "session_id": session_id,
                "event_type": event_type,
                "source": "client",
                "page": page,
                "action": event_type,
                "element_id": rng.choice(["btn-checkout", "link-detail", "nav-events", "nav-home"]) if event_type == "click" else None,
                "event_id": ev_id,
                "utm_campaign": utm,
                "referrer": rng.choice(["https://google.com", "https://instagram.com", None]),
                "amount": (amount if event_type == "purchase" else None),
            }

            try:
                status = post_track(s, args.base_url, payload, args.timeout)
                total_posts += 1
                if 200 <= status < 300:
                    total_ok += 1
            except Exception:
                total_posts += 1

            # pequeña pausa
            time.sleep(args.sleep_ms / 1000.0)

    print("✅ Traffic driver terminado")
    print(f" - base_url: {args.base_url}")
    print(f" - student_id: {args.student_id}")
    print(f" - seed: {seed}")
    print(f" - sessions: {args.sessions}")
    print(f" - total_posts: {total_posts}")
    print(f" - ok_posts: {total_ok}")
    print("ℹ️ Cada POST /track suele generar 2 líneas en JSONL (server_request + client event).")


if __name__ == "__main__":
    main()