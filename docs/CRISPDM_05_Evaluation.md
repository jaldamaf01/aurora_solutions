# CRISP-DM 05 - Evaluation

## Validaciones

- `sessions_purchase <= sessions_begin_checkout <= sessions_event_detail <= sessions_total`.
- `conversion_rate` entre 0 y 1.
- Datasets `curated` y `analytics` en Parquet.
- Particionado por `dt` y una segunda dimension.
- RDS contiene solo tablas finales de metricas.
- CloudWatch recibe eventos en el log group del alumno.

## Limitaciones

- Los datos son simulados, por lo que las conclusiones son tecnicas y de negocio aproximadas.
- El volumen de 200k eventos es suficiente para demostrar la pipeline, pero no representa carga real de produccion.
- La deteccion de anomalias usa reglas transparentes por umbral; en produccion se podria evolucionar a modelos estadisticos por ventana.

## Resultado esperado

La solucion cumple los criterios de apto: 6 EC2, Spark con 3 workers, logs CloudWatch, 4 queries, dashboard, S3 por capas, 2 jobs Spark y RDS con 3 tablas finales.
