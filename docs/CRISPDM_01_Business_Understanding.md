# CRISP-DM 01 - Business Understanding

## Contexto

Aurora Tickets vende entradas para conciertos, teatro, festivales y otros eventos. La direccion detecta mucho trafico web, baja conversion, picos de lentitud y patrones sospechosos de automatizacion.

## Objetivos de negocio

- Medir el funnel diario de navegacion: listado, detalle, checkout y compra.
- Identificar eventos con mucho interes y baja compra.
- Detectar trafico anomalo por IP, endpoint y comportamiento repetitivo.
- Publicar metricas finales en RDS para consumo operativo.
- Mantener observabilidad en CloudWatch para consultas rapidas.

## KPIs

- `conversion_rate`: sesiones con compra / sesiones totales.
- `interest_to_purchase_ratio`: vistas de detalle / compras.
- `revenue_total`: ingresos por evento y dia.
- `requests`, `errors`, `avg_latency_ms`: salud de la web.
- `is_anomaly`: indicador operativo de trafico sospechoso.

## Decisiones soportadas

- Priorizar eventos con alto interes y baja conversion.
- Ajustar campanas UTM con ingresos reales.
- Revisar endpoints lentos o con errores.
- Bloquear o investigar IPs repetitivas.
