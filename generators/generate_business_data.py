#!/usr/bin/env python3
# generators/generate_business_data.py
"""
Genera datasets de negocio para el caso Aurora Tickets:
- events.csv (catálogo de eventos) + events.json (para la web)
- campaigns.csv (campañas UTM)
- transactions.csv (compras) con session_id para unir con clickstream

Incluye "errores intencionados" controlados (nulos, outliers, ids huérfanos, tipos raros...).
La web debe mostrar SOLO eventos activos/válidos => events.json se genera desde un subconjunto limpio.

Uso típico:
python3 generators/generate_business_data.py \
  --student-id alu01 \
  --seed 123 \
  --days 7 \
  --n-events 120 \
  --n-campaigns 12 \
  --n-transactions 20000 \
  --error-rate 0.05 \
  --orphan-rate 0.02 \
  --out-dir ./output_business \
  --frontend-data-dir ./webapp/frontend/data
"""

import argparse
import csv
import json
import os
import random
import string
from datetime import datetime, timedelta, timezone
from hashlib import sha256


CITIES = ["Madrid", "Barcelona", "Valencia", "Sevilla", "Bilbao", "Zaragoza", "Málaga", "Murcia", "Valladolid", "Alicante"]
CATEGORIES = ["music", "theatre", "festival", "comedy", "sports", "talks"]
CHANNELS = ["search", "social", "display", "email", "affiliate", "direct"]
PAYMENT_METHODS = ["card", "bizum", "transfer", "cash"]


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def parse_args():
    ap = argparse.ArgumentParser(description="Aurora Tickets - Business data generator (CSV + events.json)")
    ap.add_argument("--student-id", required=True, help="Identificador del alumno (se usa para personalizar datos)")
    ap.add_argument("--seed", type=int, default=None, help="Semilla RNG (si no se indica se deriva de student-id)")
    ap.add_argument("--days", type=int, default=7, help="Número de días simulados (por defecto 7)")
    ap.add_argument("--start-date", default=None, help="Fecha inicio (YYYY-MM-DD). Si no, se usa hoy-(days-1)")
    ap.add_argument("--n-events", type=int, default=120, help="Número de eventos a generar")
    ap.add_argument("--n-campaigns", type=int, default=12, help="Número de campañas a generar")
    ap.add_argument("--n-transactions", type=int, default=20000, help="Número de transacciones a generar")
    ap.add_argument("--error-rate", type=float, default=0.05, help="Porcentaje de filas con errores (0.0-0.3 recomendado)")
    ap.add_argument("--orphan-rate", type=float, default=0.02, help="Porcentaje de transacciones con event_id huérfano")
    ap.add_argument("--out-dir", default="./output_business", help="Directorio de salida para CSV")
    ap.add_argument("--frontend-data-dir", default=None, help="Directorio frontend/data para escribir events.json")
    return ap.parse_args()


def derive_seed(student_id: str) -> int:
    h = sha256(student_id.encode("utf-8")).hexdigest()
    # Coge un trozo del hash para una semilla estable
    return int(h[:8], 16)


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def rand_word(rng: random.Random, n=6):
    letters = string.ascii_lowercase
    return "".join(rng.choice(letters) for _ in range(n))


def rand_event_name(rng: random.Random, category: str):
    if category == "music":
        return f"Aurora Live: {rng.choice(['Noche', 'Sesión', 'Show'])} {rng.choice(['Electrónica', 'Indie', 'Rock', 'Pop'])}"
    if category == "theatre":
        return f"Teatro: {rng.choice(['Sombras', 'Ecos', 'Luces'])} de {rng.choice(['Invierno', 'Otoño', 'Cristal', 'Fuego'])}"
    if category == "festival":
        return f"Festival Aurora: Día {rng.randint(1,3)}"
    if category == "comedy":
        return f"Comedy Night: {rng.choice(['Monólogos', 'Stand-up', 'Humor'])} & Más"
    if category == "sports":
        return f"Sports Live: {rng.choice(['Final', 'Derbi', 'Exhibición'])} {rng.choice(['Indoor', 'Arena', 'Open'])}"
    return f"Talks: {rng.choice(['Tech', 'Cultura', 'Ciencia'])} {rng.choice(['2026', 'Series', 'Insights'])}"


