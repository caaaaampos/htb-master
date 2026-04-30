#!/bin/bash
# ─────────────────────────────────────────────
#   HTB Agent — Setup para Mac
#   Instala todos los requisitos automáticamente
# ─────────────────────────────────────────────

set -e  # Parar si hay error

# Colores
BLACK='\033[0;30m'
WHITE='\033[1;37m'
GRAY='\033[0;37m'
BOLD='\033[1m'
NC='\033[0m' # Reset

# Banner
clear
echo ""
echo -e "${WHITE}"
echo "  ██╗  ██╗████████╗██████╗      █████╗  ██████╗ ███████╗███╗   ██╗████████╗"
echo "  ██║  ██║╚══██╔══╝██╔══██╗    ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝"
echo "  ███████║   ██║   ██████╔╝    ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   "
echo "  ██╔══██║   ██║   ██╔══██╗    ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   "
echo "  ██║  ██║   ██║   ██████╔╝    ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   "
echo "  ╚═╝  ╚═╝   ╚═╝   ╚═════╝     ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   "
echo -e "${NC}"
echo -e "${GRAY}  Mobile Agent — Setup Script for macOS${NC}"
echo -e "${GRAY}  ────────────────────────────────────────────${NC}"
echo ""

# ─── Funciones helper ───────────────────────────────────────────────────────

ok()   { echo -e "  ${WHITE}✓${NC}  $1"; }
info() { echo -e "  ${GRAY}→${NC}  $1"; }
warn() { echo -e "  ${GRAY}!${NC}  $1"; }
fail() { echo -e "  ✗  $1"; exit 1; }
step() { echo ""; echo -e "${WHITE}  ── $1${NC}"; echo ""; }

ask() {
    echo -ne "  ${WHITE}?${NC}  $1 [Y/n] "
    read answer
    [[ "$answer" != "n" && "$answer" != "N" ]]
}

# ─── Verificar macOS ────────────────────────────────────────────────────────

step "1. Verificando sistema"

if [[ "$OSTYPE" != "darwin"* ]]; then
    fail "Este script es para macOS. Para Linux/Windows usa el setup manual."
fi
ok "macOS detectado: $(sw_vers -productVersion)"

# Arquitectura
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
    ok "Apple Silicon (M1/M2/M3)"
else
    ok "Intel x86_64"
fi

# ─── Homebrew ───────────────────────────────────────────────────────────────

step "2. Homebrew"

if command -v brew &>/dev/null; then
    ok "Homebrew ya instalado ($(brew --version | head -1))"
else
    info "Instalando Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Agregar brew al PATH en Apple Silicon
    if [[ "$ARCH" == "arm64" ]]; then
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    ok "Homebrew instalado"
fi

# ─── Python ─────────────────────────────────────────────────────────────────

step "3. Python 3.12"

if command -v python3.12 &>/dev/null; then
    ok "Python 3.12 ya instalado ($(python3.12 --version))"
else
    info "Instalando Python 3.12..."
    brew install python@3.12
    ok "Python 3.12 instalado"
fi

