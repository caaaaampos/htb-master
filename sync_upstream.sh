#!/usr/bin/env bash
# sync_upstream.sh
# Sincroniza cambios del upstream (mobilerun) al white-label (htb_agent).
# Uso:
#   ./sync_upstream.sh           → modo interactivo (pide confirmación)
#   ./sync_upstream.sh --dry-run → solo muestra qué cambiaría, sin modificar nada

set -euo pipefail

# ─── Configuración ────────────────────────────────────────────────────────────
UPSTREAM_URL="https://github.com/caaaaampos/htb-master"
UPSTREAM_PKG="mobilerun"
LOCAL_PKG="htb_agent"
TEMP_DIR="/tmp/htb_upstream_sync"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false

# ─── Colores ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()  { echo -e "${BOLD}[sync]${NC} $*"; }
ok()   { echo -e "${GREEN}  ✓${NC} $*"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $*"; }
skip() { echo -e "${CYAN}  ↷${NC} $*"; }
info() { echo -e "${BLUE}  →${NC} $*"; }

# ─── Archivos/carpetas protegidos (nunca se tocan) ────────────────────────────
# Rutas relativas a la raíz del proyecto
PROTECTED=(
    "server"
    "dashboard"
    "docs"
    "${LOCAL_PKG}/spotify"
    "start.sh"
    "start_master.sh"
    "start_node.sh"
    "setup_mac.sh"
    ".env"
    "WHITELABEL.md"
    "README.md"
    "SKILL.md"
    "CONTRIBUTING.md"
    "Dockerfile"
    ".dockerignore"
    ".gitignore"
    "static/htb-agent.png"
    "pyproject.toml"
    "uv.lock"
    "${LOCAL_PKG}/__init__.py"
    "${LOCAL_PKG}/config_example.yaml"
    "${LOCAL_PKG}/portal.py"           # Portal repo/package/IME identity is brand-sensitive
    "${LOCAL_PKG}/agent/droid/__init__.py" # Public compatibility aliases
    "${LOCAL_PKG}/agent/utils/tracing_setup.py" # Telemetry/span naming is brand-sensitive
    "${LOCAL_PKG}/config_manager/config_manager.py" # Legacy config fields/aliases
    "${LOCAL_PKG}/config_manager/__init__.py"
    "${LOCAL_PKG}/config_manager/loader.py" # User config path/env var identity
    "${LOCAL_PKG}/config_manager/credential_paths.py"
    "${LOCAL_PKG}/mcp/adapter.py"      # Public HTB Agent helper names
    "${LOCAL_PKG}/mcp/__init__.py"
    "${LOCAL_PKG}/telemetry/tracker.py"
    "${LOCAL_PKG}/telemetry/langfuse_processor.py"
    "${LOCAL_PKG}/tools/android/portal_client.py"
    "${LOCAL_PKG}/tools/driver/ios.py" # iOS bundle ids are app-identity sensitive
    "${LOCAL_PKG}/tools/driver/cloud.py" # External SDK/API endpoint; review manually
    "${LOCAL_PKG}/cli"                 # CLI is user-facing; merge upstream changes manually
    "${LOCAL_PKG}/cli/main.py"
    "${LOCAL_PKG}/cli/tui"            # TUI puede tener cambios de branding
)

# ─── Directorios del paquete a sincronizar ────────────────────────────────────
# Se copian desde upstream/${UPSTREAM_PKG}/<dir> → local/${LOCAL_PKG}/<dir>
SYNC_DIRS=(
    "agent"
    "app_cards"
    "config"
    "config_manager"
    "credential_manager"
    "macro"
    "mcp"
    "telemetry"
    "tools"
)

# cli/ se sincroniza pero excluyendo main.py y tui/ (están en PROTECTED)
SYNC_CLI=true

# ─── Archivos sueltos del paquete a sincronizar ───────────────────────────────
SYNC_PKG_FILES=(
    "log_handlers.py"
    "portal.py"
    "__main__.py"
    "config_example.yaml"
)

# ─── Archivos raíz a sincronizar ─────────────────────────────────────────────
SYNC_ROOT_FILES=(
    "CHANGELOG.md"
    "CONTRIBUTING.md"
    "SKILL.md"
    "Dockerfile"
    ".dockerignore"
    ".gitignore"
    ".python-version"
)

# ─── Parseo de argumentos ─────────────────────────────────────────────────────
for arg in "$@"; do
    case $arg in
        --dry-run) DRY_RUN=true ;;
        --help)
            echo "Uso: $0 [--dry-run]"
            echo "  --dry-run   Muestra qué cambiaría sin modificar nada"
            exit 0 ;;
        *) echo "Argumento desconocido: $arg"; exit 1 ;;
    esac