def rand_description(rng: random.Random):
    return rng.choice([
        "Aforo limitado. Apertura de puertas 20:00.",
        "Evento al aire libre. Recomendado llegar con antelación.",
        "Duración aproximada 90 minutos. Sin descanso.",
        "Incluye acceso general. Zonas premium disponibles.",
        "Recomendado +16. Humor y sorpresas."
    ])


def pick_base_price(rng: random.Random, category: str):
    base = {
        "music": (18, 45),
        "theatre": (15, 35),
        "festival": (35, 85),
        "comedy": (12, 28),
        "sports": (20, 60),
        "talks": (10, 25),
    }[category]
    return round(rng.uniform(base[0], base[1]), 2)


def daterange(start_date: datetime, days: int):
    for i in range(days):
        yield (start_date + timedelta(days=i))


def random_date_in_range(rng: random.Random, start_date: datetime, days: int):
    d = start_date + timedelta(days=rng.randint(0, days - 1))
    # añade hora dentro del día para timestamp
    hour = rng.randint(0, 23)
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    return d.replace(hour=hour, minute=minute, second=second, tzinfo=timezone.utc)


def make_session_id(rng: random.Random):
    # similar a lo que haría el front (pero no tiene por qué ser idéntico)
    token = "".join(rng.choice("0123456789abcdef") for _ in range(10))
    return f"sess_{token}_{rng.randint(100000,999999)}"


def maybe_null(rng: random.Random, value, p: float):
    return None if rng.random() < p else value


def inject_errors_in_event_row(rng: random.Random, row: dict, error_rate: float):
    """
    Introduce errores típicos sin romper el subconjunto 'activo/válido' que exportamos a events.json.
    Ojo: el subconjunto válido lo controlamos con is_active + validación posterior.
    """
    if rng.random() >= error_rate:
        return row

    # Elige un tipo de error
    err_type = rng.choice(["null_city", "null_category", "bad_price", "bad_date", "weird_types", "duplicate_name"])
    if err_type == "null_city":
        row["city"] = ""
    elif err_type == "null_category":
        row["category"] = ""
    elif err_type == "bad_price":
        # precio como texto o negativo
        row["base_price"] = rng.choice(["free", "-12.5", "999999"])
    elif err_type == "bad_date":
        # fecha con formato raro
        row["event_date"] = rng.choice(["2026/04/10", "10-04-2026", "not-a-date"])
    elif err_type == "weird_types":
        # mezcla de tipos: capacidad string, etc.
        row["capacity"] = rng.choice(["one thousand", "N/A", ""])
    elif err_type == "duplicate_name":
        row["name"] = "Aurora Live: Noche Electrónica"  # fuerza colisiones de nombre
    return row


def inject_errors_in_campaign_row(rng: random.Random, row: dict, error_rate: float):
    if rng.random() >= error_rate:
        return row
    err_type = rng.choice(["null_channel", "bad_cost", "empty_utm"])
    if err_type == "null_channel":
        row["channel"] = ""
    elif err_type == "bad_cost":
        row["monthly_cost"] = rng.choice(["-50", "unknown", "1000000"])
    elif err_type == "empty_utm":
        row["utm_campaign"] = ""
    return row


def inject_errors_in_transaction_row(rng: random.Random, row: dict, error_rate: float, orphan_event_ids: list):
    if rng.random() >= error_rate:
        return row
    err_type = rng.choice(["null_amount", "bad_amount", "bad_timestamp", "orphan_event", "bad_payment", "duplicate_id"])
    if err_type == "null_amount":
        row["amount"] = ""
    elif err_type == "bad_amount":
        row["amount"] = rng.choice(["-9.99", "NaN", "9999999"])
    elif err_type == "bad_timestamp":
        row["timestamp"] = rng.choice(["not-a-ts", "2026/02/01 10:00:00", ""])
    elif err_type == "orphan_event":
        row["event_id"] = rng.choice(orphan_event_ids) if orphan_event_ids else 999999
    elif err_type == "bad_payment":
        row["payment_method"] = rng.choice(["paypal", "crypto", ""])  # fuera del dominio esperado
    elif err_type == "duplicate_id":
        # Deja transaction_id vacío para causar problema o dup
        row["transaction_id"] = ""
    return row


def write_csv(path: str, rows: list, fieldnames: list):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fieldnames})


