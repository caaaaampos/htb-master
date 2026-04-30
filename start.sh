#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activar virtualenv
if [[ -f "$SCRIPT_DIR/.venv/bin/activate" ]]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
else
    echo "  ✗  Virtualenv no encontrado. Ejecuta ./setup_mac.sh primero."
    exit 1
fi

# Cargar .env
if [[ -f .env ]]; then
    export $(grep -v '^#' .env | xargs)
fi

# Verificar API key
if [[ "$OPENAI_API_KEY" == "sk-your-key-here" || -z "$OPENAI_API_KEY" ]]; then
    echo ""
    echo "  ✗  OPENAI_API_KEY no configurada."
    echo "     Edita el archivo .env y agrega tu key."
    echo ""
    exit 1
fi

PORT="${HTB_PORT:-8888}"

echo ""
echo "  HTB Agent Dashboard"
echo "  ─────────────────────────────"
echo "  http://localhost:$PORT"
echo "  Ctrl+C para detener"
echo ""

# Abrir browser automáticamente
sleep 1.5 && open "http://localhost:$PORT" &

# Iniciar servidor
uvicorn server.main:app --host 0.0.0.0 --port $PORT --reload
