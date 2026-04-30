"""LLM prompts for Spotify automation ticks."""

from __future__ import annotations

from .state import SpotifySessionState


def prompt_first_song(state: SpotifySessionState) -> str:
    pl_url = state.playlists[state.current_playlist_idx]
    return f"""
You are automating Spotify on an Android device.
The playlist has just been opened via its link: {pl_url}

TASK — First song selection:
1. Wait up to 3 seconds for the playlist screen to load fully.
2. Scroll the track list at least TWO times (same direction or mixed) before choosing —
   do not pick from only the first screenful; this should look like a natural browse
   and help cover more of the playlist. Optionally scroll 3–4 times when the list is long.
3. Pick ONE random song from the area you scrolled to (prefer not the very first row).
4. Tap the song to start playback.
5. Confirm playback started: the play/pause button should show "pause",
   or the progress bar at the bottom should be moving.
6. Finish immediately once playback is confirmed.

Constraints:
- Stay ONLY inside the Spotify app. Do NOT navigate to any other app.
- Do NOT press shuffle — pick a specific track yourself.
- If the playlist is empty or loading fails, report failure.
- If you see ANY popup, dialog, banner, cookie consent, or notification overlay
  that is NOT part of the playlist screen, dismiss it immediately
  (tap "Dismiss", "OK", "Close", "X", "Not now", or press Back) before continuing.
- If an audio/video ad or another screen hides the playlist track list, get through or
  dismiss it (Back, skip/close if offered), return to this playlist's track list
  (re-open {pl_url} if you cannot get back otherwise), then run steps 2 onward —
  including mandatory at-least-two scrolls before picking.
""".strip()


def prompt_next_tick(state: SpotifySessionState) -> str:
    needs_switch = state.tracks_on_current >= state.target_tracks_before_switch
    pl_url = state.playlists[state.current_playlist_idx]
    other_pls = [
        f"  [{i}] {url}"
        for i, url in enumerate(state.playlists)
        if i != state.current_playlist_idx
    ]
    other_section = (
        "\n".join(other_pls)
        if other_pls
        else "  (none — only one playlist configured)"
    )
    action = (
        "SWITCH to a DIFFERENT playlist (see list below) then play a random song there."
        if needs_switch
        else "Play a DIFFERENT random song in the CURRENT playlist (not the same track that was just playing if visible)."
    )

    return f"""
You are automating Spotify on an Android device.

SESSION STATE:
  Current playlist index : {state.current_playlist_idx}
  Current playlist URL   : {pl_url}
  Tracks on this playlist: {state.tracks_on_current} (switch threshold: {state.target_tracks_before_switch})
  Total tracks this session: {state.total_tracks_played}
  Time remaining (s)     : {int(state.remaining_sec())}

ACTION REQUIRED: {action}

OTHER ALLOWED PLAYLISTS (use one of these if switching):
{other_section}

RULES:
1. To switch playlist: use the system Back button or Spotify home to navigate,
   open the new playlist URL (tap the search/library or use the provided URL),
   then scroll the new playlist's track list at least TWO times (more if long) before
   tapping a random song — same natural-browse rule as below.
2. To continue on the current playlist: ALWAYS scroll the track list at least TWO times
   before each pick (two or more; vary between ticks so behavior feels human). Do not
   only play what was already on screen — explore different depths so the whole playlist
   can be reached over the session. Then tap a different song (not the same track that
   was just playing if it is still visible).
3. Confirm playback started before finishing.
4. Do NOT leave Spotify or open any other app.
5. Do NOT enable shuffle mode — you are selecting tracks manually.
6. Finish immediately once the new track is confirmed playing.
7. If you see ANY popup, dialog, banner, cookie consent, ad overlay, or system
   notification blocking the screen, dismiss it first (tap "Dismiss", "OK",
   "Close", "X", "Not now", or press Back) before continuing with the task.
8. Ads / left the playlist: If an audio or video ad plays, or the UI no longer shows
   THIS playlist's track list (full-screen ad, Now Playing without the list, radio,
   or another section), finish or dismiss the ad as the UI allows (Back, skip, close),
   then return to the track list for the current playlist (Back, Home/Library, or
   re-open "Current playlist URL" from SESSION STATE above). Once the track list is
   visible again, you MUST scroll the list at least TWO times before tapping the next
   song — same as rule 2 — even if you just came back from an ad; do not pick from the
   first screenful only.
""".strip()


def prompt_session_cleanup() -> str:
    return """
The Spotify automation session has ended normally (time limit reached).
1. If music is playing, pause it by tapping the play/pause button.
2. Press the Android Home button to return to the home screen.
3. Finish.

Do NOT close the Spotify app, just leave it in paused state.
""".strip()