def main():
    args = parse_args()
    seed = args.seed if args.seed is not None else derive_seed(args.student_id)
    rng = random.Random(seed)

    # Fechas
    if args.start_date:
        start = datetime.fromisoformat(args.start_date).replace(tzinfo=timezone.utc)
    else:
        today = datetime.now(timezone.utc).date()
        start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) - timedelta(days=args.days - 1)

    out_dir = args.out_dir
    ensure_dir(out_dir)

    # -------------------------
    # 1) EVENTS (catalog)
    # -------------------------
    # Generamos IDs estables por alumno: base + índice
    base_id = int(sha256(args.student_id.encode("utf-8")).hexdigest()[:4], 16) * 1000

    events = []
    for i in range(args.n_events):
        category = rng.choice(CATEGORIES)
        ev_id = base_id + i + 1
        ev_city = rng.choice(CITIES)
        ev_date = (start + timedelta(days=rng.randint(7, 120))).date().isoformat()  # evento futuro
        base_price = pick_base_price(rng, category)
        cap = rng.randint(150, 5000)

        row = {
            "event_id": ev_id,
            "name": rand_event_name(rng, category),
            "city": ev_city,
            "category": category,
            "event_date": ev_date,
            "base_price": base_price,
            "capacity": cap,
            "is_active": 1,  # los activos son los que pueden salir en la web
            "description": rand_description(rng),
            "created_at": iso_now()
        }

        # Introducimos errores controlados en algunos registros
        row = inject_errors_in_event_row(rng, row, args.error_rate)

        # También podemos inactivar algunos eventos (para que existan pero no se muestren)
        if rng.random() < 0.08:
            row["is_active"] = 0

        events.append(row)

    event_fields = ["event_id", "name", "city", "category", "event_date", "base_price", "capacity", "is_active", "description", "created_at"]
    events_csv_path = os.path.join(out_dir, "events.csv")
    write_csv(events_csv_path, events, event_fields)

    # Creamos un subconjunto "válido" para la web
    def is_event_valid_for_web(e: dict) -> bool:
        try:
            # Requisitos mínimos: activo + campos esenciales no vacíos + precio numérico
            if str(e.get("is_active", "0")) != "1":
                return False
            if not str(e.get("name", "")).strip():
                return False
            if not str(e.get("city", "")).strip():
                return False
            if not str(e.get("category", "")).strip():
                return False
            if not str(e.get("event_date", "")).strip():
                return False
            # precio debe poder parsearse a float y ser razonable
            float(str(e.get("base_price", "0")))
            return True
        except Exception:
            return False

    valid_events_for_web = [e for e in events if is_event_valid_for_web(e)]
    # Si por error rate se queda muy vacío, aseguramos al menos 10
    if len(valid_events_for_web) < 10:
        # Fuerza los primeros 10 como activos y válidos mínimamente
        valid_events_for_web = []
        for e in events[:10]:
            e["is_active"] = 1
            if not str(e.get("city", "")).strip():
                e["city"] = rng.choice(CITIES)
            if not str(e.get("category", "")).strip():
                e["category"] = rng.choice(CATEGORIES)
            if not str(e.get("event_date", "")).strip():
                e["event_date"] = (start + timedelta(days=30)).date().isoformat()
            # base_price forzable
            try:
                float(str(e.get("base_price", "0")))
            except Exception:
                e["base_price"] = 19.99
            valid_events_for_web.append(e)

    # events.json para la web (solo con válidos)
    events_json_obj = {
        "generated_at": iso_now(),
        "student_id": args.student_id,
        "seed": seed,
        "events": [
            {
                "event_id": int(e["event_id"]),
                "name": e["name"],
                "city": e["city"],
                "category": e["category"],
                "event_date": e["event_date"],
                "base_price": float(str(e["base_price"])),
                "description": e.get("description", "")
            }
            for e in valid_events_for_web
        ]
    }

    if args.frontend_data_dir:
        ensure_dir(args.frontend_data_dir)
        events_json_path = os.path.join(args.frontend_data_dir, "events.json")
    else:
        events_json_path = os.path.join(out_dir, "events.json")

    with open(events_json_path, "w", encoding="utf-8") as f:
        json.dump(events_json_obj, f, ensure_ascii=False, indent=2)

    # -------------------------
    # 2) CAMPAIGNS
    # -------------------------
    campaigns = []
    # Crea campañas UTM "humanas"
    base_names = ["spring_sale", "summer_push", "autumn_nights", "blackweek", "new_year", "city_launch", "retargeting", "vip", "student", "family"]
    rng.shuffle(base_names)
    for i in range(args.n_campaigns):
        utm = base_names[i % len(base_names)]
        # Personaliza por alumno con sufijo corto
        suffix = sha256(f"{args.student_id}-{i}".encode("utf-8")).hexdigest()[:4]
        utm_campaign = f"{utm}_{suffix}"

        row = {
            "campaign_id": i + 1,
            "utm_campaign": utm_campaign,
            "channel": rng.choice(CHANNELS),
            "monthly_cost": round(rng.uniform(80, 2000), 2),
            "start_dt": start.date().isoformat(),
            "end_dt": (start + timedelta(days=args.days - 1)).date().isoformat(),
            "created_at": iso_now()
        }
        row = inject_errors_in_campaign_row(rng, row, args.error_rate)
        campaigns.append(row)

    campaigns_fields = ["campaign_id", "utm_campaign", "channel", "monthly_cost", "start_dt", "end_dt", "created_at"]
    campaigns_csv_path = os.path.join(out_dir, "campaigns.csv")
    write_csv(campaigns_csv_path, campaigns, campaigns_fields)

    # Lista de campañas válidas (para asignar a compras)
    valid_campaigns = [c["utm_campaign"] for c in campaigns if str(c.get("utm_campaign", "")).strip()]

    # -------------------------
    # 3) TRANSACTIONS (compras)
    # -------------------------
    # Construimos universo de event_ids válidos para compras reales
    valid_event_ids = [int(e["event_id"]) for e in valid_events_for_web]
    # También construimos event_ids huérfanos para errores
    orphan_event_ids = [base_id + args.n_events + 100 + i for i in range(30)]

    transactions = []
    for i in range(args.n_transactions):
        ts = random_date_in_range(rng, start, args.days)  # dentro de la semana simulada
        dt = ts.date().isoformat()

        event_id = rng.choice(valid_event_ids) if valid_event_ids else base_id + 1

        # Orphan (huérfano) controlado
        if rng.random() < args.orphan_rate:
            event_id = rng.choice(orphan_event_ids)

        session_id = make_session_id(rng)

        # amount razonable basado en catálogo si el event está en el universo, si no: aleatorio
        # (en curated se detectan outliers/negativos/strings etc.)
        if event_id in valid_event_ids:
            # Busca base_price del evento
            ev = next((e for e in valid_events_for_web if int(e["event_id"]) == event_id), None)
            base_price = float(str(ev["base_price"])) if ev else rng.uniform(10, 40)
            quantity = 1 if rng.random() < 0.92 else 2
            amount = round(base_price * quantity, 2)
        else:
            quantity = 1
            amount = round(rng.uniform(5, 120), 2)

        # campaña: algunas compras sin campaña (direct)
        utm_campaign = rng.choice(valid_campaigns) if (valid_campaigns and rng.random() < 0.65) else ""

        row = {
            "transaction_id": f"tx_{args.student_id}_{i+1}",
            "timestamp": ts.isoformat(),
            "dt": dt,
            "session_id": session_id,
            "event_id": event_id,
            "quantity": quantity,
            "amount": amount,
            "payment_method": rng.choice(PAYMENT_METHODS),
            "utm_campaign": utm_campaign,
            "created_at": iso_now()
        }

        # Inyecta errores intencionados
        row = inject_errors_in_transaction_row(rng, row, args.error_rate, orphan_event_ids)
        transactions.append(row)

    transactions_fields = ["transaction_id", "timestamp", "dt", "session_id", "event_id", "quantity", "amount", "payment_method", "utm_campaign", "created_at"]
    transactions_csv_path = os.path.join(out_dir, "transactions.csv")
    write_csv(transactions_csv_path, transactions, transactions_fields)

    # Resumen
    print("✅ Generación completada")
    print(f" - student_id: {args.student_id}")
    print(f" - seed: {seed}")
    print(f" - days: {args.days} (start: {start.date().isoformat()})")
    print(f" - events.csv: {events_csv_path} (total={len(events)})")
    print(f" - campaigns.csv: {campaigns_csv_path} (total={len(campaigns)})")
    print(f" - transactions.csv: {transactions_csv_path} (total={len(transactions)})")
    print(f" - events.json (web): {events_json_path} (active_valid={len(valid_events_for_web)})")
    print("ℹ️ Nota: events.json contiene SOLO eventos activos/válidos (subconjunto consistente con events.csv).")


if __name__ == "__main__":
    main()