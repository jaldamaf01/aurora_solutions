# Generador de datos de negocio — Aurora Tickets

Este generador produce los datasets de negocio (CSV) y el catálogo para la web (events.json), tendrás que añadir este archivo en la web, en el apartado de frontend/data.
con "errores intencionados" para que puedas aplicar limpieza en la fase **Data Preparation** (CRISP-DM).

## Archivos generados

- `events.csv` → catálogo de eventos (dimensión)
- `campaigns.csv` → campañas UTM y canal (dimensión)
- `transactions.csv` → compras (hechos) con `session_id` (clave de unión con clickstream)
- `events.json` → catálogo para el front (subconjunto válido de `events.csv`)

## Consistencia Web ↔ CSV

La web muestra eventos desde `events.json`.

✅ `events.json` se genera a partir de un subconjunto de `events.csv`:

- solo eventos con `is_active=1`
- y con campos esenciales válidos (`event_id`, `name`, `city`, `category`, `event_date`, `base_price`)

Esto garantiza que:

- TODO lo que aparece en la web tiene una fila correspondiente en `events.csv` (**consistente**)
- `events.csv` puede contener filas “sucias” adicionales para practicar limpieza (nulos, tipos raros, etc.)

## Relación con clickstream (claves)

Los análisis unen datasets mediante:

- `event_id`: clickstream ↔ events.csv ↔ transactions.csv
- `utm_campaign`: clickstream ↔ campaigns.csv (atribución)
- `session_id`: clickstream ↔ transactions.csv (funnel por sesión)

> `transactions.csv` incluye `session_id` por diseño para que el join sea simple y robusto.

---

## Esquemas (columnas)

### events.csv

- `event_id` (int) PK
- `name` (string)
- `city` (string)
- `category` (string)
- `event_date` (string fecha)
- `base_price` (decimal o a veces “sucio”)
- `capacity` (int o a veces “sucio”)
- `is_active` (0/1)
- `description` (string)
- `created_at` (ISO timestamp)

### campaigns.csv

- `campaign_id` (int) PK
- `utm_campaign` (string) clave de unión
- `channel` (string)
- `monthly_cost` (decimal o a veces “sucio”)
- `start_dt` (date)
- `end_dt` (date)
- `created_at` (ISO timestamp)

### transactions.csv

- `transaction_id` (string) PK (puede venir vacío como error intencionado)
- `timestamp` (ISO timestamp; puede venir mal formateado como error)
- `dt` (YYYY-MM-DD)
- `session_id` (string) clave para unir con clickstream
- `event_id` (int) (a veces huérfano como error)
- `quantity` (int)
- `amount` (decimal o “sucio”/outlier/negativo como error)
- `payment_method` (string; a veces fuera del dominio como error)
- `utm_campaign` (string; puede venir vacío para tráfico “direct”)
- `created_at` (ISO timestamp)

---

## Errores intencionados (Data Preparation)

El generador puede introducir:

- nulos / vacíos en city/category/channel/amount
- formatos de fecha incorrectos (`event_date` o `timestamp`)
- tipos incorrectos (`base_price` como texto, capacity como “N/A”)
- outliers (`amount` enorme o negativo)
- IDs huérfanos (transactions con `event_id` no existente en eventos válidos)
- pagos fuera del dominio (`paypal`, `crypto`, etc.)

Estos errores deben tratarse en Spark (Job 1) al generar `curated/`.

---

## Uso

Ejemplo recomendado:

```bash
python3 generators/generate_business_data.py \
  --student-id alu01 \
  --days 7 \
  --n-events 120 \
  --n-campaigns 12 \
  --n-transactions 20000 \
  --error-rate 0.05 \
  --orphan-rate 0.02 \
  --out-dir ./output_business \
  --frontend-data-dir ./webapp/frontend/data
```
