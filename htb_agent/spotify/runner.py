"""
spotify_automation_loop — main coroutine for one device's Spotify session.

Architecture:
  1. ADB  → open playlist URL (no LLM)
  2. LLM  → first song selection
  3. loop → sleep(random) + [optional ADB playlist switch] + LLM next tick
  4. LLM  → cleanup (pause + home)

The semaphore (shared across all device tasks for the same node) limits
concurrent LLM calls so the model is not flooded.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from typing import Callable, Awaitable

from .state import SpotifySessionState
from .prompts import prompt_first_song, prompt_next_tick, prompt_session_cleanup

logger = logging.getLogger("htb-server")

# One shared LLM semaphore per process; size is set by the first session that
# starts.  Subsequent sessions reuse it.
_llm_sem: asyncio.Semaphore | None = None
_llm_sem_size: int = 0


def _get_llm_semaphore(size: int) -> asyncio.Semaphore:
    global _llm_sem, _llm_sem_size
    if _llm_sem is None or _llm_sem_size != size:
        _llm_sem = asyncio.Semaphore(size)
        _llm_sem_size = size
    return _llm_sem


def _device_rng(serial: str) -> random.Random:
    seed = int.from_bytes(hashlib.sha256(serial.encode()).digest()[:8], "big")
    return random.Random(seed)


async def _adb_open_url(adb_bin: str, serial: str, url: str) -> tuple[bool, str]:
    """Open a URL via Android VIEW intent. Argv-safe — no shell interpolation."""
    proc = await asyncio.create_subprocess_exec(
        adb_bin, "-s", serial,
        "shell", "am", "start",
        "-a", "android.intent.action.VIEW",
        "-d", url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=25.0)
    except asyncio.TimeoutError:
        proc.kill()
        return False, "adb timeout"
    text = ((out or b"") + (err or b"")).decode(errors="replace").strip()
    ok = proc.returncode == 0 or "Starting:" in text or "cmp=" in text
    return ok, text[:300]


A11Y_SERVICE = (
    "com.droidrun.portal/"
    "com.droidrun.portal.service.DroidrunAccessibilityService"
)


async def _ensure_device_ready(adb_bin: str, serial: str) -> None:
    """Prepare the device before every LLM tick.

    1. Wake screen + keep it on while USB is connected
    2. Re-enable Portal accessibility if Samsung killed it
    3. Whitelist Portal from battery optimization
    4. Ensure Spotify is in foreground
    """
    async def _sh(cmd: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            adb_bin, "-s", serial, "shell", cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        return (out or b"").decode(errors="replace").strip()

    # Wake screen & keep alive
    await _sh("input keyevent KEYCODE_WAKEUP")
    await _sh("svc power stayon usb")
    await _sh("settings put system screen_off_timeout 1800000")

    # Re-enable accessibility if it was killed
    a11y = await _sh("settings get secure enabled_accessibility_services")
    if "com.droidrun.portal" not in a11y:
        logger.warning(f"[{serial}] Portal a11y was OFF — re-enabling")
        svc = f"{a11y}:{A11Y_SERVICE}" if a11y and a11y != "null" else A11Y_SERVICE
        await _sh(f"settings put secure enabled_accessibility_services {svc}")
        await _sh("settings put secure accessibility_enabled 1")
        await asyncio.sleep(2.0)

    # Samsung battery whitelist
    await _sh("cmd appops set com.droidrun.portal RUN_IN_BACKGROUND allow")
    await _sh("dumpsys deviceidle whitelist +com.droidrun.portal")

    # Ensure Spotify is in foreground
    focus = await _sh("dumpsys window | grep mCurrentFocus")
    if "com.spotify.music" not in focus:
        logger.info(f"[{serial}] Spotify not in foreground, bringing it back")
        await _sh(
            "am start -n com.spotify.music/.MainActivity "
            "--activity-single-top --activity-brought-to-front"
        )
        await asyncio.sleep(1.5)


async def _warm_up_portal(driver, max_attempts: int = 6, interval: float = 2.0) -> bool:
    """Poll driver.get_ui_tree() until the Portal returns a valid state.

    Deep links (VIEW intents) load heavier screens than the launcher activity,
    so the Portal often needs a few extra seconds before the accessibility tree
    is available.  Returns True once a good response is received.
    """
    for i in range(1, max_attempts + 1):
        try:
            data = await driver.get_ui_tree()
            if isinstance(data, dict) and "error" not in data and "a11y_tree" in data:
                logger.info(f"Portal warm-up OK after {i} attempt(s)")
                return True
            logger.debug(f"Portal warm-up attempt {i}: got keys={list(data.keys()) if isinstance(data, dict) else type(data)}")
        except Exception as exc:
            logger.debug(f"Portal warm-up attempt {i}: {exc}")
        await asyncio.sleep(interval)
    logger.warning(f"Portal warm-up failed after {max_attempts} attempts — proceeding anyway")
    return False


async def _run_llm_tick(
    driver,
    llm,
    goal: str,
    max_steps: int,
    sem: asyncio.Semaphore,
) -> None:
    """Invoke DroidAgent with a short goal, guarded by a semaphore."""
    from htb_agent.agent.droid.droid_agent import DroidAgent

    async with sem:
        agent = DroidAgent(goal=goal, driver=driver, llms=llm)
        handler = agent.run()
        async for _ in handler.stream_events():
            pass
        await handler


async def spotify_automation_loop(
    state: SpotifySessionState,
    adb_bin: str,
    llm,
    driver,
    broadcast: Callable[[dict], Awaitable[None]],
    report: Callable[[dict], Awaitable[None]],
    llm_concurrency: int = 10,
) -> None:
    """
    Full Spotify session for one device.

    Args:
        state         : mutable session state (serial, playlists, timings…)
        adb_bin       : path to adb executable
        llm           : loaded LLM object (from load_llm)
        driver        : AndroidDriver already connected
        broadcast     : async fn(dict) → dashboard WebSocket
        report        : async fn(dict) → master node-event
        llm_concurrency: max parallel LLM calls across all device tasks
    """
    loop = asyncio.get_event_loop()
    rng = _device_rng(state.serial)
    sem = _get_llm_semaphore(llm_concurrency)

    # ── helpers ────────────────────────────────────────────────────────────────
    def _now() -> str:
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S")

    async def _log(msg: str, kind: str = "") -> None:
        evt = {
            "type": "device_update",
            "serial": state.serial,
            "status": "busy",
            "task": "♫ Spotify",
            "progress": state.progress_pct(),
            "log": {"time": _now(), "msg": msg, "type": kind},
        }
        await broadcast(evt)
        await report(evt)

    async def _done(msg: str) -> None:
        evt = {
            "type": "task_complete",
            "serial": state.serial,
            "status": "online",
            "task": "idle",
            "progress": 100,
            "log": {"time": _now(), "msg": msg, "type": "success"},
        }
        await broadcast(evt)
        await report(evt)

    async def _error(msg: str) -> None:
        evt = {
            "type": "task_error",
            "serial": state.serial,
            "status": "online",
            "task": "idle",
            "progress": 0,
            "error": msg[:200],
            "log": {"time": _now(), "msg": msg, "type": "error"},
        }
        await broadcast(evt)
        await report(evt)

    # ── initialise state ──────────────────────────────────────────────────────
    state.session_start_ts = loop.time()
    state.deadline_ts = loop.time() + state.total_duration_sec
    state.current_playlist_idx = rng.randrange(len(state.playlists))
    state.target_tracks_before_switch = rng.randint(state.tracks_min, state.tracks_max)
    state.phase = "opening"

    try:
        # ── PHASE 0: prepare device ────────────────────────────────────────────
        await _log("🔧 Preparing device (screen, accessibility, battery)...")
        await _ensure_device_ready(adb_bin, state.serial)

        # ── PHASE 1: open playlist via ADB (no LLM) ───────────────────────────
        pl_url = state.playlists[state.current_playlist_idx]
        await _log(
            f"▶ Opening playlist [{state.current_playlist_idx}]: {pl_url[:60]}..."
        )
        ok, msg = await _adb_open_url(adb_bin, state.serial, pl_url)
        if not ok:
            raise RuntimeError(f"Could not open playlist via ADB: {msg}")

        # Deep links load heavier screens — give Spotify time, then confirm
        # the Portal can read the UI before handing control to the LLM.
        await asyncio.sleep(5.0)
        await _log("⏳ Waiting for Portal to read Spotify UI...")
        await _warm_up_portal(driver, max_attempts=6, interval=2.0)

        # ── PHASE 2: first song — LLM decides ─────────────────────────────────
        state.phase = "first_song"
        await _log("🤖 LLM selecting first song...")
        await _run_llm_tick(
            driver, llm,
            prompt_first_song(state),
            state.llm_max_steps_per_tick,
            sem,
        )
        state.tracks_on_current = 1
        state.total_tracks_played = 1
        state.phase = "running"
        await _log(
            f"▶ Session running — "
            f"{state.listen_min_sec:.0f}-{state.listen_max_sec:.0f}s / track, "
            f"switch after {state.target_tracks_before_switch} tracks, "
            f"{state.total_duration_sec / 60:.0f}min total",
            "success",
        )

        # ── PHASE 3: main loop ────────────────────────────────────────────────
        while loop.time() < state.deadline_ts and not state.cancelled:
            state.iterations += 1

            # random listen window per device (different RNG seed per serial)
            wait_sec = rng.uniform(state.listen_min_sec, state.listen_max_sec)
            remaining = state.deadline_ts - loop.time()
            if remaining <= 0:
                break
            actual_wait = min(wait_sec, remaining)

            await broadcast({
                "type": "device_update",
                "serial": state.serial,
                "status": "busy",
                "task": "♫ Spotify",
                "progress": state.progress_pct(),
                "log": {
                    "time": _now(),
                    "msg": f"⏱ Listening {actual_wait:.0f}s… (track {state.total_tracks_played}, playlist {state.current_playlist_idx})",
                    "type": "",
                },
            })
            await asyncio.sleep(actual_wait)

            if loop.time() >= state.deadline_ts or state.cancelled:
                break

            # did we reach the per-playlist track threshold?
            needs_switch = state.tracks_on_current >= state.target_tracks_before_switch

            # when switching: ADB opens the new playlist URL first so the LLM
            # already sees it loaded in Spotify — saves several agent steps
            if needs_switch and len(state.playlists) > 1:
                others = [
                    i for i in range(len(state.playlists))
                    if i != state.current_playlist_idx
                ]
                state.current_playlist_idx = rng.choice(others)
                new_url = state.playlists[state.current_playlist_idx]
                await _log(
                    f"🔄 Switching playlist → [{state.current_playlist_idx}]: {new_url[:55]}..."
                )
                ok, _ = await _adb_open_url(adb_bin, state.serial, new_url)
                await asyncio.sleep(4.0)
                await _warm_up_portal(driver, max_attempts=4, interval=1.5)
                state.tracks_on_current = 0
                state.playlist_switches += 1
                state.target_tracks_before_switch = rng.randint(
                    state.tracks_min, state.tracks_max
                )

            # Pre-tick: ensure screen/accessibility/Spotify are alive
            await _ensure_device_ready(adb_bin, state.serial)

            # LLM tick: next track or playlist navigation
            await _log("🤖 LLM deciding next track...")
            try:
                await _run_llm_tick(
                    driver, llm,
                    prompt_next_tick(state),
                    state.llm_max_steps_per_tick,
                    sem,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state.tick_errors += 1
                await _log(f"⚠ LLM tick error ({state.tick_errors}): {exc}", "error")
                # don't abort — sleep will still happen next cycle

            state.tracks_on_current += 1
            state.total_tracks_played += 1

        # ── PHASE 4: session end cleanup ──────────────────────────────────────
        state.phase = "done"
        await _log("✅ Session time elapsed — cleaning up")
        try:
            await _run_llm_tick(
                driver, llm,
                prompt_session_cleanup(),
                8,
                sem,
            )
        except Exception:
            pass  # best-effort

        await _done(
            f"✓ Spotify session done — {state.total_tracks_played} tracks, "
            f"{state.playlist_switches} playlist switch(es), "
            f"{state.tick_errors} error(s)"
        )

    except asyncio.CancelledError:
        state.cancelled = True
        state.phase = "done"
        await _error(
            f"⏹ Spotify session stopped by user "
            f"(played {state.total_tracks_played} tracks)"
        )
        raise

    except Exception as exc:
        state.phase = "done"
        state.last_error = str(exc)
        logger.error(f"Spotify loop [{state.serial}]: {exc}")
        await _error(f"✗ Spotify session failed: {exc}")
        raise
