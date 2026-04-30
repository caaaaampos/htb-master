# HTB Agent — Guía de White-label

## Flujo de repositorios

```
droidrun/mobilerun  (upstream público original)
        ↓
github.com/caaaaampos/htb-master  (fork de seguimiento)
        ↓
hackthebox-agent-full23/  (este repo — white-label HTB)
```

## Comprobación actual

Revisión hecha contra `caaaaampos/htb-master` y `droidrun/mobilerun` en `main`.
Ambos apuntan al mismo commit upstream actual: `79b18a5` (`Merge pull request #325 from Ramtx/fix/dep-conflicts`).

Nota importante: esta carpeta local no tiene `.git`. Si quieres hacer merges/rebases con seguridad,
trabaja desde un checkout git del white-label y usa esta carpeta como referencia o copia de trabajo.

## Rename central

| Upstream | White-label |
|---|---|
| Paquete Python: `mobilerun` | `htb_agent` |
| Package PyPI: `mobilerun` | `hackthebox-agent` |
| CLI command: `mobilerun` | `htb-agent` |
| Autor: Niels Schmidt / droidrun.ai | Hack The Box / hackthebox.com |
| Config dir: `~/.config/mobilerun` | `~/.config/htb_agent` |
| Portal Android | Mantener `com.droidrun.portal` salvo que exista APK HTB propia |

---

## Archivos 100% personalizados — NUNCA sobrescribir

Estos archivos **no existen** en el upstream y son completamente tuyos:

| Ruta | Descripción |
|---|---|
| `server/master.py` | Servidor de orquestación multi-nodo |
| `server/main.py` | API REST del servidor |
| `server/nodes.json` | Configuración de nodos activos |
| `dashboard/index.html` | Dashboard principal |
| `dashboard/master.html` | Vista del master node |
| `dashboard/screenwall.html` | Screen wall multi-dispositivo |
| `dashboard/os-spotify.html` | Integración OS + Spotify |
| `dashboard/viewer.html` | Visor de sesiones |
| `htb_agent/spotify/` | Módulo Spotify completo |
| `server/requirements.txt` | Dependencias del backend local |
| `server/htb_history.db` | Base de datos runtime/local, no es upstream |
| `start.sh` | Script arranque nodo simple |
| `start_master.sh` | Script arranque servidor master |
| `start_node.sh` | Script arranque nodo worker |
| `setup_mac.sh` | Setup automático en macOS |
| `static/htb-agent.png` | Logo HTB Agent |
| `WHITELABEL.md` | Esta guía |
| `sync_upstream.sh` | Herramienta local de sync |
| `.env` | Variables de entorno secretas |

---

## Archivos de white-label — Sincronizar manualmente con cuidado

Existen en el upstream pero tienen cambios de branding/imports tuyos:

| Ruta local | Qué tiene de personalizado |
|---|---|
| `pyproject.toml` | `name`, `authors`, `urls`, entry point `htb-agent` |
| `uv.lock` | Debe regenerarse desde tu `pyproject.toml`, no copiarse del upstream |
| `README.md` | Marca, comandos, logo y narrativa HTB |
| `SKILL.md` | Skill/documentación interna HTB |
| `CONTRIBUTING.md` | URLs, comandos y package local |
| `Dockerfile` / `.dockerignore` | Usuario, workdir, entrypoint y package incluido |
| `htb_agent/__init__.py` | Imports con `htb_agent.*`, versión de `hackthebox-agent` |
| `htb_agent/cli/main.py` | Branding HTB en mensajes, imports `htb_agent` |
| `htb_agent/cli/` | Toda la CLI es superficie visible; merge manual |
| `htb_agent/cli/tui/` | UI/UX terminal y textos visibles |
| `htb_agent/config_example.yaml` | Nombre de agente, rutas y defaults HTB |
| `htb_agent/portal.py` | Repo APK, asset, package name, IME, content URIs |
| `htb_agent/tools/android/portal_client.py` | Depende del package/URI del portal; merge junto con `portal.py` |
| `htb_agent/tools/driver/ios.py` | Bundle IDs del portal iOS |
| `htb_agent/tools/driver/cloud.py` | SDK/API cloud externo; no inventar endpoint HTB |
| `docs/` | Documentación pública, URLs y screenshots |

Cuando el upstream actualice estos archivos, hacer un **diff manual** y aplicar solo la lógica nueva, sin pisar los datos de marca.

---

## Archivos de lógica pura — El script los sincroniza automáticamente

El script `sync_upstream.sh` copia estos directorios desde upstream y aplica el rename automáticamente:

| Upstream `mobilerun/` | Local `htb_agent/` |
|---|---|
| `agent/` | `htb_agent/agent/` |
| `app_cards/` | `htb_agent/app_cards/` |
| `config/` | `htb_agent/config/` |
| `config_manager/` | `htb_agent/config_manager/` |
| `credential_manager/` | `htb_agent/credential_manager/` |
| `macro/` | `htb_agent/macro/` |
| `mcp/` | `htb_agent/mcp/` |
| `telemetry/` | `htb_agent/telemetry/` |
| `tools/` | `htb_agent/tools/` excepto portal/iOS/cloud |
| `log_handlers.py` | `htb_agent/log_handlers.py` |
| `__main__.py` | `htb_agent/__main__.py` |

