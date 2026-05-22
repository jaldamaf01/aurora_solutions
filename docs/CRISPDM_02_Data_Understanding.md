# CRISP-DM 02 - Data Understanding

## Fuentes

- Clickstream JSON Lines generado por la web FastAPI y por replay masivo.
- `events.csv`: catalogo de eventos.
- `campaigns.csv`: campanas UTM.
- `transactions.csv`: compras simuladas.

## Claves de union

- `clickstream.event_id` con `events.event_id`.
- `clickstream.utm_campaign` con `campaigns.utm_campaign`.
- `transactions.session_id` y `transactions.event_id` con clickstream cuando aplica.

## Campos principales de clickstream

- `student_id`, `timestamp`, `dt`, `session_id`.
- `event_type`: `page_view`, `view_event_list`, `view_event_detail`, `begin_checkout`, `purchase`, `click`, `server_request`.
- `event_id`, `utm_campaign`, `amount`.
- `status_code`, `latency_ms`, `request_path`, `ip`.

## Calidad esperada

Los CSV incluyen ruido intencionado: nulos, precios invalidos, importes extremos, ids huerfanos, fechas fuera de formato y valores de dominio incorrectos. La limpieza se realiza en el Job 1.
