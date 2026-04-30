"""
HTB Agent — Dashboard Backend Server
"""

import asyncio
import base64
import json
import logging
import struct
import subprocess
import os
import sys
import shutil
import tempfile
from datetime import datetime

import httpx

import io

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("htb-server")

# ── Node identity ─────────────────────────────────────────────────────────────
NODE_TOKEN  = os.environ.get("HTB_NODE_TOKEN", "")
NODE_ID     = os.environ.get("HTB_NODE_ID", "RACK-01")
MASTER_URL  = os.environ.get("HTB_MASTER_URL", "").rstrip("/")

def check_node_token(request):
    """Returns True if request has valid node token (or token not set yet)."""
    if not NODE_TOKEN:
        return True   # no token set — allow (first boot)
    return request.headers.get("X-Node-Token") == NODE_TOKEN


app = FastAPI(title="HTB Agent Dashboard", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

dashboard_path = os.path.join(os.path.dirname(__file__), "..", "dashboard")
app.mount("/static", StaticFiles(directory=dashboard_path), name="static")

# ─── Tool paths ───────────────────────────────────────────────────────────────

def find_tool(name: str) -> str:
    candidates = [
        f"/opt/homebrew/bin/{name}",
        f"/usr/local/bin/{name}",
        shutil.which(name) or "",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return name

ADB    = find_tool("adb")
SCRCPY = find_tool("scrcpy")
logger.info(f"ADB: {ADB} | scrcpy: {SCRCPY}")

# scrcpy-server.jar bundled with the scrcpy installation
# Resolve relative to the scrcpy binary: <prefix>/bin/scrcpy → <prefix>/share/scrcpy/scrcpy-server
_scrcpy_bin_dir  = os.path.dirname(os.path.abspath(SCRCPY)) if os.path.isfile(SCRCPY) else ""
_scrcpy_share    = os.path.join(_scrcpy_bin_dir, "..", "share", "scrcpy", "scrcpy-server")
SCRCPY_SERVER_LOCAL  = os.path.normpath(_scrcpy_share) if os.path.isfile(os.path.normpath(_scrcpy_share)) else ""
SCRCPY_SERVER_DEVICE = "/data/local/tmp/scrcpy-server.jar"
SCRCPY_SERVER_VER    = "3.3.4"      # must match the installed scrcpy version

# ─── scrcpy-server protocol constants ────────────────────────────────────────
_PKT_FLAG_CONFIG    = 0x8000000000000000  # packet contains codec config (SPS/PPS)
_PKT_FLAG_KEYFRAME  = 0x4000000000000000  # packet is an IDR (key) frame
_PORT_BASE          = 27183               # adb forward local port base

# ─── WebSocket Manager ────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()

# ─── WebSocket Log Handler — streams logs to dashboard ───────────────────────

class WSLogHandler(logging.Handler):
    """Sends all log records to connected dashboard clients via WebSocket."""
    def __init__(self, mgr):
        super().__init__()
        self.mgr = mgr

    def emit(self, record):
        try:
            level = record.levelname  # DEBUG INFO WARNING ERROR CRITICAL
            msg = self.format(record)
            asyncio.get_event_loop().call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    self.mgr.broadcast({
                        "type": "server_log",
                        "level": level,
                        "logger": record.name,
                        "msg": msg,
                        "time": datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    })
                )
            )
        except Exception:
            pass

# Attach WS log handler to root logger so ALL logs go to dashboard
_ws_handler = WSLogHandler(manager)
_ws_handler.setFormatter(logging.Formatter("%(name)s — %(message)s"))
logging.getLogger().addHandler(_ws_handler)


# ─── Screen streaming (scrcpy → screenshots via ADB) ─────────────────────────

# serial → { "task": asyncio.Task, "ws_set": set[WebSocket] }
screen_streams: dict[str, dict] = {}


