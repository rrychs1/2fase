#!/bin/bash
echo "========================================="
echo " Algorithmic Trading Bot V3 Deployment"
echo "========================================="

# Ensure execution flags strictly pass locally on Unix configs
chmod +x run.sh

# Verify Docker daemon is running
if ! docker info > /dev/null 2>&1; then
  echo "ERROR: Docker daemon is not running! Start Docker before deploying."
  exit 1
fi

echo "[*] Building and spinning up the complete isolated orchestration stack..."

# Re-build ensuring fresh caches map natively over the network bonds
docker-compose up --build -d

echo ""
echo "[*] DEPLOYMENT SUCCESSFUL"
echo "========================================="
echo "Dashboard UI : http://localhost:8050"
echo "Grafana Edge : http://localhost:3000"
echo "Prometheus   : http://localhost:9090 (Internal)"
echo "Metrics Raw  : http://localhost:8000"
echo ""
echo "Type 'docker-compose logs -f bot' to view the live trading execution native systems loop."
echo "========================================="
