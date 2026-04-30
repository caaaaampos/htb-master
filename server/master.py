"""
HTB Agent — Master Server
Runs on Mac Studio. Manages rack node registry and fleet commands.
"""

import asyncio
import hashlib
import json
import logging
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path
import sqlite3
import threading

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("htb-master")

# ── Auth config ───────────────────────────────────────────────────────────────
# Change MASTER_PASSWORD to your own password
MASTER_PASSWORD = os.environ.get("HTB_MASTER_PASSWORD", "KonejoBlanco$$23")
MASTER_PASSWORD_HASH = hashlib.sha256(MASTER_PASSWORD.encode()).hexdigest()
sessions: set[str] = set()   # active session tokens
SCREENWALL_TOKEN = os.environ.get("HTB_SCREENWALL_TOKEN", "screenwall-htb-2024")

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def new_session() -> str:
    token = secrets.token_hex(32)
    sessions.add(token)
    return token

def valid_session(request: Request) -> bool:
    token = request.cookies.get("htb_session")
    return token in sessions

def require_auth(request: Request):
    """Dependency — redirects to login if not authenticated."""
    if not valid_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

from fastapi import HTTPException

app = FastAPI(title="HTB Agent Master", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Static files ──────────────────────────────────────────────────────────────
dashboard_path = os.path.join(os.path.dirname(__file__), "..", "dashboard")
app.mount("/static", StaticFiles(directory=dashboard_path), name="static")

# ── Login endpoints ──────────────────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>HTB MASTER — LOGIN</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#000;color:#00ff88;font-family:'Share Tech Mono',monospace;height:100vh;display:flex;align-items:center;justify-content:center}}
body::before{{content:'';position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,255,136,.01) 2px,rgba(0,255,136,.01) 3px);pointer-events:none}}
.box{{border:1px solid rgba(0,255,136,.3);padding:48px;width:400px;background:rgba(0,10,6,.9);box-shadow:0 0 40px rgba(0,255,136,.1)}}
.logo{{display:flex;align-items:center;gap:12px;margin-bottom:32px}}
.hex{{width:28px;height:28px;border:1px solid #00ff88;transform:rotate(45deg);box-shadow:0 0 10px rgba(0,255,136,.3)}}
.title{{font-size:18px;letter-spacing:.2em;text-shadow:0 0 12px rgba(0,255,136,.4)}}
.sub{{font-size:8px;color:rgba(0,255,136,.4);letter-spacing:.3em;margin-top:2px}}
.label{{font-size:8px;color:rgba(0,255,136,.4);letter-spacing:.2em;margin-bottom:8px}}
.field{{width:100%;background:#000;border:1px solid rgba(0,255,136,.2);color:#00ff88;font-family:'Share Tech Mono',monospace;font-size:14px;padding:10px 14px;outline:none;margin-bottom:20px;transition:border-color .15s}}
.field:focus{{border-color:#00ff88;box-shadow:0 0 10px rgba(0,255,136,.15)}}
.btn{{width:100%;padding:12px;background:rgba(0,255,136,.08);border:1px solid #00ff88;color:#00ff88;font-family:'Share Tech Mono',monospace;font-size:12px;letter-spacing:.2em;cursor:pointer;transition:all .15s}}
.btn:hover{{background:rgba(0,255,136,.15);box-shadow:0 0 16px rgba(0,255,136,.2)}}
.error{{color:#ff2244;font-size:10px;margin-bottom:16px;min-height:16px}}
</style>
</head>
<body>
<div class="box">
  <div class="logo"><div class="hex"></div><div><div class="title">HTB MASTER</div><div class="sub">FLEET COMMAND CENTER</div></div></div>
  <div class="label">PASSWORD</div>
  <div class="error">{error}</div>
  <form method="POST" action="/login">
    <input class="field" type="password" name="password" placeholder="Enter master password..." autofocus/>
    <button class="btn" type="submit">▶ ACCESS FLEET</button>
  </form>
</div>
</body>
</html>"""

@app.get("/login")
async def login_page(request: Request):
    if valid_session(request):
        return RedirectResponse("/", status_code=302)
    return HTMLResponse(LOGIN_HTML.format(error=""))

@app.post("/login")
async def login_submit(request: Request, response: Response):
    form = await request.form()
    pw = form.get("password", "")
    if hash_pw(pw) == MASTER_PASSWORD_HASH:
        token = new_session()
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie("htb_session", token, httponly=True, max_age=3600*8)  # 8 horas
        logger.info(f"Login successful from {request.client.host}")
        return resp
    logger.warning(f"Failed login attempt from {request.client.host}")
    return HTMLResponse(LOGIN_HTML.format(error="⚠ Invalid password"), status_code=401)

@app.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("htb_session")
    sessions.discard(token)
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("htb_session")
    return resp

@app.get("/")
async def root(request: Request):
    if not valid_session(request):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(os.path.join(dashboard_path, "master.html"))

@app.get("/master.html")
async def master_html(request: Request):
    if not valid_session(request):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(os.path.join(dashboard_path, "master.html"))

@app.get("/favicon.ico", status_code=204)
@app.get("/apple-touch-icon.png", status_code=204)
@app.get("/apple-touch-icon-precomposed.png", status_code=204)
async def no_icon():
    return None


@app.get("/screenwall")
@app.get("/screenwall.html")
async def screenwall():
    return FileResponse(os.path.join(dashboard_path, "screenwall.html"))

@app.get("/viewer")
@app.get("/viewer.html")
async def viewer(request: Request):
    if not valid_session(request):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(os.path.join(dashboard_path, "viewer.html"))

@app.get("/api/screenwall-token")
async def get_screenwall_token(request: Request, _=Depends(require_auth)):
    """Returns the screenwall read-only token — only accessible when logged in."""
    return JSONResponse({"token": SCREENWALL_TOKEN})

@app.get("/index.html")
async def index_redirect():
    return FileResponse(os.path.join(dashboard_path, "master.html"))

# ── Node Registry ─────────────────────────────────────────────────────────────
REGISTRY_FILE = Path(__file__).parent / "nodes.json"

def load_registry() -> dict:
    """Load node registry from disk."""
    if REGISTRY_FILE.exists():
        try:
            with open(REGISTRY_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load registry: {e}")
    return {}

def save_registry(nodes: dict):
    """Persist node registry to disk."""
    try:
        with open(REGISTRY_FILE, 'w') as f:
            json.dump(nodes, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save registry: {e}")

# node_id → { id, name, ip, port, status, devices, hostname, last_seen, ... }
# ── SQLite — task history + device state ─────────────────────────────────────
DB_FILE = Path(__file__).parent / "htb_history.db"
db_lock = threading.Lock()

def get_db():
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS task_history (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT NOT NULL,
                node_id   TEXT NOT NULL,
                serial    TEXT NOT NULL,
                device    TEXT,
                task      TEXT NOT NULL,
                status    TEXT NOT NULL,  -- running | done | error
                duration  INTEGER,        -- seconds
                error     TEXT,
                progress  INTEGER DEFAULT 0
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_ts     ON task_history(ts)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_node   ON task_history(node_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_status ON task_history(status)")
        db.commit()
    logger.info(f"DB ready: {DB_FILE}")

init_db()

def db_task_start(node_id: str, serial: str, device: str, task: str) -> int:
    with db_lock:
        with get_db() as db:
            cur = db.execute(
                "INSERT INTO task_history (ts, node_id, serial, device, task, status) VALUES (?,?,?,?,?,?)",
                (datetime.now().isoformat(), node_id, serial, device, task, "running")
            )
            db.commit()
            return cur.lastrowid

def db_task_done(row_id: int, status: str, error: str = None, progress: int = 100):
    if not row_id:
        return
    with db_lock:
        with get_db() as db:
            db.execute("""
                UPDATE task_history
                SET status=?, error=?, progress=?,
                    duration = CAST((julianday('now') - julianday(ts)) * 86400 AS INTEGER)
                WHERE id=?
            """, (status, error, progress, row_id))
            db.commit()

nodes: dict = load_registry()

# ── WebSocket Manager ─────────────────────────────────────────────────────────
class WSManager:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def broadcast(self, msg: dict):
        dead = set()
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except:
                dead.add(ws)
        self.clients -= dead

manager = WSManager()

def now() -> str:
    return datetime.now().strftime("%H:%M:%S")

# ── Node health checker ───────────────────────────────────────────────────────
async def ping_node(node: dict) -> dict:
    """Ping a rack node and return updated info."""
    url = f"http://{node['ip']}:{node['port']}/api/ping"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            data = r.json()
            return {
                **node,
                "status": "online",
                "devices": data.get("devices", 0),
                "hostname": data.get("hostname", node.get("hostname", "?")),
                "provider": data.get("provider", "?"),
                "model": data.get("model", "?"),
                "last_seen": now(),
            }
    except Exception as e:
        return {**node, "status": "offline", "last_seen": node.get("last_seen", "never")}


async def health_loop():
    """Periodically ping all registered nodes."""
    while True:
        await asyncio.sleep(15)
        if not nodes:
            continue
        changed = False
        for node_id, node in list(nodes.items()):
            updated = await ping_node(node)
            if updated["status"] != node.get("status"):
                changed = True
                logger.info(f"Node {node_id} status: {node.get('status')} → {updated['status']}")
            nodes[node_id] = updated

        if changed:
            save_registry(nodes)
            await manager.broadcast({"type": "nodes_update", "nodes": list(nodes.values())})


@app.on_event("startup")
async def startup():
    # Ping all existing nodes on startup
    logger.info(f"Master server starting — {len(nodes)} nodes in registry")
    for node_id, node in list(nodes.items()):
        updated = await ping_node(node)
        nodes[node_id] = updated
        logger.info(f"  {node_id} ({node['ip']}:{node['port']}) → {updated['status']}")
    asyncio.create_task(health_loop())


# ── Node Registry Endpoints ───────────────────────────────────────────────────

@app.get("/api/nodes")
async def get_nodes():
    return JSONResponse(list(nodes.values()))


class RegisterNodeBody(BaseModel):
    ip: str
    port: int = 8889
    name: str = ""


@app.post("/api/nodes/register")
async def register_node(body: RegisterNodeBody, request: Request, _=Depends(require_auth)):
    """Register a new rack node by IP:port. Pings it to verify."""
    node_id = f"RACK-{str(len(nodes)+1).padStart(2,'0')}" if False else f"RACK-{len(nodes)+1:02d}"

    # Check if already registered
    for nid, n in nodes.items():
        if n["ip"] == body.ip and n["port"] == body.port:
            # Re-ping existing node and update name if provided
            updated = await ping_node(n)
            if body.name:
                updated["name"] = body.name
            nodes[nid] = updated
            save_registry(nodes)
            await manager.broadcast({"type": "nodes_update", "nodes": list(nodes.values())})
            return JSONResponse({"ok": True, "node": updated, "existing": True})

    node_token = secrets.token_hex(24)   # unique token for this node
    candidate = {
        "id": node_id,
        "name": body.name or node_id,
        "ip": body.ip,
        "port": body.port,
        "status": "connecting",
        "devices": 0,
        "hostname": "",
        "last_seen": "never",
        "registered_at": datetime.now().isoformat(),
        "token": node_token,
    }

    # Ping to verify node is alive
    pinged = await ping_node(candidate)

    if pinged["status"] == "offline":
        return JSONResponse({
            "ok": False,
            "error": f"Could not reach node at {body.ip}:{body.port}. Make sure HTB Agent is running on the Mac Mini."
        }, status_code=400)

    # Use hostname as name if not provided
    if not body.name:
        pinged["name"] = pinged.get("hostname") or node_id

    nodes[node_id] = pinged
    save_registry(nodes)
    logger.info(f"New node registered: {node_id} at {body.ip}:{body.port} ({pinged.get('hostname')})")

    # Push token to node so it can verify future requests
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"http://{body.ip}:{body.port}/api/set-token",
                json={"token": node_token},
            )
        logger.info(f"Token pushed to {node_id}")
    except Exception as e:
        logger.warning(f"Could not push token to {node_id}: {e}")

    await manager.broadcast({"type": "node_registered", "node": pinged})
    await manager.broadcast({"type": "nodes_update", "nodes": list(nodes.values())})

    return JSONResponse({"ok": True, "node": pinged, "existing": False})


@app.delete("/api/nodes/{node_id}")
async def remove_node(node_id: str):
    """Remove a node from the registry."""
    if node_id not in nodes:
        return JSONResponse({"error": "Node not found"}, status_code=404)
    removed = nodes.pop(node_id)
    save_registry(nodes)
    await manager.broadcast({"type": "nodes_update", "nodes": list(nodes.values())})
    logger.info(f"Node removed: {node_id}")
    return JSONResponse({"ok": True, "removed": node_id})


@app.post("/api/nodes/reset")
async def reset_registry(request: Request, _=Depends(require_auth)):
    """Remove all nodes from the registry."""
    nodes.clear()
    save_registry(nodes)
    await manager.broadcast({"type": "nodes_update", "nodes": []})
    logger.info("Node registry reset by operator")
    return JSONResponse({"ok": True})


@app.post("/api/nodes/scan")
async def scan_nodes(request: Request, _=Depends(require_auth)):
    """Ping all nodes and refresh status."""
    for node_id in list(nodes.keys()):
        updated = await ping_node(nodes[node_id])
        nodes[node_id] = updated
    save_registry(nodes)
    await manager.broadcast({"type": "nodes_update", "nodes": list(nodes.values())})
    online = sum(1 for n in nodes.values() if n["status"] == "online")
    return JSONResponse({"ok": True, "total": len(nodes), "online": online})


# ── Fleet Command Endpoints ───────────────────────────────────────────────────

class FleetCommandBody(BaseModel):
    task: str
    target: str = "all"       # all | online | selected
    node_ids: list[str] = []
    concurrency: int = 0


@app.post("/api/fleet/broadcast")
async def fleet_broadcast(body: FleetCommandBody, request: Request, _=Depends(require_auth)):
    """Send a command to all (or selected) rack nodes."""
    if body.target == "selected":
        targets = [n for n in nodes.values() if n["id"] in body.node_ids]
    elif body.target == "online":
        targets = [n for n in nodes.values() if n["status"] == "online"]
    else:
        targets = list(nodes.values())

    if not targets:
        return JSONResponse({"ok": False, "error": "No nodes targeted"}, status_code=400)

    results = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = []
        for node in targets:
            url = f"http://{node['ip']}:{node['port']}/api/broadcast"
            payload = {"task": body.task, "target": "online", "concurrency": body.concurrency}
            tasks.append(client.post(url, json=payload))

        responses = await asyncio.gather(*tasks, return_exceptions=True)
        for node, resp in zip(targets, responses):
            if isinstance(resp, Exception):
                results.append({"node": node["id"], "ok": False, "error": str(resp)})
                logger.error(f"Fleet cmd failed for {node['id']}: {resp}")
            else:
                results.append({"node": node["id"], "ok": True, "count": resp.json().get("count", 0)})

    total_devices = sum(r.get("count", 0) for r in results if r.get("ok"))
    logger.info(f"Fleet command sent to {len(targets)} nodes — {total_devices} devices")

    await manager.broadcast({
        "type": "fleet_started",
        "task": body.task,
        "nodes": len(targets),
        "devices": total_devices,
        "time": now()
    })

    return JSONResponse({"ok": True, "nodes": len(targets), "devices": total_devices, "results": results})


@app.post("/api/fleet/stop")
async def fleet_stop(request: Request, _=Depends(require_auth)):
    """Stop all tasks on all nodes."""
    stopped = 0
    async with httpx.AsyncClient(timeout=5.0) as client:
        tasks = [
            client.post(f"http://{n['ip']}:{n['port']}/api/stop/all")
            for n in nodes.values() if n["status"] == "online"
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        for resp in responses:
            if not isinstance(resp, Exception):
                stopped += resp.json().get("count", 0)

    await manager.broadcast({"type": "fleet_stopped", "time": now()})
    return JSONResponse({"ok": True, "stopped": stopped})


# ── Master WebSocket ──────────────────────────────────────────────────────────


@app.websocket("/ws/screen/{serial}")
async def screen_proxy(ws: WebSocket, serial: str):
    """Proxy screen stream from node to screenwall client."""
    # Auth — session cookie or screenwall token
    session_token = ws.cookies.get("htb_session")
    query_token = ws.query_params.get("token", "")
    if session_token not in sessions and query_token != SCREENWALL_TOKEN:
        await ws.close(code=4401)
        return

    node_addr = ws.query_params.get("node", "")
    if not node_addr:
        await ws.close(code=4400)
        return

    await ws.accept()
    node_ws_url = f"ws://{node_addr}/ws/screen/{serial}"
    logger.info(f"Screen proxy: {serial} via {node_addr}")

    try:
        import websockets
        async with websockets.connect(node_ws_url) as node_ws:
            async def forward():
                async for msg in node_ws:
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        break

            await asyncio.create_task(forward())
    except Exception as e:
        logger.warning(f"Screen proxy error for {serial}: {e}")
        try:
            await ws.send_json({"type": "error", "msg": str(e)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # Check session cookie OR screenwall read-only token
    session_token = ws.cookies.get("htb_session")
    query_token = ws.query_params.get("token", "")
    is_session = session_token in sessions
    is_screenwall = query_token == SCREENWALL_TOKEN
    if not is_session and not is_screenwall:
        await ws.close(code=4401)
        logger.warning(f"Unauthorized WS attempt from {ws.client.host}")
        return
    await manager.connect(ws)
    logger.info("Dashboard connected to master WS")
    try:
        await ws.send_json({
            "type": "init",
            "nodes": list(nodes.values()),
        })
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("Dashboard disconnected")
    finally:
        manager.disconnect(ws)


# ── Master ping ───────────────────────────────────────────────────────────────

# ── LLM Config (master level — applies to all nodes) ─────────────────────────

master_llm_config = {
    "provider": "Ollama",
    "model": "qwen2.5:72b",
    "api_key": "",
    "ollama_url": "http://localhost:11434",
}


@app.post("/api/node-event")
async def node_event(request: Request):
    """Receive device status updates from nodes in real time."""
    # Verify node token
    body = await request.json()
    node_id = body.get("node_id", "")

    # Verify node is registered
    node = nodes.get(node_id)
    if not node:
        logger.warning(f"node-event from unknown node: {node_id}")
        return JSONResponse({"error": "Unknown node"}, status_code=404)

    # No token auth — local network only

    evt_type = body.get("type", "device_update")
    serial   = body.get("serial", "")

    # Update node's device list in registry
    if serial:
        if "device_list" not in nodes[node_id]:
            nodes[node_id]["device_list"] = {}
        existing = nodes[node_id]["device_list"].get(serial, {"serial": serial})
        existing.update({k: v for k, v in body.items() if k not in ("type", "node_id")})
        nodes[node_id]["device_list"][serial] = existing

        # Update total device count
        nodes[node_id]["devices"] = len(nodes[node_id]["device_list"])

    # Update busy count
    busy_count = sum(1 for d in nodes[node_id].get("device_list", {}).values() if d.get("status") == "busy")
    nodes[node_id]["running"] = busy_count
    nodes[node_id]["status"] = "online"
    nodes[node_id]["last_seen"] = datetime.now().strftime("%H:%M:%S")

    # Save registry so data survives master restart
    save_registry(nodes)

    # Broadcast to all connected dashboards (master + screenwall)
    await manager.broadcast({**body, "node_id": node_id})

    # Track task history in DB
    if evt_type == "device_update":
        status = body.get("status", "")
        task   = body.get("task", "")
        device_name = nodes[node_id].get("device_list", {}).get(serial, {}).get("name", serial)

        if status == "busy" and task and task != "idle":
            # Start tracking — store row_id in device_list
            row_id = db_task_start(node_id, serial, device_name, task)
            if serial and node_id in nodes:
                nodes[node_id]["device_list"][serial]["_history_id"] = row_id

    elif evt_type == "task_complete":
        row_id = nodes[node_id].get("device_list", {}).get(serial, {}).get("_history_id")
        db_task_done(row_id, "done")

    elif evt_type == "task_error":
        row_id = nodes[node_id].get("device_list", {}).get(serial, {}).get("_history_id")
        db_task_done(row_id, "error", error=body.get("error", "")[:200])

    # Also send full nodes_update so screenwall counters stay in sync
    await manager.broadcast({"type": "nodes_update", "nodes": list(nodes.values())})

    return JSONResponse({"ok": True})


@app.get("/api/history")
async def get_history(
    _=Depends(require_auth),
    limit: int = 100,
    node_id: str = None,
    status: str = None,
    serial: str = None
):
    """Get task execution history."""
    query = "SELECT * FROM task_history WHERE 1=1"
    params = []
    if node_id:
        query += " AND node_id=?"; params.append(node_id)
    if status:
        query += " AND status=?"; params.append(status)
    if serial:
        query += " AND serial=?"; params.append(serial)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return JSONResponse({"history": [dict(r) for r in rows], "total": len(rows)})

@app.get("/api/history/stats")
async def get_history_stats(_=Depends(require_auth)):
    """Get summary stats from history."""
    with get_db() as db:
        total    = db.execute("SELECT COUNT(*) FROM task_history").fetchone()[0]
        done     = db.execute("SELECT COUNT(*) FROM task_history WHERE status='done'").fetchone()[0]
        errors   = db.execute("SELECT COUNT(*) FROM task_history WHERE status='error'").fetchone()[0]
        running  = db.execute("SELECT COUNT(*) FROM task_history WHERE status='running'").fetchone()[0]
        avg_dur  = db.execute("SELECT AVG(duration) FROM task_history WHERE status='done' AND duration IS NOT NULL").fetchone()[0]
        by_node  = db.execute("SELECT node_id, COUNT(*) as cnt FROM task_history GROUP BY node_id ORDER BY cnt DESC").fetchall()
        recent   = db.execute("SELECT * FROM task_history ORDER BY id DESC LIMIT 10").fetchall()
    return JSONResponse({
        "total": total, "done": done, "errors": errors, "running": running,
        "avg_duration": round(avg_dur or 0),
        "by_node": [dict(r) for r in by_node],
        "recent": [dict(r) for r in recent]
    })

@app.delete("/api/history")
async def clear_history(_=Depends(require_auth)):
    """Clear all task history."""
    with db_lock:
        with get_db() as db:
            db.execute("DELETE FROM task_history")
            db.commit()
    return JSONResponse({"ok": True})

@app.get("/api/config")
async def get_config():
    safe = {**master_llm_config}
    if safe.get("api_key"):
        safe["api_key"] = safe["api_key"][:4] + "••••••••"
    return JSONResponse(safe)

@app.post("/api/config")
async def set_config(body: dict):
    global master_llm_config
    master_llm_config.update({k: v for k, v in body.items() if k in master_llm_config})
    logger.info(f"Master LLM config updated — {master_llm_config['provider']} / {master_llm_config['model']}")
    await manager.broadcast({"type": "config_updated", **master_llm_config})
    return JSONResponse({"ok": True, **master_llm_config})


# ── Master ping ───────────────────────────────────────────────────────────────

@app.get("/api/ping")
async def master_ping():
    return JSONResponse({
        "status": "ok",
        "role": "master",
        "nodes": len(nodes),
        "online": sum(1 for n in nodes.values() if n["status"] == "online"),
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("master:app", host="0.0.0.0", port=8888, reload=False)
