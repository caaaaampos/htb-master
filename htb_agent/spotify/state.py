"""SpotifySessionState — mutable state for one device's Spotify session."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SpotifySessionState:
    # ── immutable config ──────────────────────────────────────────────────────
    serial: str
    playlists: list[str]              # Spotify playlist URLs
    listen_min_sec: float             # e.g. 35
    listen_max_sec: float             # e.g. 45
    tracks_min: int                   # min songs before playlist switch
    tracks_max: int                   # max songs before playlist switch
    total_duration_sec: float         # session wall-clock budget
    llm_max_steps_per_tick: int = 15  # DroidAgent steps per LLM invocation
    llm_semaphore_id: str = "global"  # key for shared semaphore (unused externally)

    # ── mutable runtime ───────────────────────────────────────────────────────
    phase: str = "not_started"
    # phases: not_started → connecting → opening → first_song → running → done

    session_start_ts: float = 0.0
    deadline_ts: float = 0.0

    current_playlist_idx: int = 0
    tracks_on_current: int = 0
    target_tracks_before_switch: int = 0

    total_tracks_played: int = 0
    playlist_switches: int = 0
    iterations: int = 0
    tick_errors: int = 0

    cancelled: bool = False
    last_error: str = ""

    def elapsed_sec(self) -> float:
        if not self.session_start_ts:
            return 0.0
        import asyncio
        return asyncio.get_event_loop().time() - self.session_start_ts

    def remaining_sec(self) -> float:
        if not self.deadline_ts:
            return 0.0
        import asyncio
        return max(0.0, self.deadline_ts - asyncio.get_event_loop().time())

    def progress_pct(self) -> int:
        if not self.total_duration_sec:
            return 0
        return min(99, int(100 * self.elapsed_sec() / self.total_duration_sec))

    def to_status_dict(self) -> dict:
        return {
            "serial": self.serial,
            "phase": self.phase,
            "playlist_idx": self.current_playlist_idx,
            "tracks_on_current": self.tracks_on_current,
            "target_tracks_before_switch": self.target_tracks_before_switch,
            "total_tracks_played": self.total_tracks_played,
            "playlist_switches": self.playlist_switches,
            "iterations": self.iterations,
            "tick_errors": self.tick_errors,
            "progress": self.progress_pct(),
            "elapsed_sec": int(self.elapsed_sec()),
            "remaining_sec": int(self.remaining_sec()),
            "cancelled": self.cancelled,
            "last_error": self.last_error,
        }