# Verificar versión
PYTHON_VERSION=$(python3.12 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
info "Usando Python $PYTHON_VERSION"
ok "Python listo"

# ─── ADB ────────────────────────────────────────────────────────────────────

step "4. ADB (Android Debug Bridge)"

if command -v adb &>/dev/null; then
    ok "ADB ya instalado ($(adb version | head -1))"
else
    info "Instalando ADB via Homebrew..."
    brew install android-platform-tools
    ok "ADB instalado"
fi

# ─── Node.js (para Electron futuro) ─────────────────────────────────────────

step "5. Node.js (requerido para Electron)"

if command -v node &>/dev/null; then
    ok "Node.js ya instalado ($(node --version))"
else
    info "Instalando Node.js..."
    brew install node
    ok "Node.js instalado ($(node --version))"
fi

# ─── Virtual Environment + Dependencias ─────────────────────────────────────

step "6. Virtual Environment + Dependencias"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Crear virtualenv si no existe
if [[ -d "$VENV_DIR" ]]; then
    ok "Virtualenv ya existe en .venv"
else
    info "Creando virtualenv en .venv ..."
    python3.12 -m venv "$VENV_DIR"
    ok "Virtualenv creado"
fi

# Activar virtualenv
source "$VENV_DIR/bin/activate"
ok "Virtualenv activado"

# Actualizar pip dentro del venv
info "Actualizando pip..."
pip install --upgrade pip --quiet

# Instalar htb_agent
info "Instalando htb_agent..."
cd "$SCRIPT_DIR"
pip install -e . --quiet
ok "htb_agent instalado"

# Instalar server
info "Instalando dependencias del servidor..."
pip install -r server/requirements.txt --quiet
ok "Server dependencies instaladas"

# ─── Archivo .env ───────────────────────────────────────────────────────────

step "7. Configuración API Keys"

ENV_FILE="$SCRIPT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
    ok ".env ya existe"
    warn "Edítalo en: $ENV_FILE"
else
    echo ""
    echo -e "  ${GRAY}Necesitas una API Key de OpenAI.${NC}"
    echo -e "  ${GRAY}Obtenerla en: https://platform.openai.com/api-keys${NC}"
    echo ""
    echo -ne "  ${WHITE}?${NC}  Pega tu OPENAI_API_KEY (o Enter para hacerlo después): "
    read API_KEY

    cat > "$ENV_FILE" << EOF
# HTB Agent — Environment Variables
# ────────────────────────────────────

# OpenAI API Key (requerido)
OPENAI_API_KEY=${API_KEY:-sk-your-key-here}

# Modelo a usar (opcional)
HTB_DEFAULT_MODEL=gpt-4o

# Puerto del servidor dashboard (opcional)
HTB_PORT=8888
EOF
    ok ".env creado en $ENV_FILE"

    if [[ -z "$API_KEY" ]]; then
        warn "Recuerda agregar tu OPENAI_API_KEY en el archivo .env"
    fi
fi

# ─── Script de inicio ───────────────────────────────────────────────────────

step "8. Creando comandos de inicio"

# Script para iniciar el dashboard
cat > "$SCRIPT_DIR/start.sh" << 'STARTSCRIPT'
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
STARTSCRIPT

chmod +x "$SCRIPT_DIR/start.sh"
ok "start.sh creado"

# Alias opcional
if ask "¿Agregar comando 'htb-dashboard' a tu terminal?"; then
    SHELL_RC="$HOME/.zshrc"
    [[ -f "$HOME/.bashrc" ]] && SHELL_RC="$HOME/.bashrc"

    ALIAS_LINE="alias htb-dashboard='bash $SCRIPT_DIR/start.sh'"
    if ! grep -q "htb-dashboard" "$SHELL_RC"; then
        echo "" >> "$SHELL_RC"
        echo "# HTB Agent" >> "$SHELL_RC"
        echo "$ALIAS_LINE" >> "$SHELL_RC"
        ok "Alias agregado a $SHELL_RC"
        info "Reinicia tu terminal o ejecuta: source $SHELL_RC"
    else
        ok "Alias ya existe"
    fi
fi

# ─── Verificar ADB devices ──────────────────────────────────────────────────

step "9. Verificando dispositivos conectados"

ADB_OUTPUT=$(adb devices 2>/dev/null)
DEVICE_COUNT=$(echo "$ADB_OUTPUT" | grep -c "device$" || true)

if [[ $DEVICE_COUNT -gt 0 ]]; then
    ok "$DEVICE_COUNT dispositivo(s) detectado(s):"
    echo "$ADB_OUTPUT" | grep "device$" | while read line; do
        echo "     → $line"
    done
else
    warn "No hay dispositivos conectados ahora."
    info "Conecta un Android con USB y activa 'Depuración USB' en Opciones de desarrollador"
    info "Para WiFi: adb connect IP_DEL_TELEFONO:5555"
fi

# ─── Resumen final ──────────────────────────────────────────────────────────

echo ""
echo -e "${WHITE}  ─────────────────────────────────────────────${NC}"
echo -e "${WHITE}  ✓  Setup completado${NC}"
echo ""
echo -e "${GRAY}  Para iniciar el dashboard:${NC}"
echo ""
echo -e "      ${WHITE}./start.sh${NC}"
echo ""
echo -e "${GRAY}  O si agregaste el alias:${NC}"
echo ""
echo -e "      ${WHITE}htb-dashboard${NC}"
echo ""
echo -e "${GRAY}  Para usar el CLI directamente:${NC}"
echo ""
echo -e "      ${WHITE}htb-agent run \"Abre WhatsApp\"${NC}"
echo ""
echo -e "  ${GRAY}────────────────────────────────────────────────${NC}"
echo ""
