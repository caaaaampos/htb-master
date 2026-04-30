#!/bin/bash
# HTB Agent — Node Server
# Run on each Mac Mini rack node

# ── Config ────────────────────────────────────────────────────────────────────
# IP del Mac Studio (master)
export HTB_MASTER_URL="http://192.168.0.10:8888"

# ID de este nodo — cambiar en cada Mac Mini (RACK-01, RACK-02, etc.)
export HTB_NODE_ID="RACK-01"

# Token — se setea automáticamente al registrarse en el master
# Si ya está registrado, pégalo aquí:
# export HTB_NODE_TOKEN="tu-token-aquí"

# ── Start ─────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")"
source .venv/bin/activate

echo "Starting HTB Agent Node — ${HTB_NODE_ID}"
echo "Master: ${HTB_MASTER_URL}"
echo "Port:   8889"
echo ""

uvicorn server.main:app --host 0.0.0.0 --port 8889 --reload