done

# ─── Funciones ────────────────────────────────────────────────────────────────

is_protected() {
    local rel_path="$1"
    for p in "${PROTECTED[@]}"; do
        # Coincidencia exacta o prefijo de directorio
        if [[ "$rel_path" == "$p" || "$rel_path" == "$p/"* ]]; then
            return 0
        fi
    done
    return 1
}

apply_rename() {
    # Aplica el rename mobilerun→htb_agent dentro de un archivo.
    # Mantenerlo conservador: no tocar API/package names como
    # api.mobilerun.com o com.mobilerun.portal.
    local file="$1"
    LC_ALL=C LC_CTYPE=C LANG=C UPSTREAM_PKG="$UPSTREAM_PKG" LOCAL_PKG="$LOCAL_PKG" perl -0pi -e '
        my $u = $ENV{"UPSTREAM_PKG"};
        my $l = $ENV{"LOCAL_PKG"};
        s/from \Q$u\E\./from $l./g;
        s/from \Q$u\E import/from $l import/g;
        s/import \Q$u\E\b/import $l/g;
        s/\b\Q$u\E(?=\.(?:agent|app_cards|cli|config|config_manager|credential_manager|macro|mcp|telemetry|tools|log_handlers|portal)\b)/$l/g;
        s/logging\.getLogger\("\Q$u\E"\)/logging.getLogger("$l")/g;
        s/logging\.getLogger\("\Q$u\E-/logging.getLogger("$l-/g;
        s/version\("\Q$u\E"\)/version("hackthebox-agent")/g;
        s/mcp_to_mobilerun_tools/mcp_to_htb_agent_tools/g;
        s/\bMobilerun\b/HTB Agent/g;
        s/\bMobileRun\b/HTB Agent/g;
        s/(?<![\.\/\w-])\Q$u\E(?![.\w-])/$l/g;
        s/"\.\Q$u\E"/".$l"/g;
        s/'\''\.\Q$u\E'\''/'\''.$l'\''/g;
        s#https://docs\.mobilerun\.ai#https://docs.hackthebox.com#g;
        s#https://github\.com/droidrun/mobilerun/blob/main/mobilerun/config_example\.yaml#https://github.com/hackthebox/hackthebox-agent/blob/main/htb_agent/config_example.yaml#g;
        s#/usr/share/\Q$u\E#/usr/share/$l#g;
    ' "$file"
}

needs_rename() {
    local src="$1"
    local ext="${src##*.}"
    [[ "$ext" == "py" || "$ext" == "yaml" || "$ext" == "yml" || "$ext" == "jinja2" || "$ext" == "md" ]]
}

render_with_rename() {
    local src="$1"
    local dst="$2"

    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"

    if needs_rename "$src"; then
        apply_rename "$dst"
    fi
}

copy_with_rename() {
    # Copia un archivo aplicando el rename en formatos textuales conocidos.
    local src="$1"
    local dst="$2"
    local tmp_compare

    if $DRY_RUN; then
        tmp_compare=$(mktemp)
        render_with_rename "$src" "$tmp_compare"
        if [[ ! -f "$dst" ]]; then
            info "NUEVO: ${dst#$SCRIPT_DIR/}"
        elif ! diff -q "$tmp_compare" "$dst" > /dev/null 2>&1; then
            info "CAMBIO: ${dst#$SCRIPT_DIR/}"
        fi
        rm -f "$tmp_compare"
        return
    fi

    render_with_rename "$src" "$dst"
}

sync_directory() {
    local upstream_dir="$1"   # ruta absoluta en el upstream clonado
    local local_dir="$2"       # ruta absoluta en el repo local
    local rel_base="$3"        # prefijo para mensajes (ej: htb_agent/agent)

    local count_new=0 count_changed=0 count_skipped=0

    # Iterar sobre todos los archivos del upstream (excluyendo __pycache__)
    while IFS= read -r -d '' src_file; do
        local rel="${src_file#$upstream_dir/}"
        local dst_file="${local_dir}/${rel}"
        local rel_full="${rel_base}/${rel}"

        # Saltar __pycache__ y .pyc
        if [[ "$rel" == *"__pycache__"* || "$rel" == *.pyc ]]; then
            continue
        fi

        # Verificar si está protegido
        if is_protected "${rel_full}"; then
            skip "Protegido: ${rel_full}"
            ((count_skipped++)) || true
            continue
        fi

        if [[ ! -f "$dst_file" ]]; then
            copy_with_rename "$src_file" "$dst_file"
            $DRY_RUN || ok "Nuevo: ${rel_full}"
            ((count_new++)) || true
        else
            # Comparar contenido después del rename (en temp)
            local tmp_compare
            tmp_compare=$(mktemp)
            render_with_rename "$src_file" "$tmp_compare"

            if ! diff -q "$tmp_compare" "$dst_file" > /dev/null 2>&1; then
                if $DRY_RUN; then
                    info "CAMBIO: ${rel_full}"
                    diff --color=always -u "$dst_file" "$tmp_compare" 2>/dev/null || true
                else
                    copy_with_rename "$src_file" "$dst_file"
                    ok "Actualizado: ${rel_full}"
                fi
                ((count_changed++)) || true
            fi
            rm -f "$tmp_compare"
        fi
    done < <(find "$upstream_dir" -type f -print0)

    # Detectar archivos eliminados en upstream (avisar, no borrar)
    while IFS= read -r -d '' dst_file; do
        local rel="${dst_file#$local_dir/}"
        local rel_full="${rel_base}/${rel}"
        if [[ "$rel" == *"__pycache__"* || "$rel" == *.pyc ]]; then
            continue
        fi
        local src_file="${upstream_dir}/${rel}"
        if [[ ! -f "$src_file" ]]; then
            warn "ELIMINADO en upstream (revisar): ${rel_full}"
        fi
    done < <(find "$local_dir" -type f -print0 2>/dev/null || true)

    echo -e "  ${GREEN}Nuevos: ${count_new}${NC}  ${BLUE}Actualizados: ${count_changed}${NC}  ${CYAN}Protegidos saltados: ${count_skipped}${NC}"
}

# ─── Main ─────────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   HTB Agent — Sync desde upstream (${UPSTREAM_PKG})   ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

if $DRY_RUN; then
    echo -e "${YELLOW}  MODO DRY-RUN — no se modificará ningún archivo${NC}"
    echo ""
fi

# 1. Clonar / actualizar upstream
log "Descargando upstream: ${UPSTREAM_URL}"
if [[ -d "$TEMP_DIR/.git" ]]; then
    info "Ya existe clon local — haciendo pull..."
    git -C "$TEMP_DIR" fetch --depth=1 origin main 2>/dev/null \
        && git -C "$TEMP_DIR" reset --hard origin/main 2>/dev/null \
        || { warn "No pudo actualizar, re-clonando..."; rm -rf "$TEMP_DIR"; git clone --depth=1 "$UPSTREAM_URL" "$TEMP_DIR"; }
else
    rm -rf "$TEMP_DIR"
    git clone --depth=1 "$UPSTREAM_URL" "$TEMP_DIR"
fi
UPSTREAM_PKG_DIR="${TEMP_DIR}/${UPSTREAM_PKG}"

if [[ ! -d "$UPSTREAM_PKG_DIR" ]]; then
    echo -e "${RED}ERROR: No se encontró '${UPSTREAM_PKG}/' en el upstream clonado.${NC}"
    echo "  Ruta esperada: ${UPSTREAM_PKG_DIR}"
    exit 1
fi

UPSTREAM_COMMIT=$(git -C "$TEMP_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
ok "Upstream en commit: ${UPSTREAM_COMMIT}"
echo ""

# 2. Sincronizar directorios del paquete
log "Sincronizando directorios del paquete..."
for dir in "${SYNC_DIRS[@]}"; do
    upstream_d="${UPSTREAM_PKG_DIR}/${dir}"
    local_d="${SCRIPT_DIR}/${LOCAL_PKG}/${dir}"
    if [[ ! -d "$upstream_d" ]]; then
        warn "  No existe en upstream: ${UPSTREAM_PKG}/${dir} — saltando"
        continue
    fi
    echo -e "\n  ${BOLD}${LOCAL_PKG}/${dir}/${NC}"
    sync_directory "$upstream_d" "$local_d" "${LOCAL_PKG}/${dir}"
done

# 3. Sincronizar cli/ (excluyendo main.py y tui/)
if $SYNC_CLI; then
    echo -e "\n  ${BOLD}${LOCAL_PKG}/cli/${NC}  (excluye main.py y tui/)"
    upstream_cli="${UPSTREAM_PKG_DIR}/cli"
    local_cli="${SCRIPT_DIR}/${LOCAL_PKG}/cli"
    if [[ -d "$upstream_cli" ]]; then
        while IFS= read -r -d '' src_file; do
            rel="${src_file#$upstream_cli/}"
            # Saltar main.py, tui/, __pycache__ y .pyc
            if [[ "$rel" == "main.py" || "$rel" == "tui"* \
               || "$rel" == *"__pycache__"* || "$rel" == *.pyc ]]; then
                continue
            fi
            dst_file="${local_cli}/${rel}"

            if is_protected "${LOCAL_PKG}/cli/${rel}"; then
                skip "Protegido: ${LOCAL_PKG}/cli/${rel}"
                continue
            fi

            tmp_compare=$(mktemp)
            render_with_rename "$src_file" "$tmp_compare"

            if [[ ! -f "$dst_file" ]]; then
                if $DRY_RUN; then
                    info "NUEVO: ${LOCAL_PKG}/cli/${rel}"
                else
                    mkdir -p "$(dirname "$dst_file")"
                    cp "$tmp_compare" "$dst_file"
                    ok "Nuevo: ${LOCAL_PKG}/cli/${rel}"
                fi
            elif ! diff -q "$tmp_compare" "$dst_file" > /dev/null 2>&1; then
                if $DRY_RUN; then
                    info "CAMBIO: ${LOCAL_PKG}/cli/${rel}"
                    diff --color=always -u "$dst_file" "$tmp_compare" 2>/dev/null || true
                else
                    cp "$tmp_compare" "$dst_file"
                    ok "Actualizado: ${LOCAL_PKG}/cli/${rel}"
                fi
            fi
            rm -f "$tmp_compare"
        done < <(find "$upstream_cli" -type f -print0)
    fi
fi

# 4. Sincronizar archivos sueltos del paquete
echo -e "\n  ${BOLD}${LOCAL_PKG}/ (archivos sueltos)${NC}"
for f in "${SYNC_PKG_FILES[@]}"; do
    src="${UPSTREAM_PKG_DIR}/${f}"
    dst="${SCRIPT_DIR}/${LOCAL_PKG}/${f}"
    if [[ ! -f "$src" ]]; then
        warn "No existe en upstream: ${UPSTREAM_PKG}/${f} — saltando"
        continue
    fi
    if is_protected "${LOCAL_PKG}/${f}"; then
        skip "Protegido: ${LOCAL_PKG}/${f}"
        continue
    fi
    copy_with_rename "$src" "$dst"
    $DRY_RUN || ok "Sincronizado: ${LOCAL_PKG}/${f}"
done

# 5. Sincronizar archivos raíz
echo -e "\n  ${BOLD}Archivos raíz${NC}"
for f in "${SYNC_ROOT_FILES[@]}"; do
    src="${TEMP_DIR}/${f}"
    dst="${SCRIPT_DIR}/${f}"
    if [[ ! -f "$src" ]]; then
        warn "No existe en upstream: ${f} — saltando"
        continue
    fi
    if is_protected "$f"; then
        skip "Protegido: ${f}"
        continue
    fi
    copy_with_rename "$src" "$dst"
    $DRY_RUN || ok "Sincronizado: ${f}"
done

# 6. Resumen final
echo ""
echo -e "${BOLD}─────────────────────────────────────────────────────${NC}"
if $DRY_RUN; then
    echo -e "${YELLOW}  Dry-run completo. Ejecuta sin --dry-run para aplicar.${NC}"
else
    echo -e "${GREEN}  Sync completo desde upstream ${UPSTREAM_COMMIT}.${NC}"
    echo ""
    echo -e "  Próximos pasos recomendados:"
    echo -e "  ${CYAN}1.${NC} Revisar cambios: git diff (si tienes git init)"
    echo -e "  ${CYAN}2.${NC} Probar: htb-agent --help"
    echo -e "  ${CYAN}3.${NC} Si algo se rompió, revisar los archivos marcados como ELIMINADO"
fi
echo ""
