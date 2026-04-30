#!/bin/bash
# HTB Agent — MASTER SERVER (Mac Studio)
# Corre en puerto 8888

cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║      HTB AGENT — MASTER SERVER       ║"
echo "║         Mac Studio  :8888            ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Verificar virtualenv
if [ ! -d ".venv" ]; then
  echo "→ Creando virtualenv..."
  python3 -m venv .venv
fi

source .venv/bin/activate

# Instalar dependencias si faltan
echo "→ Verificando dependencias..."
pip install -q fastapi uvicorn httpx

# Verificar Ollama
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
  echo "✓ Ollama corriendo en localhost:11434"
else
  echo "⚠ Ollama no está corriendo — iniciando..."
  ollama serve &
  sleep 3
fi

echo ""
echo "→ Dashboard: http://localhost:8888"
echo "→ Dashboard: http://$(ipconfig getifaddr en0):8888"
echo ""

uvicorn server.master:app --host 0.0.0.0 --port 8888
