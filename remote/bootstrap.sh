#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:?role}"
BUNDLE_URL="${2:?bundle url}"
STUDENT_ID="${3:?student id}"
BUCKET="${4:?bucket}"
PREFIX="${5:?prefix}"
REGION="${6:?region}"
MASTER_PRIVATE="${7:-}"
RDS_HOST="${8:-}"
RDS_DB="${9:-aurora}"
RDS_USER="${10:-auroraadmin}"
RDS_PASSWORD="${11:-}"

export AWS_DEFAULT_REGION="${REGION}"
export DEBIAN_FRONTEND=noninteractive

mkdir -p /opt/aurora /var/log/aurora
exec > >(tee -a /var/log/aurora/bootstrap-${ROLE}.log | logger -t aurora-bootstrap -s 2>/dev/console) 2>&1

echo "Aurora bootstrap role=${ROLE} student=${STUDENT_ID}"

apt_retry() {
  for n in 1 2 3 4 5; do
    if "$@"; then
      return 0
    fi
    echo "retry ${n}: $*"
    sleep 15
  done
  "$@"
}

install_base() {
  apt_retry apt-get update -y
  apt_retry apt-get install -y ca-certificates curl wget unzip python3 python3-pip python3-venv awscli
}

download_bundle() {
  mkdir -p /opt/aurora/app
  curl -fsSL "${BUNDLE_URL}" -o /opt/aurora/aurora_bundle.zip
  unzip -oq /opt/aurora/aurora_bundle.zip -d /opt/aurora/app
}

install_spark() {
  apt_retry apt-get install -y openjdk-11-jdk
  if [ ! -x /opt/spark/bin/spark-submit ]; then
    local spark_version="3.5.3"
    cd /opt
    curl -fL "https://archive.apache.org/dist/spark/spark-${spark_version}/spark-${spark_version}-bin-hadoop3.tgz" -o /tmp/spark.tgz
    tar -xzf /tmp/spark.tgz
    ln -sfn "/opt/spark-${spark_version}-bin-hadoop3" /opt/spark
    chown -R ubuntu:ubuntu "/opt/spark-${spark_version}-bin-hadoop3"
  fi
}

upload_status() {
  local name="$1"
  mkdir -p /opt/aurora/status
  date -u +"%Y-%m-%dT%H:%M:%SZ" > "/opt/aurora/status/${name}.txt"
  aws s3 cp "/opt/aurora/status/${name}.txt" "s3://${BUCKET}/${PREFIX}/status/${name}.txt" || true
}

configure_spark_master() {
  install_spark
  local private_ip
  private_ip="$(hostname -I | awk '{print $1}')"
  cat >/etc/systemd/system/spark-master.service <<EOF
[Unit]
Description=Aurora Spark Master
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Environment=SPARK_HOME=/opt/spark
Environment=JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ExecStart=/opt/spark/bin/spark-class org.apache.spark.deploy.master.Master --host ${private_ip} --port 7077 --webui-port 8080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now spark-master
  sleep 10
  upload_status "spark_master_ready"
}

configure_spark_worker() {
  install_spark
  cat >/etc/systemd/system/spark-worker.service <<EOF
[Unit]
Description=Aurora Spark Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Environment=SPARK_HOME=/opt/spark
Environment=JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ExecStart=/opt/spark/bin/spark-class org.apache.spark.deploy.worker.Worker spark://${MASTER_PRIVATE}:7077 --webui-port 8081 --cores 1 --memory 512m
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now spark-worker
  sleep 10
  upload_status "${ROLE}_ready"
}

configure_cloudwatch_agent() {
  if [ ! -x /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl ]; then
    wget -q "https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb" -O /tmp/amazon-cloudwatch-agent.deb
    dpkg -i /tmp/amazon-cloudwatch-agent.deb || apt-get -f install -y
  fi
  cat >/opt/aurora/cw_agent_config.json <<EOF
{
  "agent": {
    "metrics_collection_interval": 60,
    "run_as_user": "root"
  },
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/aurora/aurora_clickstream.jsonl",
            "log_group_name": "/aurora/${STUDENT_ID}/clickstream",
            "log_stream_name": "{instance_id}",
            "timezone": "UTC",
            "retention_in_days": 14
          }
        ]
      }
    },
    "force_flush_interval": 5
  }
}
EOF
  /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:/opt/aurora/cw_agent_config.json
}

