#!/usr/bin/env bash
set -euo pipefail

STUDENT_ID="${1:?student id}"
BUCKET="${2:?bucket}"
PREFIX="${3:?prefix}"
REGION="${4:?region}"
MASTER_PRIVATE="${5:?master private ip}"
RDS_HOST="${6:?rds host}"
RDS_DB="${7:?rds db}"
RDS_USER="${8:?rds user}"
RDS_PASSWORD="${9:?rds password}"

export AWS_DEFAULT_REGION="${REGION}"
export PYSPARK_DRIVER_PYTHON=/opt/aurora/pyenv/bin/python
export PYSPARK_PYTHON=python3

LOG1=/opt/aurora/spark-submit-job1-retry.log
LOG2=/opt/aurora/spark-submit-job2-retry.log

/opt/aurora/pyenv/bin/pip install --quiet PyMySQL cryptography

aws s3 rm "s3://${BUCKET}/${PREFIX}/curated/" --recursive || true
aws s3 rm "s3://${BUCKET}/${PREFIX}/analytics/" --recursive || true

s3_conf=(
  --packages org.apache.hadoop:hadoop-aws:3.3.4,com.amazonaws:aws-java-sdk-bundle:1.12.262
  --conf spark.hadoop.fs.s3a.impl=org.apache.hadoop.fs.s3a.S3AFileSystem
  --conf spark.hadoop.fs.s3a.aws.credentials.provider=com.amazonaws.auth.InstanceProfileCredentialsProvider
  --conf spark.executor.memory=512m
  --conf spark.driver.memory=512m
  --conf spark.executor.cores=1
  --conf spark.executor.heartbeatInterval=30s
  --conf spark.network.timeout=600s
)

/opt/spark/bin/spark-submit \
  --master "spark://${MASTER_PRIVATE}:7077" \
  "${s3_conf[@]}" \
  /opt/aurora/app/spark/job1_curate.py \
  --bucket "${BUCKET}" \
  --prefix "${PREFIX}" \
  --student-id "${STUDENT_ID}" \
  > "${LOG1}" 2>&1

aws s3 cp "${LOG1}" "s3://${BUCKET}/${PREFIX}/evidence/spark-submit-job1.log"

/opt/spark/bin/spark-submit \
  --master "spark://${MASTER_PRIVATE}:7077" \
  "${s3_conf[@]}" \
  /opt/aurora/app/spark/job2_analytics.py \
  --bucket "${BUCKET}" \
  --prefix "${PREFIX}" \
  --student-id "${STUDENT_ID}" \
  --rds-host "${RDS_HOST}" \
  --rds-db "${RDS_DB}" \
  --rds-user "${RDS_USER}" \
  --rds-password "${RDS_PASSWORD}" \
  > "${LOG2}" 2>&1

aws s3 cp "${LOG2}" "s3://${BUCKET}/${PREFIX}/evidence/spark-submit-job2.log"
date -u +"%Y-%m-%dT%H:%M:%SZ" >/opt/aurora/status/spark_jobs_done.txt
aws s3 cp /opt/aurora/status/spark_jobs_done.txt "s3://${BUCKET}/${PREFIX}/status/spark_jobs_done.txt"