Archivos raíz sincronizados automáticamente: `.gitignore`, `.python-version` y `CHANGELOG.md` si vuelve a existir en upstream.
Todo archivo raíz con marca (`README.md`, `CONTRIBUTING.md`, `SKILL.md`, `Dockerfile`, `.dockerignore`) queda protegido.

---

## Cambios upstream actuales detectados

El upstream actual trae cambios grandes. No aplicar a ciegas:

| Tipo | Rutas nuevas upstream que faltan localmente |
|---|---|
| Fast Agent nuevo | `htb_agent/agent/fast_agent/` |
| OAuth/configuración | `htb_agent/agent/utils/oauth/`, `htb_agent/cli/configure_*.py`, `htb_agent/cli/oauth_actions.py` |
| Provider registry | `htb_agent/agent/providers/` |
| Config paths/migraciones | `htb_agent/config_manager/credential_paths.py`, migraciones `v004` y `v005` |
| Visual/iOS/vision-only | `htb_agent/tools/driver/visual_remote.py`, `htb_agent/tools/ui/screenshot_provider.py` |
| Imágenes helper | `htb_agent/tools/helpers/images.py` |
| Prompts nuevos | `htb_agent/config/prompts/fast_agent/` |

También hay archivos locales que upstream ya eliminó o reemplazó:

| Local | Estado |
|---|---|
| `htb_agent/agent/codeact/` | Reemplazado por `fast_agent` en upstream actual |
| `htb_agent/agent/scripter/` | Eliminado/deprecated en upstream actual |
| `htb_agent/agent/external/autoglm.py`, `mai_ui.py` | Eliminados en upstream actual |
| `htb_agent/config/prompts/codeact/`, `scripter/` | Eliminados en upstream actual |
| `htb_agent/config_manager/safe_execution.py` | Eliminado en upstream actual |

Antes de borrar cualquiera de estos, comprobar si tus dashboards, Spotify o flujos internos todavía los importan.

---

## Dependencias que revisar manualmente

El upstream actual cambió `pyproject.toml`. Como tu `pyproject.toml` está protegido, revisar estos puntos:

| Upstream actual | Acción white-label |
|---|---|
| `version = "0.6.0rc2"` | Decidir versión de `hackthebox-agent` |
| `InquirerPy>=0.3.4` | Agregar si adoptas `configure`/OAuth wizard |
| `llama-index-llms-openai>=0.6.0` | Subir si adoptas cambios nuevos |
| `llama-index-llms-openai-like>=0.6.0` | Subir si adoptas cambios nuevos |
| `mobilerun-sdk>=3.1.0` | Preferir pin/rango explícito |
| `deepseek` extra no aparece upstream | Mantener como extra vacío; el runtime lo enruta por `OpenAILike` |
| `python-dotenv` no aparece upstream | Mantener si tus scripts/server lo usan |

---

## Cómo sincronizar cuando sale una nueva versión upstream

```bash
# 1. Ver qué cambiaría (sin modificar nada)
./sync_upstream.sh --dry-run

# 2. Revisar el output, especialmente:
#    - Líneas "CAMBIO:" → revisar diff mostrado
#    - Líneas "NUEVO:" → archivos nuevos que se agregarían
#    - Líneas "ELIMINADO en upstream" → el upstream borró algo, decidir si mantenerlo

# 3. Aplicar los cambios
./sync_upstream.sh

# 4. Verificar que todo funciona
htb-agent --help

# 5. Revisar si pyproject.toml upstream agregó nuevas dependencias
#    (el script NO toca tu pyproject.toml — hacerlo manualmente)
```

---

## Rename patterns aplicados automáticamente por el script

```
from mobilerun.X  →  from htb_agent.X
from mobilerun import X  →  from htb_agent import X
import mobilerun  →  import htb_agent
mobilerun.X       →  htb_agent.X  (solo módulos del paquete, no dominios/API/package names)
getLogger("mobilerun")      →  getLogger("htb_agent")
version("mobilerun")        →  version("hackthebox-agent")
Mobilerun / MobileRun       →  HTB Agent
https://docs.mobilerun.ai  →  https://docs.hackthebox.com
```

El script evita renombrar automáticamente cosas como `api.mobilerun.com`,
`com.mobilerun.portal` o bundle IDs. Esos puntos se revisan manualmente.

---

## Verificar nuevas dependencias del upstream

El script **NO sincroniza** `pyproject.toml` ni `uv.lock`. Cuando salga una nueva versión del upstream, comparar manualmente las dependencias:

```bash
# Ver dependencias del upstream
cat /tmp/htb_upstream_sync/pyproject.toml | grep -A30 "dependencies"

# Comparar con las tuyas
cat pyproject.toml | grep -A30 "dependencies"
```

Si el upstream agrega una nueva dependencia de lógica (no de branding), agregarla también en tu `pyproject.toml`.
