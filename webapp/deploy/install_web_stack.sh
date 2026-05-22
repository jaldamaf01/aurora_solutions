#!/usr/bin/env bash
# webapp/deploy/install_web_stack.sh
set -euo pipefail

echo "[1/9] Actualizando sistema e instalando dependencias..."
sudo apt-get update -y
sudo apt-get install -y nginx python3-venv python3-pip

echo "[2/9] Creando directorios destino..."
sudo mkdir -p /var/www/aurora/frontend
sudo mkdir -p /opt/aurora/backend
sudo mkdir -p /etc/aurora
sudo mkdir -p /var/log/aurora

echo "[3/9] Copiando frontend..."
# Asume que ejecutas el script desde la raíz del repo (donde está webapp/)
sudo rsync -av --delete webapp/frontend/ /var/www/aurora/frontend/

echo "[4/9] Copiando backend..."
sudo rsync -av --delete webapp/backend/ /opt/aurora/backend/

echo "[5/9] Preparando venv e instalando requirements..."
sudo chown -R ubuntu:ubuntu /opt/aurora
sudo chown -R ubuntu:ubuntu /var/log/aurora
cd /opt/aurora/backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo "[6/9] Instalando env file si no existe..."
if [ ! -f /etc/aurora/aurora.env ]; then
  echo "No existe /etc/aurora/aurora.env. Copiando template..."
  sudo cp webapp/deploy/aurora.env.template /etc/aurora/aurora.env || true
  sudo chown ubuntu:ubuntu /etc/aurora/aurora.env
  echo "⚠️ Edita /etc/aurora/aurora.env y establece STUDENT_ID=..."
fi

echo "[7/9] Instalando script de arranque backend..."
sudo cp webapp/deploy/run_backend.sh /opt/aurora/run_backend.sh
sudo chmod +x /opt/aurora/run_backend.sh
sudo chown ubuntu:ubuntu /opt/aurora/run_backend.sh

echo "[8/9] Configurando Nginx..."
sudo cp webapp/deploy/nginx/aurora.nginx.conf.template /etc/nginx/sites-available/aurora
# Deshabilitar default y habilitar aurora
sudo rm -f /etc/nginx/sites-enabled/default || true
sudo ln -sf /etc/nginx/sites-available/aurora /etc/nginx/sites-enabled/aurora
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx

echo "[9/9] Instalando y arrancando systemd service..."
sudo cp webapp/deploy/systemd/aurora-backend.service /etc/systemd/system/aurora-backend.service
sudo systemctl daemon-reload
sudo systemctl enable aurora-backend
sudo systemctl restart aurora-backend

echo "✅ Instalación terminada."
echo "Prueba:  curl -s http://localhost/health"
echo "Log file: /var/log/aurora/aurora_clickstream.jsonl"