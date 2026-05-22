# Aurora Tickets - entrega reproducible

Student ID usado: `juana`

Region AWS: `us-east-1`

Servicios desplegados:

- 6 EC2 con roles separados: Spark master, 3 Spark workers, submit node y web.
- S3 con prefijo `aurora/juana/` y capas `raw`, `curated`, `analytics`.
- RDS MySQL con tablas finales de metricas.
- CloudWatch Logs con log group `/aurora/juana/clickstream`.
- CloudWatch Dashboard `aurora-dashboard-juana`.
- 4 queries guardadas de Logs Insights.

## Estructura anadida

- `aurora_solution/deploy_aws.py`: despliegue idempotente de infraestructura y artefactos.
- `aurora_solution/remote/bootstrap.sh`: provisionado automatizado de cada EC2 por rol.
- `aurora_solution/webapp`: copia local autocontenida de la aplicacion web usada en el bundle.
- `aurora_solution/generators`: copia local autocontenida de los generadores de datos de negocio.
- `aurora_solution/simulators`: copia local autocontenida de los simuladores de trafico y replay.
- `aurora_solution/spark/job1_curate.py`: curacion raw -> curated.
- `aurora_solution/spark/job2_analytics.py`: analitica curated -> analytics + RDS.
- `aurora_solution/docs/CRISPDM_*.md`: documentacion por fases.

## Ejecucion

El despliegue se lanza desde la raiz del repo con credenciales temporales AWS en entorno:

```bash
python aurora_solution/deploy_aws.py --student-id juana --region us-east-1
```

El script empaqueta la web/generadores/simuladores, sube el bundle a S3, crea los recursos AWS y arranca las EC2 con user-data. No requiere instalacion manual maquina por maquina.

## Salidas esperadas

S3:

- `s3://aurora-369764304576-juana-20260508/aurora/juana/raw/`
- `s3://aurora-369764304576-juana-20260508/aurora/juana/curated/`
- `s3://aurora-369764304576-juana-20260508/aurora/juana/analytics/`
- `s3://aurora-369764304576-juana-20260508/aurora/juana/evidence/`

RDS MySQL:

- `metrics_funnel_daily`
- `metrics_event_rank`
- `metrics_anomalies`

CloudWatch:

- Log group: `/aurora/juana/clickstream`
- Dashboard: `aurora-dashboard-juana`
- Queries: `aurora_q1_funnel_daily`, `aurora_q2_top_events_interest_vs_revenue`, `aurora_q3_errors_and_latency`, `aurora_q4_anomalies_suspected_bots`

## Comprobaciones

- La web responde en `http://<web_public_ip>/health`.
- Spark UI responde en `http://<spark_master_public_ip>:8080` y debe mostrar 3 workers vivos.
- El objeto `status/spark_jobs_done.txt` en S3 confirma que los dos `spark-submit` terminaron.
- Los logs de submit quedan en `evidence/spark-submit-job1.log` y `evidence/spark-submit-job2.log`.