async def capture_screen_loop(serial: str):
    """Capture screenshots via ADB and broadcast to subscribed WebSockets."""
    logger.info(f"Starting screen stream for {serial}")
    tmp = tempfile.mktemp(suffix=".png")

    while True:
        ws_set = screen_streams.get(serial, {}).get("ws_set", set())
        if not ws_set:
            break

        try:
            # Capture screenshot via ADB
            proc = await asyncio.create_subprocess_exec(
                ADB, "-s", serial, "exec-out", "screencap", "-p",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            png_data, _ = await asyncio.wait_for(proc.communicate(), timeout=3)

            if png_data and len(png_data) > 1000:
                b64 = base64.b64encode(png_data).decode()
                msg = json.dumps({"type": "screen_frame", "serial": serial, "frame": b64})

                dead = set()
                for ws in list(ws_set):
                    try:
                        await ws.send_text(msg)
                    except:
                        dead.add(ws)
                ws_set -= dead

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error(f"Screen capture error for {serial}: {e}")

        await asyncio.sleep(0.5)  # ~2 fps

    # Cleanup
    screen_streams.pop(serial, None)
    logger.info(f"Screen stream stopped for {serial}")


def start_stream(serial: str, ws: WebSocket):
    if serial not in screen_streams:
        screen_streams[serial] = {"ws_set": set(), "task": None}

    screen_streams[serial]["ws_set"].add(ws)

    if screen_streams[serial]["task"] is None or screen_streams[serial]["task"].done():
        task = asyncio.create_task(capture_screen_loop(serial))
        screen_streams[serial]["task"] = task


def stop_stream(serial: str, ws: WebSocket):
    if serial in screen_streams:
        screen_streams[serial]["ws_set"].discard(ws)


# ─── ADB Utils ────────────────────────────────────────────────────────────────

def adb_cmd(args: list[str], device: str = None) -> str:
    cmd = [ADB]
    if device:
        cmd += ["-s", device]
    cmd += args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except:
        return ""


def get_connected_devices() -> list[dict]:
    output = adb_cmd(["devices", "-l"])
    logger.debug(f"adb devices: {repr(output)}")
    devices = []

    for line in output.splitlines()[1:]:
        line = line.strip()
        if not line or "offline" in line or "unauthorized" in line:
            continue
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue

        serial = parts[0]
        conn_type = "WiFi" if ":" in serial else "USB"
        model = adb_cmd(["shell", "getprop", "ro.product.model"], serial) or "Unknown"
        android = adb_cmd(["shell", "getprop", "ro.build.version.release"], serial) or "?"

        battery_raw = adb_cmd(["shell", "dumpsys", "battery"], serial)
        battery = "?%"
        for bat_line in battery_raw.splitlines():
            if "level:" in bat_line:
                battery = bat_line.split(":")[1].strip() + "%"
                break

        devices.append({
            "serial": serial, "name": model, "conn": conn_type,
            "android": f"Android {android}", "battery": battery,
            "status": "online", "task": "idle", "progress": 0,
            "logs": [{"time": now(), "msg": "Device connected", "type": "success"}]
        })

    logger.debug(f"Found {len(devices)} device(s)")
    return devices


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


async def report_to_master(payload: dict):
    """Forward a device event to the master so it reaches the screenwall."""
    if not MASTER_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(
                f"{MASTER_URL}/api/node-event",
                json={**payload, "node_id": NODE_ID},
            )
    except Exception as e:
        logger.debug(f"Could not report to master: {e}")


# ─── Task Runner ──────────────────────────────────────────────────────────────

running_tasks: dict[str, asyncio.Task] = {}


async def run_agent_task(serial: str, task: str):
    _start_evt = {
        "type": "device_update", "serial": serial,
        "status": "busy", "task": task, "progress": 5,
        "log": {"time": now(), "msg": f"▶ {task}", "type": "success"}
    }
    await manager.broadcast(_start_evt)
    await report_to_master(_start_evt)
    try:
        provider   = llm_config["provider"]
        model      = llm_config["model"]
        api_key    = llm_config["api_key"] or os.getenv("OPENAI_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "") or os.getenv("GROQ_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
        ollama_url = llm_config["ollama_url"]

        if provider != "Ollama" and not api_key:
            raise ValueError(f"No API key configured for {provider}. Set it in the dashboard settings.")

        from htb_agent.tools.driver.android import AndroidDriver
        from htb_agent.agent.droid.droid_agent import DroidAgent

        await manager.broadcast({
            "type": "device_update", "serial": serial, "progress": 20,
            "log": {"time": now(), "msg": "Initializing driver...", "type": ""}
        })

        tools = AndroidDriver(serial=serial)
        await tools.connect()

        await manager.broadcast({
            "type": "device_update", "serial": serial, "progress": 40,
            "log": {"time": now(), "msg": "Driver ready. Running agent...", "type": "success"}
        })

        from htb_agent.agent.utils.llm_picker import load_llm
        if provider == "Ollama":
            llm = load_llm("Ollama", model=model, base_url=ollama_url)
        else:
            llm = load_llm(provider, model=model, api_key=api_key)
        agent = DroidAgent(goal=task, driver=tools, llms=llm)
        handler = agent.run()
        step = 40
        async for event in handler.stream_events():
            step = min(step + 10, 90)
            await manager.broadcast({
                "type": "device_update", "serial": serial, "progress": step,
                "log": {"time": now(), "msg": str(event)[:100], "type": ""}
            })

        result = await handler
        _done_evt = {
            "type": "task_complete", "serial": serial,
            "status": "online", "task": "idle", "progress": 100,
            "log": {"time": now(), "msg": f"✓ Done: {str(result)[:80]}", "type": "success"}
        }
        await manager.broadcast(_done_evt)
        await report_to_master(_done_evt)

    except Exception as e:
        logger.error(f"Task error on {serial}: {e}")
        _err_evt = {
            "type": "task_error", "serial": serial,
            "status": "online", "task": "idle", "progress": 0,
            "error": str(e)[:200],
            "log": {"time": now(), "msg": f"✗ Error: {str(e)}", "type": "error"}
        }
        await manager.broadcast(_err_evt)
        await report_to_master(_err_evt)




# ─── LLM Config ───────────────────────────────────────────────────────────────

llm_config = {
    "provider": "OpenAI",
    "model": "gpt-4o",
    "api_key": "",
    "ollama_url": "http://localhost:11434"
}

PROVIDER_DEFAULTS = {
    "OpenAI":    {"model": "gpt-4o",                "needs_key": True},
    "Anthropic": {"model": "claude-sonnet-4-5",      "needs_key": True},
    "Groq":      {"model": "llama-3.3-70b-versatile","needs_key": True},
    "Gemini":    {"model": "gemini-2.0-flash",        "needs_key": True},
    "Ollama":    {"model": "qwen2.5:14b",            "needs_key": False},
}

# ─── Auto-install Portal on new devices ──────────────────────────────────────

known_devices: set[str] = set()          # serials we've already seen
setup_in_progress: set[str] = set()      # serials currently being setup


async def portal_already_installed(serial: str) -> bool:
    """Check if Portal APK is already installed on device."""
    output = adb_cmd(["shell", "pm", "list", "packages", "com.droidrun.portal"], serial)
    installed = "com.droidrun.portal" in output
    logger.info(f"Portal installed on {serial}: {installed}")
    return installed



PORTAL_A11Y = "com.droidrun.portal/com.droidrun.portal.service.DroidrunAccessibilityService"


async def enable_accessibility(serial: str):
    """Try to enable Portal accessibility service via ADB (stock + root)."""

    # Check if already active
    current = adb_cmd(["shell", "settings", "get", "secure", "enabled_accessibility_services"], serial)
    if "com.droidrun.portal" in current:
        logger.info(f"✓ Accessibility already active on {serial}")
        await manager.broadcast({
            "type": "device_update", "serial": serial,
            "log": {"time": now(), "msg": "✓ Accessibility already active", "type": "success"}
        })
        return

    await manager.broadcast({
        "type": "device_update", "serial": serial,
        "log": {"time": now(), "msg": "⚙ Enabling accessibility service...", "type": ""}
    })

    # Method 1 — stock Android (works on many Samsung, Pixel without root)
    existing = current.strip() if current.strip() not in ("null", "") else ""
    new_val = f"{existing}:{PORTAL_A11Y}" if existing else PORTAL_A11Y

    r1 = adb_cmd(["shell", "settings", "put", "secure", "enabled_accessibility_services", new_val], serial)
    # Also enable a11y globally
    adb_cmd(["shell", "settings", "put", "secure", "accessibility_enabled", "1"], serial)

    # Verify
    verify = adb_cmd(["shell", "settings", "get", "secure", "enabled_accessibility_services"], serial)
    if "com.droidrun.portal" in verify:
        logger.info(f"✓ Accessibility enabled (stock method) on {serial}")
        await manager.broadcast({
            "type": "device_update", "serial": serial,
            "log": {"time": now(), "msg": "✓ Accessibility enabled automatically", "type": "success"}
        })
        return

    # Method 2 — root via `su`
    root_cmd = f"su -c \'settings put secure enabled_accessibility_services {new_val}\'"
    adb_cmd(["shell", root_cmd], serial)
    adb_cmd(["shell", "su", "-c", "settings put secure accessibility_enabled 1"], serial)

    verify2 = adb_cmd(["shell", "settings", "get", "secure", "enabled_accessibility_services"], serial)
    if "com.droidrun.portal" in verify2:
        logger.info(f"✓ Accessibility enabled (root method) on {serial}")
        await manager.broadcast({
            "type": "device_update", "serial": serial,
            "log": {"time": now(), "msg": "✓ Accessibility enabled via root", "type": "success"}
        })
        return

    # Both failed — notify user to do it manually
    logger.warning(f"Could not auto-enable accessibility on {serial} — manual action needed")
    await manager.broadcast({
        "type": "device_update", "serial": serial,
        "log": {"time": now(), "msg": "⚠ Enable accessibility manually: Settings → Accessibility → Portal", "type": ""}
    })


async def auto_setup_device(serial: str):
    """Install Portal APK automatically when a new device is detected."""
    if serial in setup_in_progress:
        return
    setup_in_progress.add(serial)

    logger.info(f"🔌 New device detected: {serial} — checking Portal...")
    await manager.broadcast({
        "type": "device_update",
        "serial": serial,
        "log": {"time": now(), "msg": "🔌 New device — checking Portal...", "type": "success"}
    })

    # Check if Portal is already installed
    already_installed = await portal_already_installed(serial)

    if already_installed:
        logger.info(f"✓ Portal already installed on {serial} — checking accessibility")
        await manager.broadcast({
            "type": "device_update",
            "serial": serial,
            "log": {"time": now(), "msg": "✓ Portal installed — checking accessibility...", "type": "success"}
        })
        await enable_accessibility(serial)
        setup_in_progress.discard(serial)
        return
    else:
        await manager.broadcast({
            "type": "device_update",
            "serial": serial,
            "log": {"time": now(), "msg": "📦 Portal not found — installing...", "type": ""}
        })

    try:
        # Find htb-agent CLI
        import sys
        htb_agent_bin = os.path.join(os.path.dirname(sys.executable), "htb-agent")
        if not os.path.isfile(htb_agent_bin):
            htb_agent_bin = "htb-agent"

        logger.info(f"Running setup for {serial} using {htb_agent_bin}")

        proc = await asyncio.create_subprocess_exec(
            htb_agent_bin, "setup", "--device", serial,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "PATH": f"/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH','')}"}
        )

        # Stream setup output line by line to dashboard
        async for line in proc.stdout:
            line_str = line.decode().strip()
            if line_str:
                logger.info(f"[setup:{serial}] {line_str}")
                await manager.broadcast({
                    "type": "device_update",
                    "serial": serial,
                    "log": {"time": now(), "msg": line_str, "type": ""}
                })

        await proc.wait()

        if proc.returncode == 0:
            logger.info(f"✓ Auto-setup complete for {serial}")
            await manager.broadcast({
                "type": "device_update",
                "serial": serial,
                "log": {"time": now(), "msg": "✓ Portal installed", "type": "success"}
            })
        else:
            logger.warning(f"Setup exited with code {proc.returncode} for {serial}")
            await manager.broadcast({
                "type": "device_update",
                "serial": serial,
                "log": {"time": now(), "msg": f"⚠ Setup finished (code {proc.returncode})", "type": ""}
            })


    except Exception as e:
        logger.error(f"Auto-setup failed for {serial}: {e}")
        await manager.broadcast({
            "type": "device_update",
            "serial": serial,
            "log": {"time": now(), "msg": f"✗ Setup error: {str(e)}", "type": "error"}
        })
    finally:
        setup_in_progress.discard(serial)


async def device_watcher():
    """Background task — watches for new devices and triggers auto-setup."""
    global known_devices
    logger.info("Device watcher started — auto-setup enabled")

    while True:
        try:
            current = get_connected_devices()
            current_serials = {d["serial"] for d in current}

            # Find newly connected devices
            new_serials = current_serials - known_devices
            removed_serials = known_devices - current_serials

            for serial in new_serials:
                asyncio.create_task(auto_setup_device(serial))

            # Only broadcast and log when devices change
            if new_serials or removed_serials:
                logger.info(f"Device change — new: {new_serials}, removed: {removed_serials}")
                await manager.broadcast({"type": "init", "devices": current})

            known_devices = current_serials

        except Exception as e:
            logger.error(f"Device watcher error: {e}")

        await asyncio.sleep(30)


@app.on_event("startup")
async def startup():
    """Start background device watcher on server startup."""
    # Seed known_devices with already-connected devices so we don't
    # re-setup devices that were connected before the server started
    existing = get_connected_devices()
    for d in existing:
        known_devices.add(d["serial"])
    logger.info(f"Startup — found {len(existing)} existing device(s), skipping auto-setup for them")
    asyncio.create_task(device_watcher())

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(os.path.join(dashboard_path, "index.html"))


@app.get("/os-spotify")
@app.get("/os-spotify.html")
async def os_spotify():
    return FileResponse(os.path.join(dashboard_path, "os-spotify.html"))

@app.get("/api/devices")
async def get_devices():
    devices = get_connected_devices()
    return JSONResponse({"devices": devices, "count": len(devices)})

@app.post("/api/devices/connect")
async def connect_device(body: dict):
    address = body.get("address", "")
    if not address:
        return JSONResponse({"error": "address required"}, status_code=400)
    result = adb_cmd(["connect", address])
    success = "connected" in result.lower()
    await manager.broadcast({"type": "device_connected", "address": address, "success": success})
    return JSONResponse({"success": success, "message": result})

@app.post("/api/devices/refresh")
async def refresh_devices():
    devices = get_connected_devices()
    await manager.broadcast({"type": "init", "devices": devices})
    return JSONResponse({"devices": devices})

@app.get("/api/devices/{serial}/screenshot")
async def screenshot(serial: str):
    """Return a single screenshot as JPEG."""
    proc = await asyncio.create_subprocess_exec(
        ADB, "-s", serial, "exec-out", "screencap", "-p",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )
    png_data, _ = await proc.communicate()
    if not png_data:
        return JSONResponse({"error": "Failed to capture screenshot"}, status_code=500)
    return Response(content=png_data, media_type="image/png")

class RunTaskBody(BaseModel):
    serial: str
    task: str

@app.post("/api/run")
async def run_task(body: RunTaskBody):
    if body.serial in running_tasks and not running_tasks[body.serial].done():
        return JSONResponse({"error": "Device is already running a task"}, status_code=409)
    task = asyncio.create_task(run_agent_task(body.serial, body.task))
    running_tasks[body.serial] = task
    return JSONResponse({"status": "started", "serial": body.serial, "task": body.task})

class BroadcastBody(BaseModel):
    task: str
    target: str = "online"
    serials: list[str] = []
    concurrency: int = 0  # 0 = unlimited

@app.post("/api/broadcast")
async def broadcast_task(body: BroadcastBody, request: Request):
    if not check_node_token(request):
        return JSONResponse({"error": "Unauthorized — invalid node token"}, status_code=401)
    devices = get_connected_devices()
    targets = body.serials if body.target == "selected" else [d["serial"] for d in devices]
    # Filter out devices already running
    targets = [s for s in targets if s not in running_tasks or running_tasks[s].done()]

    concurrency = body.concurrency if body.concurrency > 0 else len(targets)
    started = []

    async def run_with_concurrency():
        sem = asyncio.Semaphore(concurrency)
        async def run_one(serial):
            async with sem:
                await run_agent_task(serial, body.task)
        await asyncio.gather(*[run_one(s) for s in targets])

    # Create a master task that manages concurrency
    master = asyncio.create_task(run_with_concurrency())
    # Also store individual handles for stop support
    for serial in targets:
        started.append(serial)

    # Store master broadcast task so it can be cancelled
    running_tasks["__broadcast__"] = master

    return JSONResponse({"started": started, "count": len(started), "concurrency": concurrency})


@app.post("/api/stop/{serial}")
async def stop_task(serial: str, request: Request):
    if not check_node_token(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    """Stop a running task on a specific device."""
    if serial == "all":
        # Stop broadcast master
        if "__broadcast__" in running_tasks:
            running_tasks["__broadcast__"].cancel()
            del running_tasks["__broadcast__"]
        # Stop all individual tasks
        stopped = []
        for s, task in list(running_tasks.items()):
            if not task.done():
                task.cancel()
                stopped.append(s)
                await manager.broadcast({
                    "type": "device_update", "serial": s,
                    "status": "online", "task": "idle", "progress": 0,
                    "log": {"time": now(), "msg": "⏹ Task stopped by user", "type": "error"}
                })
        running_tasks.clear()
        return JSONResponse({"stopped": stopped, "count": len(stopped)})
    else:
        task = running_tasks.get(serial)
        if task and not task.done():
            task.cancel()
            del running_tasks[serial]
            await manager.broadcast({
                "type": "device_update", "serial": serial,
                "status": "online", "task": "idle", "progress": 0,
                "log": {"time": now(), "msg": "⏹ Task stopped by user", "type": "error"}
            })
            return JSONResponse({"stopped": serial})
        return JSONResponse({"error": "No running task found"}, status_code=404)

@app.post("/api/devices/scan")
async def manual_scan():
    """Manually trigger device scan and auto-setup for new devices."""
    current = get_connected_devices()
    current_serials = {d["serial"] for d in current}
    new_serials = current_serials - known_devices
    for serial in new_serials:
        asyncio.create_task(auto_setup_device(serial))
    known_devices.update(current_serials)
    await manager.broadcast({"type": "init", "devices": current})
    logger.info(f"Manual scan — {len(current)} devices, {len(new_serials)} new")
    return JSONResponse({"devices": len(current), "new": len(new_serials), "serials": list(new_serials)})





@app.post("/api/set-token")
async def set_node_token(request: Request):
    """Called by master after registration to set this node's auth token."""
    global NODE_TOKEN
    # Only allow if no token set yet, or if current token matches
    incoming = request.headers.get("X-Node-Token", "")
    body = await request.json()
    new_token = body.get("token", "")
    if not new_token:
        return JSONResponse({"error": "No token provided"}, status_code=400)
    if NODE_TOKEN and incoming != NODE_TOKEN:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    NODE_TOKEN = new_token
    logger.info(f"Node token updated by master")
    return JSONResponse({"ok": True, "token_set": True})

# ─── Node identity (used by Master to register & health-check this node) ─────

@app.get("/api/ping")
async def ping():
    import platform
    devices = get_connected_devices()
    return JSONResponse({
        "status": "ok",
        "role": "node",
        "hostname": platform.node(),
        "version": "1.0.0",
        "devices": len(devices),
        "serials": [d["serial"] for d in devices],
        "provider": llm_config.get("provider", "Ollama"),
        "model": llm_config.get("model", "qwen2.5:14b"),
        "ollama_url": llm_config.get("ollama_url", "http://localhost:11434"),
        "token_set": bool(NODE_TOKEN),
    })


# ─── LLM Config endpoints ────────────────────────────────────────────────────

class LLMConfigBody(BaseModel):
    provider: str
    model: str
    api_key: str = ""
    ollama_url: str = "http://localhost:11434"

@app.get("/api/config")
async def get_config():
    safe = {**llm_config}
    if safe.get("api_key"):
        safe["api_key"] = safe["api_key"][:4] + "••••••••"
    return JSONResponse(safe)

@app.post("/api/config")
async def set_config(body: LLMConfigBody):
    global llm_config
    llm_config["provider"] = body.provider
    llm_config["model"] = body.model
    llm_config["ollama_url"] = body.ollama_url
    if body.api_key and not body.api_key.endswith("••••••••"):
        llm_config["api_key"] = body.api_key
    logger.info(f"LLM config updated — provider:{body.provider} model:{body.model}")
    await manager.broadcast({"type": "config_updated", "provider": body.provider, "model": body.model})
    return JSONResponse({"ok": True, "provider": body.provider, "model": body.model})


# ─── MJPEG stream ─────────────────────────────────────────────────────────────

_MJPEG_BOUNDARY = b"--mjpegframe\r\nContent-Type: image/jpeg\r\n\r\n"

# Shared frame buffers: serial → (jpeg_bytes, timestamp)
# Multiple browser clients for the same serial reuse the same captured frame.
_frame_cache: dict[str, tuple[bytes, float]] = {}
_frame_lock: dict[str, asyncio.Lock] = {}
_capture_tasks: dict[str, asyncio.Task] = {}


def _screencap_sync(serial: str, width: int, quality: int) -> bytes | None:
    """Run screencap in a thread-pool worker. Returns JPEG bytes or None."""
    try:
        result = subprocess.run(
            [ADB, "-s", serial, "exec-out", "screencap", "-p"],
            capture_output=True, timeout=6,
        )
        png_data = result.stdout
        if not png_data or len(png_data) < 1000:
            return None
        if HAS_PILLOW:
            img = Image.open(io.BytesIO(png_data))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            orig_w, orig_h = img.size
            new_h = int(orig_h * width / orig_w) & ~1
            img = img.resize((width, new_h), Image.BILINEAR)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=False)
            return buf.getvalue()
        return png_data
    except Exception as exc:
        logger.debug(f"screencap_sync ({serial}): {exc}")
        return None


async def _capture_loop(serial: str, width: int, quality: int) -> None:
    """
    Background task: continuously captures frames for one device.
    Shared by all concurrent stream clients for the same serial.
    """
    if serial not in _frame_lock:
        _frame_lock[serial] = asyncio.Lock()
    try:
        while True:
            t0 = asyncio.get_event_loop().time()
            frame = await asyncio.to_thread(_screencap_sync, serial, width, quality)
            if frame:
                async with _frame_lock[serial]:
                    _frame_cache[serial] = (frame, t0)
            await asyncio.sleep(0)  # yield to event loop; screencap already took ~400ms
    except (asyncio.CancelledError, GeneratorExit):
        pass
    finally:
        _frame_cache.pop(serial, None)
        _capture_tasks.pop(serial, None)


async def _mjpeg_generator(serial: str, width: int, quality: int):
    """
    Yields MJPEG chunks.  Multiple concurrent viewers for the same device
    share a single background capture task so ADB is only called once.
    The capture always uses the highest requested width; clients receiving
    a larger frame than their target can display it at their CSS size.
    """
    # One shared task per device regardless of resolution
    if serial not in _capture_tasks or _capture_tasks[serial].done():
        _capture_tasks[serial] = asyncio.create_task(
            _capture_loop(serial, width, quality), name=f"capture-{serial}"
        )
    # else: reuse running task — same device, frame cache is shared

    last_ts: float = 0.0
    try:
        while True:
            entry = _frame_cache.get(serial)
            if entry and entry[1] > last_ts:
                last_ts = entry[1]
                yield _MJPEG_BOUNDARY + entry[0] + b"\r\n"
            else:
                await asyncio.sleep(0.05)  # wait for new frame
    except (asyncio.CancelledError, GeneratorExit):
        pass


@app.get("/api/devices/{serial}/stream")
async def stream_device(
    serial: str,
    w: int = 720,       # ?w=360 for grid thumbnails, ?w=720 for full view
    q: int = 75,        # JPEG quality
):
    """MJPEG live stream for a device via ADB screencap."""
    width   = max(180, min(w, 1440))
    quality = max(30, min(q, 95))
    return StreamingResponse(
        _mjpeg_generator(serial, width, quality),
        media_type="multipart/x-mixed-replace; boundary=mjpegframe",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection":    "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ─── scrcpy-server streaming (H.264 → WebCodecs in browser) ─────────────────

class ScrcpySession:
    """
    One scrcpy-server session per device.  Many browser clients subscribe to
    the same session so the device is only streamed once per node.

    Lifecycle:
        get_or_create(serial) → starts server + reader task
        subscribe()           → returns a Queue that receives binary packets
        unsubscribe(q)        → removes that subscriber
        stop()                → kills the server process and cleans up
    """

    _sessions: dict[str, "ScrcpySession"] = {}
    _port_map:  dict[str, int]            = {}
    _port_counter: int                    = _PORT_BASE

    # ── class-level helpers ───────────────────────────────────────────────────

    @classmethod
    def _alloc_port(cls, serial: str) -> int:
        if serial not in cls._port_map:
            cls._port_map[serial] = cls._port_counter
            cls._port_counter += 1
        return cls._port_map[serial]

    @classmethod
    async def get_or_create(cls, serial: str) -> "ScrcpySession":
        existing = cls._sessions.get(serial)
        if existing and not existing._dead:
            return existing
        session = cls(serial)
        cls._sessions[serial] = session
        await session._start()
        return session

    # ── instance ──────────────────────────────────────────────────────────────

    def __init__(self, serial: str):
        self.serial  = serial
        self.port    = ScrcpySession._alloc_port(serial)
        self.width   = 0
        self.height  = 0
        self._dead   = False
        self._shell  = None          # adb shell subprocess
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task:   asyncio.Task | None         = None
        self._subs:   list[asyncio.Queue]         = []
        self._config: bytes | None                = None  # last SPS/PPS payload

    # ── startup ───────────────────────────────────────────────────────────────

    async def _start(self) -> None:
        if not SCRCPY_SERVER_LOCAL:
            raise RuntimeError("scrcpy-server.jar not found — is scrcpy installed?")

        # 1. Push server .jar to device (skip if already there)
        await asyncio.to_thread(self._push_jar)

        # 2. Kill any leftover server process on the device
        subprocess.run(
            [ADB, "-s", self.serial, "shell",
             "pkill -f scrcpy-server 2>/dev/null; true"],
            capture_output=True,
        )

        # 3. Remove stale adb forward
        subprocess.run(
            [ADB, "-s", self.serial, "forward", "--remove", f"tcp:{self.port}"],
            capture_output=True,
        )

        # 4. Set up adb forward
        r = subprocess.run(
            [ADB, "-s", self.serial, "forward",
             f"tcp:{self.port}", "localabstract:scrcpy"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"adb forward failed for {self.serial}: {r.stderr.strip()}")

        # 5. Launch scrcpy-server on device
        cmd = (
            f"CLASSPATH={SCRCPY_SERVER_DEVICE} "
            f"app_process / com.genymobile.scrcpy.Server {SCRCPY_SERVER_VER} "
            f"log_level=error "
            f"video_codec=h264 "
            f"max_size=720 "
            f"max_fps=20 "
            f"bit_rate=2000000 "
            f"send_device_meta=true "
            f"send_dummy_byte=false "
            f"control=false "
            f"tunnel_forward=true "
            f"audio=false "
            f"video=true "
            f"cleanup=true "
            f"power_off_on_close=false"
        )
        self._shell = await asyncio.create_subprocess_shell(
            f"{ADB} -s {self.serial} shell {cmd}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        # 6. Wait for server to be ready and connect
        await asyncio.sleep(0.6)
        self._reader, self._writer = await self._connect_with_retry()

        # 7. Read device metadata.
        #    scrcpy ≥3.0 format (76 bytes):
        #      64 bytes device name  +  4 bytes codec ASCII ("h264"/"hevc"/"av1 ")
        #      +  4 bytes width (uint32 BE)  +  4 bytes height (uint32 BE)
        meta = await asyncio.wait_for(self._reader.readexactly(76), timeout=5.0)
        self.width  = struct.unpack(">I", meta[68:72])[0]
        self.height = struct.unpack(">I", meta[72:76])[0]
        logger.info(
            f"scrcpy-server [{self.serial}] ready "
            f"{self.width}x{self.height} @ port {self.port}"
        )

        # 8. Start background reader task
        self._task = asyncio.create_task(
            self._read_loop(), name=f"scrcpy-{self.serial}"
        )

    def _push_jar(self) -> None:
        """Push scrcpy-server.jar to device if not present (runs in thread)."""
        check = subprocess.run(
            [ADB, "-s", self.serial, "shell", "ls", "-l", SCRCPY_SERVER_DEVICE],
            capture_output=True, text=True,
        )
        if "No such file" in check.stdout or check.returncode != 0:
            result = subprocess.run(
                [ADB, "-s", self.serial, "push",
                 SCRCPY_SERVER_LOCAL, SCRCPY_SERVER_DEVICE],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                raise RuntimeError(f"push scrcpy-server failed: {result.stderr}")
            logger.info(f"scrcpy-server.jar pushed to {self.serial}")

    async def _connect_with_retry(
        self, retries: int = 8, delay: float = 0.35
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        last_err: Exception = RuntimeError("no attempts made")
        for _ in range(retries):
            try:
                return await asyncio.open_connection("127.0.0.1", self.port)
            except (ConnectionRefusedError, OSError) as e:
                last_err = e
                await asyncio.sleep(delay)
        raise RuntimeError(
            f"Cannot connect to scrcpy-server on {self.serial}:{self.port}: {last_err}"
        )

    # ── read loop ─────────────────────────────────────────────────────────────

    async def _read_loop(self) -> None:
        """
        Continuously reads H.264 packets from scrcpy-server and fans them
        out to all active subscriber queues.

        Binary message format sent to subscribers:
            [1 byte: type]  0=config  1=keyframe  2=delta
            [8 bytes: PTS big-endian uint64]
            [N bytes: H.264 Annex-B payload]
        """
        try:
            while not self._dead:
                # 12-byte packet header
                header = await asyncio.wait_for(
                    self._reader.readexactly(12), timeout=8.0
                )
                pts_raw = struct.unpack(">Q", header[:8])[0]
                length  = struct.unpack(">I", header[8:12])[0]

                is_config   = bool(pts_raw & _PKT_FLAG_CONFIG)
                is_keyframe = bool(pts_raw & _PKT_FLAG_KEYFRAME)
                pts         = pts_raw & ~(_PKT_FLAG_CONFIG | _PKT_FLAG_KEYFRAME)

                payload = await asyncio.wait_for(
                    self._reader.readexactly(length), timeout=8.0
                )

                if is_config:
                    self._config = payload     # cache SPS/PPS for reconnecting clients
                    ptype = 0
                elif is_keyframe:
                    ptype = 1
                else:
                    ptype = 2

                msg = struct.pack(">BQ", ptype, pts) + payload
                self._broadcast(msg)

        except (asyncio.CancelledError, asyncio.IncompleteReadError, ConnectionError):
            pass
        except asyncio.TimeoutError:
            logger.warning(f"scrcpy read timeout for {self.serial}")
        except Exception as e:
            logger.warning(f"scrcpy read_loop [{self.serial}]: {e}")
        finally:
            self._dead = True
            ScrcpySession._sessions.pop(self.serial, None)
            await self._cleanup()

    def _broadcast(self, msg: bytes) -> None:
        dead: list[asyncio.Queue] = []
        for q in self._subs:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass   # client too slow — drop frame, never block
            except Exception:
                dead.append(q)
        for q in dead:
            self._safe_remove(q)

    # ── pub/sub ───────────────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        """Return a new Queue that will receive binary video packets."""
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=6)
        self._subs.append(q)
        # Immediately send the cached config so a new client can init decoder
        if self._config is not None:
            cached_msg = struct.pack(">BQ", 0, 0) + self._config
            try:
                q.put_nowait(cached_msg)
            except asyncio.QueueFull:
                pass
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._safe_remove(q)
        if not self._subs:
            # No more clients — schedule cleanup after a short grace period
            asyncio.create_task(self._deferred_stop(5.0))

    def _safe_remove(self, q: asyncio.Queue) -> None:
        try:
            self._subs.remove(q)
        except ValueError:
            pass

    # ── cleanup ───────────────────────────────────────────────────────────────

    async def _deferred_stop(self, grace: float) -> None:
        await asyncio.sleep(grace)
        if not self._subs:   # still no clients after grace period
            await self.stop()

    async def stop(self) -> None:
        self._dead = True
        ScrcpySession._sessions.pop(self.serial, None)
        if self._task and not self._task.done():
            self._task.cancel()
        await self._cleanup()

    async def _cleanup(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        if self._shell:
            try:
                self._shell.kill()
                await self._shell.wait()
            except Exception:
                pass
            self._shell = None
        subprocess.run(
            [ADB, "-s", self.serial, "forward", "--remove", f"tcp:{self.port}"],
            capture_output=True,
        )
        # Kill the server process on device
        subprocess.run(
            [ADB, "-s", self.serial, "shell",
             "pkill -f scrcpy-server 2>/dev/null; true"],
            capture_output=True,
        )
        logger.info(f"scrcpy-server [{self.serial}] stopped")


@app.websocket("/ws/scrcpy/{serial}")
async def scrcpy_ws(ws: WebSocket, serial: str):
    """
    WebSocket endpoint that delivers raw H.264 packets to the browser.
    The browser uses the WebCodecs API to decode them into a <canvas>.

    Message format (binary):
        byte 0   : packet type  0=codec-config  1=key-frame  2=delta-frame
        bytes 1–8: PTS microseconds (uint64 big-endian)
        bytes 9+  : H.264 Annex-B payload

    First text message after connect:
        {"type": "meta", "width": W, "height": H, "codec": "h264"}
    """
    await ws.accept()
    session: ScrcpySession | None = None
    q: asyncio.Queue | None = None
    try:
        session = await ScrcpySession.get_or_create(serial)

        # Send device metadata so the browser can size the canvas
        await ws.send_json({
            "type":   "meta",
            "width":  session.width,
            "height": session.height,
            "codec":  "h264",
        })

        q = session.subscribe()
        logger.info(f"scrcpy-ws [{serial}] client connected")

        while True:
            try:
                packet = await asyncio.wait_for(q.get(), timeout=8.0)
                await ws.send_bytes(packet)
            except asyncio.TimeoutError:
                # Send a keepalive ping so the browser doesn't close the WS
                try:
                    await ws.send_json({"type": "ping"})
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"scrcpy-ws [{serial}]: {e}")
    finally:
        if session and q is not None:
            session.unsubscribe(q)
        logger.info(f"scrcpy-ws [{serial}] client disconnected")


# ─── Screen stream WebSocket ──────────────────────────────────────────────────

@app.websocket("/ws/screen/{serial}")
async def screen_ws(ws: WebSocket, serial: str):
    await ws.accept()
    logger.info(f"Screen stream requested for {serial}")
    start_stream(serial, ws)
    try:
        while True:
            # Keep alive — client can send "stop" to end
            data = await ws.receive_text()
            if data == "stop":
                break
    except WebSocketDisconnect:
        pass
    finally:
        stop_stream(serial, ws)
        logger.info(f"Screen stream WS closed for {serial}")

# ─── Main WebSocket ────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    logger.info("Dashboard connected via WebSocket")
    refresh_task = None
    try:
        devices = get_connected_devices()
        await ws.send_json({"type": "init", "devices": devices})

        # Device watcher handles auto-refresh globally
        refresh_task = None

        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info("Dashboard disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        manager.disconnect(ws)
        if refresh_task:
            refresh_task.cancel()

# ─── Spotify Automation ───────────────────────────────────────────────────────

# serial → SpotifySessionState (for status reporting)
_spotify_states: dict[str, object] = {}


def _build_llm_for_spotify(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    ollama_url: str | None = None,
):
    """Build a LLM for Spotify. Falls back to node llm_config when params are absent."""
    from htb_agent.agent.utils.llm_picker import load_llm

    _provider   = provider or llm_config["provider"]
    _model      = model    or llm_config["model"]
    _ollama_url = ollama_url or llm_config["ollama_url"]
    _api_key    = (
        api_key
        or llm_config["api_key"]
        or os.getenv("OPENAI_API_KEY", "")
        or os.getenv("ANTHROPIC_API_KEY", "")
        or os.getenv("GROQ_API_KEY", "")
        or os.getenv("GEMINI_API_KEY", "")
    )
    if _provider != "Ollama" and not _api_key:
        raise ValueError(
            f"No API key for {_provider}. Enter it in the LLM Provider field "
            f"or set it in Fleet > Settings."
        )
    if _provider == "Ollama":
        return load_llm("Ollama", model=_model, base_url=_ollama_url)
    return load_llm(_provider, model=_model, api_key=_api_key)


async def _run_spotify_for_serial(
    serial: str,
    playlists: list[str],
    listen_min_sec: float,
    listen_max_sec: float,
    tracks_min: int,
    tracks_max: int,
    total_duration_sec: float,
    llm_max_steps_per_tick: int,
    llm_concurrency: int,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    llm_api_key: str | None = None,
    llm_ollama_url: str | None = None,
) -> None:
    from htb_agent.spotify.state import SpotifySessionState
    from htb_agent.spotify.runner import spotify_automation_loop
    from htb_agent.tools.driver.android import AndroidDriver
    from datetime import datetime

    def _now() -> str:
        return datetime.now().strftime("%H:%M:%S")

    state = SpotifySessionState(
        serial=serial,
        playlists=playlists,
        listen_min_sec=listen_min_sec,
        listen_max_sec=listen_max_sec,
        tracks_min=tracks_min,
        tracks_max=tracks_max,
        total_duration_sec=total_duration_sec,
        llm_max_steps_per_tick=llm_max_steps_per_tick,
    )
    _spotify_states[serial] = state

    async def _err(msg: str) -> None:
        evt = {
            "type": "task_error",
            "serial": serial,
            "status": "online",
            "task": "idle",
            "progress": 0,
            "error": msg[:200],
            "log": {"time": _now(), "msg": msg, "type": "error"},
        }
        await manager.broadcast(evt)
        await report_to_master(evt)

    try:
        state.phase = "connecting"
        driver = AndroidDriver(serial=serial)
        await driver.connect()

        # driver.connect() already handles Portal setup — no extra health check needed
        llm = _build_llm_for_spotify(
            provider=llm_provider,
            model=llm_model,
            api_key=llm_api_key,
            ollama_url=llm_ollama_url,
        )

        await spotify_automation_loop(
            state=state,
            adb_bin=ADB,
            llm=llm,
            driver=driver,
            broadcast=manager.broadcast,
            report=report_to_master,
            llm_concurrency=llm_concurrency,
        )
    except asyncio.CancelledError:
        state.phase = "done"
        state.cancelled = True
        await _err(f"⏹ Stopped (played {state.total_tracks_played} tracks)")
        raise
    except Exception as exc:
        state.phase = "done"
        state.last_error = str(exc)
        logger.error(f"Spotify [{serial}]: {exc}")
        await _err(f"✗ Session failed: {exc}")
    finally:
        _spotify_states.pop(serial, None)


class SpotifyStartBody(BaseModel):
    playlists: list[str]
    listen_min_sec: float = 45.0
    listen_max_sec: float = 60.0
    tracks_min: int = 15
    tracks_max: int = 20
    total_duration_minutes: float = 120.0
    llm_max_steps_per_tick: int = 15
    llm_concurrency: int = 10
    target: str = "online"       # "online" | "selected" | "all"
    serials: list[str] = []      # used only when target == "selected"
    concurrency: int = 0         # max parallel devices (0 = all at once)
    # LLM override — if omitted the node's Fleet settings are used
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_ollama_url: str | None = None


@app.post("/api/spotify/start")
async def spotify_start(body: SpotifyStartBody):
    if not body.playlists:
        return JSONResponse({"error": "At least one playlist URL is required"}, status_code=400)

    devices = get_connected_devices()

    if body.target == "selected":
        targets = [s for s in body.serials if s]
    elif body.target == "all":
        targets = [d["serial"] for d in devices]
    else:  # "online"
        targets = [d["serial"] for d in devices if d["status"] != "offline"]

    # exclude already running
    targets = [s for s in targets if s not in running_tasks or running_tasks[s].done()]
    if not targets:
        return JSONResponse({"error": "No available devices match the target"}, status_code=409)

    total_sec = body.total_duration_minutes * 60.0
    device_concurrency = body.concurrency if body.concurrency > 0 else len(targets)

    async def _run_with_sem():
        sem = asyncio.Semaphore(device_concurrency)
        async def _one(serial: str):
            async with sem:
                await _run_spotify_for_serial(
                    serial=serial,
                    playlists=body.playlists,
                    listen_min_sec=body.listen_min_sec,
                    listen_max_sec=body.listen_max_sec,
                    tracks_min=body.tracks_min,
                    tracks_max=body.tracks_max,
                    total_duration_sec=total_sec,
                    llm_max_steps_per_tick=body.llm_max_steps_per_tick,
                    llm_concurrency=body.llm_concurrency,
                    llm_provider=body.llm_provider,
                    llm_model=body.llm_model,
                    llm_api_key=body.llm_api_key,
                    llm_ollama_url=body.llm_ollama_url,
                )
        await asyncio.gather(*[_one(s) for s in targets], return_exceptions=True)

    master = asyncio.create_task(_run_with_sem())
    running_tasks["__spotify__"] = master
    for serial in targets:
        running_tasks[serial] = master  # allow individual stop via existing endpoint

    logger.info(f"Spotify session started — {len(targets)} device(s), {body.total_duration_minutes}min")
    return JSONResponse({
        "started": targets,
        "count": len(targets),
        "total_duration_minutes": body.total_duration_minutes,
        "listen_range": [body.listen_min_sec, body.listen_max_sec],
        "tracks_range": [body.tracks_min, body.tracks_max],
    })


@app.get("/api/spotify/status")
async def spotify_status():
    result = {}
    for serial, state in _spotify_states.items():
        result[serial] = state.to_status_dict()
    return JSONResponse(result)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8888, reload=True)
