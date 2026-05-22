# CRISP-DM 06 - Deployment

## Provisionado

El despliegue se automatiza con:

- `aurora_solution/deploy_aws.py`
- `aurora_solution/remote/bootstrap.sh`

Cada EC2 recibe un rol por `user-data`, instala sus dependencias y ejecuta su responsabilidad sin pasos manuales repetitivos por SSH.

## Recursos

- Bucket: `aurora-369764304576-juana-20260508`
- Prefijo: `aurora/juana/`
- Log group: `/aurora/juana/clickstream`
- Dashboard: `aurora-dashboard-juana`
- RDS: `aurora-juana-db`

## Operacion end-to-end

1. Web genera catalogo, CSV de negocio, trafico real y replay masivo.
2. CloudWatch Agent envia `/var/log/aurora/aurora_clickstream.jsonl`.
3. Web sube raw a S3.
4. Submit espera raw y ejecuta `job1_curate.py`.
5. Submit ejecuta `job2_analytics.py`.
6. Job 2 escribe analytics en S3 y metricas finales en RDS.

## Coste estimado

Para una practica corta en AWS Academy:

- 6 EC2 `t3.micro`.
- 1 RDS MySQL `db.t3.micro` con 20 GB.
- S3 con decenas de MB.
- CloudWatch Logs para unos 200k eventos.

El coste se mantiene bajo si los recursos se apagan o eliminan tras la evaluacion.