configure_web() {
  apt_retry apt-get install -y nginx rsync
  mkdir -p /var/www/aurora/frontend /opt/aurora/backend /etc/aurora /var/log/aurora /opt/aurora/output_business /opt/aurora/evidence
  chown -R ubuntu:ubuntu /opt/aurora /var/log/aurora

  python3 /opt/aurora/app/generators/generate_business_data.py \
    --student-id "${STUDENT_ID}" \
    --days 7 \
    --n-events 120 \
    --n-campaigns 12 \
    --n-transactions 20000 \
    --error-rate 0.05 \
    --orphan-rate 0.02 \
    --out-dir /opt/aurora/output_business \
    --frontend-data-dir /opt/aurora/app/webapp/frontend/data

  sed -i "s/TIENES_QUE_CAMBIAR_STUDENT_ID_CONFIG_JS/${STUDENT_ID}/g" /opt/aurora/app/webapp/frontend/js/config.js

  rsync -a --delete /opt/aurora/app/webapp/frontend/ /var/www/aurora/frontend/
  rsync -a --delete /opt/aurora/app/webapp/backend/ /opt/aurora/backend/
  python3 -m venv /opt/aurora/backend/.venv
  /opt/aurora/backend/.venv/bin/pip install --upgrade pip
  /opt/aurora/backend/.venv/bin/pip install -r /opt/aurora/backend/requirements.txt requests

  cat >/etc/aurora/aurora.env <<EOF
STUDENT_ID=${STUDENT_ID}
AURORA_LOG_PATH=/var/log/aurora/aurora_clickstream.jsonl
EOF

  cat >/etc/systemd/system/aurora-backend.service <<EOF
[Unit]
Description=Aurora Tickets FastAPI backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/aurora/backend
EnvironmentFile=/etc/aurora/aurora.env
ExecStart=/opt/aurora/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  cp /opt/aurora/app/webapp/deploy/nginx/aurora.nginx.conf.template /etc/nginx/sites-available/aurora
  rm -f /etc/nginx/sites-enabled/default
  ln -sfn /etc/nginx/sites-available/aurora /etc/nginx/sites-enabled/aurora
  nginx -t
  systemctl daemon-reload
  systemctl enable --now aurora-backend
  systemctl enable --now nginx
  systemctl restart nginx
  configure_cloudwatch_agent

  for n in $(seq 1 30); do
    if curl -fsS http://127.0.0.1/health; then
      break
    fi
    sleep 5
  done

  aws s3 cp /opt/aurora/output_business/events.csv "s3://${BUCKET}/${PREFIX}/raw/business/events.csv"
  aws s3 cp /opt/aurora/output_business/campaigns.csv "s3://${BUCKET}/${PREFIX}/raw/business/campaigns.csv"
  aws s3 cp /opt/aurora/output_business/transactions.csv "s3://${BUCKET}/${PREFIX}/raw/business/transactions.csv"

  /opt/aurora/backend/.venv/bin/python /opt/aurora/app/simulators/traffic_driver.py \
    --base-url http://127.0.0.1 \
    --student-id "${STUDENT_ID}" \
    --events-json /opt/aurora/app/webapp/frontend/data/events.json \
    --campaigns-csv /opt/aurora/output_business/campaigns.csv \
    --sessions 700 \
    --max-actions 8 \
    --sleep-ms 10

  /opt/aurora/backend/.venv/bin/python /opt/aurora/app/simulators/replay_clickstream.py \
    --student-id "${STUDENT_ID}" \
    --days 7 \
    --n-events 205000 \
    --events-json /opt/aurora/app/webapp/frontend/data/events.json \
    --campaigns-csv /opt/aurora/output_business/campaigns.csv \
    --out /var/log/aurora/aurora_clickstream.jsonl \
    --append \
    --include-server 1 \
    --bot-rate 0.02

  wc -l /var/log/aurora/aurora_clickstream.jsonl | tee /opt/aurora/evidence/clickstream_line_count.txt
  aws s3 cp /var/log/aurora/aurora_clickstream.jsonl "s3://${BUCKET}/${PREFIX}/raw/clickstream/aurora_clickstream.jsonl"
  aws s3 cp /opt/aurora/evidence/clickstream_line_count.txt "s3://${BUCKET}/${PREFIX}/evidence/clickstream_line_count.txt"
  upload_status "web_raw_ready"
}

configure_submit() {
  install_spark
  python3 -m venv /opt/aurora/pyenv
  /opt/aurora/pyenv/bin/pip install --upgrade pip
  /opt/aurora/pyenv/bin/pip install PyMySQL cryptography

  for n in $(seq 1 120); do
    if aws s3 ls "s3://${BUCKET}/${PREFIX}/raw/clickstream/aurora_clickstream.jsonl"; then
      break
    fi
    echo "waiting for raw clickstream in S3"
    sleep 30
  done

  export PYSPARK_DRIVER_PYTHON=/opt/aurora/pyenv/bin/python
  export PYSPARK_PYTHON=python3
  local s3_conf
  s3_conf=(
    --packages org.apache.hadoop:hadoop-aws:3.3.4,com.amazonaws:aws-java-sdk-bundle:1.12.262
    --conf spark.hadoop.fs.s3a.impl=org.apache.hadoop.fs.s3a.S3AFileSystem
    --conf spark.hadoop.fs.s3a.aws.credentials.provider=com.amazonaws.auth.InstanceProfileCredentialsProvider
    --conf spark.executor.memory=512m
    --conf spark.driver.memory=512m
    --conf spark.executor.cores=1
  )

  /opt/spark/bin/spark-submit \
    --master "spark://${MASTER_PRIVATE}:7077" \
    "${s3_conf[@]}" \
    /opt/aurora/app/spark/job1_curate.py \
    --bucket "${BUCKET}" \
    --prefix "${PREFIX}" \
    --student-id "${STUDENT_ID}" \
    > /opt/aurora/spark-submit-job1.log 2>&1

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
    > /opt/aurora/spark-submit-job2.log 2>&1

  aws s3 cp /opt/aurora/spark-submit-job1.log "s3://${BUCKET}/${PREFIX}/evidence/spark-submit-job1.log"
  aws s3 cp /opt/aurora/spark-submit-job2.log "s3://${BUCKET}/${PREFIX}/evidence/spark-submit-job2.log"
  upload_status "spark_jobs_done"
}

install_base
download_bundle

case "${ROLE}" in
  spark-master)
    configure_spark_master
    ;;
  spark-worker-1|spark-worker-2|spark-worker-3)
    configure_spark_worker
    ;;
  web)
    configure_web
    ;;
  submit)
    configure_submit
    ;;
  *)
    echo "Unknown role ${ROLE}" >&2
    exit 1
    ;;
esac

echo "Aurora bootstrap completed role=${ROLE}"
