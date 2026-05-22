# CRISP-DM 04 - Modeling

## Arquitectura

```mermaid
flowchart LR
  Web["EC2 Web + FastAPI"] --> CW["CloudWatch Logs"]
  Web --> Raw["S3 raw"]
  Raw --> Job1["Spark Job 1"]
  Job1 --> Curated["S3 curated parquet"]
  Curated --> Job2["Spark Job 2"]
  Job2 --> Analytics["S3 analytics parquet"]
  Job2 --> RDS["RDS MySQL"]
  CW --> Dash["CloudWatch Dashboard"]
```

## Cluster Spark

- EC2-1: Spark Master.
- EC2-2, EC2-3, EC2-4: Spark Workers.
- EC2-5: Submit node.
- EC2-6: Web + FastAPI + CloudWatch Agent.

## Productos analiticos

Producto A: funnel diario.

- `sessions_total`
- `sessions_event_list`
- `sessions_event_detail`
- `sessions_begin_checkout`
- `sessions_purchase`
- `conversion_rate`

Producto B: interes vs ingresos.

- `detail_views`
- `purchases`
- `revenue_total`
- `interest_to_purchase_ratio`

Producto C: anomalias.

- Regla por umbrales verificables: requests altos, errores altos, latencia alta o IP repetitiva.
- Salida con `is_anomaly` y `reason`.
