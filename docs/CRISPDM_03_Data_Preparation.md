# CRISP-DM 03 - Data Preparation

## Capa raw

La capa `raw/` conserva los datos de aterrizaje:

- `raw/clickstream/aurora_clickstream.jsonl`
- `raw/business/events.csv`
- `raw/business/campaigns.csv`
- `raw/business/transactions.csv`

## Limpieza en Job 1

Clickstream:

- Filtrado por `student_id`.
- Normalizacion de `dt`, `event_ts`, `event_id`, `amount`, `status_code` y `latency_ms`.
- Eliminacion de duplicados basicos.
- Escritura Parquet particionada por `dt` y `event_type`.

Catalogo:

- Cast de `event_id`, `base_price`, `capacity`, `is_active`.
- Eliminacion de nombres, ciudades o categorias vacias.
- Filtrado de precios no validos o extremos.
- Escritura Parquet particionada por `dt` y `category`.

Campanas:

- Validacion de `utm_campaign`.
- Validacion de canal permitido.
- Filtrado de costes negativos o extremos.
- Escritura Parquet particionada por `dt` y `channel`.

Transacciones:

- Validacion de importes, metodo de pago y claves.
- Eliminacion de eventos huerfanos mediante join con catalogo curado.
- Escritura Parquet particionada por `dt` y `payment_method`.
