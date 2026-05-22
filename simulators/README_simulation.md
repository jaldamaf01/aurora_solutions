# Simulación de Clickstream — Aurora Tickets

Este bloque proporciona dos mecanismos para generar clickstream:

1. **Replay masivo** (`replay_clickstream.py`)
   - Genera gran volumen rápido (>= 200k)
   - Escribe directamente en el fichero JSONL que recoge CloudWatch Agent
   - No requiere tocar FastAPI
   - Útil para volumen y para que Spark tenga “chicha”

2. **Tráfico real automatizado** (`traffic_driver.py`)
   - Envía POST reales a `/track` (vía Nginx/80)
   - El middleware de FastAPI genera logs **server-side reales** automáticamente
   - Útil para tener latencia/status reales en el JSONL (source=server)

---

## Requisitos del proyecto (recordatorio)

- Mínimo **200.000 eventos** en total
- Repartidos en **7 días**
- Mezcla recomendada:
  - 180k–220k por replay
  - 5k–30k por tráfico real (según presupuesto/tiempo)

---

## Archivos de entrada necesarios

- `events.json` (catálogo que usa la web)
- `campaigns.csv` (UTM existentes)

Estos se generan con `generators/generate_business_data.py`.

---

## Replay masivo (orientación)

`replay_clickstream.py` escribe eventos JSONL directamente.

Aspectos clave:

- Incluye `student_id` en cada evento
- Genera `session_id` anónimo
- Reparte timestamps en `days` (por defecto 7)
- Opcional: genera también eventos `source=server` sintéticos (`--include-server 1`)

Recomendación:

- Usar `--append` para no borrar el fichero existente si ya hay tráfico real.

---

## Tráfico real automatizado (orientación)

`traffic_driver.py` manda `POST /track` a la URL del servidor web.

- Requiere que la web esté desplegada y accesible en **HTTP 80**
- Requiere que FastAPI esté detrás de Nginx y el endpoint `/track` funcione
- Cada POST suele producir:
  - 1 evento `source=server` (middleware)
  - 1 evento `source=client` (evento recibido)

Dependencia:

- `pip install requests`

---

## Checklist de validación (sin receta)

- El fichero `/var/log/aurora/aurora_clickstream.jsonl` existe y crece.
- En CloudWatch (Log group `/aurora/<student_id>/clickstream`) aparecen entradas.
- Se observan tanto eventos `source=client` como `source=server` (si has usado tráfico real o include-server).
- Los eventos contienen:
  - `student_id`, `timestamp`, `dt`, `session_id`, `event_type`, `source`

---

## Problemas típicos

1. **No llegan logs a CloudWatch**
   - CloudWatch Agent no está arrancado o no lee el path correcto.
   - Permisos/credenciales del entorno.

2. **El replay no se refleja**
   - Se está escribiendo en un fichero distinto al que lee el agente.
   - El agente está leyendo pero no hay eventos nuevos (prueba append y genera nuevas líneas).

3. **Traffic driver falla**
   - La web no está accesible en HTTP 80.
   - `/track` no responde.
   - Falta instalar `requests`.

---

## Buenas prácticas

- Mantener un único fichero JSONL para simplificar
- Mantener `student_id` consistente (CloudWatch log group, S3 prefix, dashboard)
- Guardar evidencias de conteo aproximado de eventos generados
