#!/usr/bin/env bash
# webapp/deploy/run_backend.sh
set -euo pipefail

ENV_FILE="/etc/aurora/aurora.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: No existe $ENV_FILE. Cópialo desde aurora.env.template"
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

# Directorio backend en /opt/aurora/backend (lo pone install_web_stack.sh)
cd /opt/aurora/backend

# Activar venv
source .venv/bin/activate

# Arrancar uvicorn
exec uvicorn app.main:app --host "${AURORA_HOST:-127.0.0.1}" --port "${AURORA_PORT:-8000}"