# Audio Preview & Waveform — Architectural Design

> **Status:** Proposed
> **Date:** 2026-04-12
> **Author:** Architect agent
> **ADR:** ADR-009 (see `architecture-decisions.md`)

## 1. Problem Statement

DJs using Sidecar's suggestion panel currently rely on metadata alone (key, BPM, energy, genre) to decide whether a suggested track is a good fit. They cannot audition tracks without switching to Serato or a file browser. Adding inline audio preview with a seekable waveform lets DJs confirm their choice before committing, reducing context-switching and improving set flow.

## 2. Requirements

### Functional
- **Play/pause button** on each suggestion row to preview the track's audio file.
- **Waveform visualization** that appears when a track is playing, showing the full track duration.
- **Seekable waveform** — clicking a position on the waveform jumps playback to that point.
- **Single-track playback** — only one track plays at a time. Starting a new track stops the previous one.
- **Playback position indicator** — a visual cursor/line showing the current position within the waveform.

### Non-Functional
- Cross-platform: Windows and macOS (Linux nice-to-have).
- Must bundle cleanly with PyInstaller (no external runtime dependencies the user must install separately).
- Waveform generation must not block the UI thread.
- Memory-efficient: do not hold entire decoded audio buffers in memory for all suggested tracks.

## 3. Library Selection

### Audio Playback: `pygame.mixer` (from pygame)

**Chosen over:** `python-vlc` (requires VLC installed), `playsound` (no seek/pause), `pyaudio` (raw PCM only, no format decoding), `just_playback` (unmaintained), `simpleaudio` (no seek), `miniaudio` (good but less battle-tested with PyInstaller).

**Why pygame.mixer:**
- Proven cross-platform audio playback (Windows, macOS, Linux) backed by SDL2.
- Supports MP3, WAV, OGG, FLAC out of the box via SDL_mixer.
- Provides `play()`, `pause()`, `unpause()`, `stop()`, `set_pos()`, `get_pos()` — all the controls we need.
- Mature PyInstaller support — `pygame` is one of the most commonly bundled game/multimedia libraries. PyInstaller hooks exist and work.
- We only need `pygame.mixer` and `pygame.time` — we do NOT init `pygame.display` or any video subsystem. This keeps the footprint minimal.
- Pure pip install, no system-level dependencies on Windows or macOS.

**Dependency note:** pygame is ~30MB installed. Since we only use the mixer module, the PyInstaller bundle size increase is primarily the SDL2 shared libraries (~3-5MB). This is acceptable for the value delivered.

**Alternative considered — miniaudio:**
`miniaudio` is lighter-weight and has a clean Python API. It would be the second choice if pygame causes bundling problems. The tradeoff is less community knowledge around PyInstaller bundling and fewer StackOverflow answers when things go wrong. If pygame proves problematic during implementation, fall back to `miniaudio`.

### Waveform Generation: `mutagen` (already a dependency) + raw audio sampling

**Approach:** We already depend on `mutagen` for ID3 tag reading. For waveform rendering, we need amplitude data at ~200-400 sample points across the track duration. Two options:

**Option A (Recommended): `pydub` for amplitude extraction.**
`pydub` can decode MP3/FLAC/WAV/AIFF into raw PCM samples using ffmpeg OR the audioop stdlib module. However, `pydub` with ffmpeg creates a system dependency we want to avoid.

**Option B (Recommended, simpler): `pygame.mixer.Sound` for short files + raw WAV sampling.**
For waveform data, load the audio into a `pygame.sndarray` (which gives a numpy-like array of samples). This avoids adding another dependency but requires pygame's mixer to decode the file.

**Option C (Chosen): Pure-Python waveform from file bytes + `struct`.**
For MP3s, we can get a rough-but-adequate waveform by sampling raw byte amplitudes at regular intervals across the file. This produces a "fake waveform" that is visually representative (louder sections show taller bars) without needing to fully decode the audio. This is the approach used by many lightweight DJ tools for preview waveforms.

For WAV/AIFF files (uncompressed), we can read actual PCM sample values using `struct.unpack` since the format is straightforward.

**Final decision:** Use **Option C** (raw byte sampling) as the initial implementation. It requires zero new dependencies for waveform generation, works on all supported formats, and produces visually useful results. If users request higher-fidelity waveforms in the future, upgrade to decoded PCM sampling via pygame's sndarray (requires numpy, which is a heavier dependency).

### New Dependencies

Add to `requirements.txt`:
```
pygame>=2.5.0
```

No other new dependencies required. Waveform generation uses only stdlib (`struct`, `array`, `pathlib`).

## 4. Architecture

### New Components

```
source/
├── services/
│   ├── audio_player.py      # NEW — Playback control (play, pause, stop, seek, position)
│   └── waveform.py           # NEW — Waveform amplitude data generation + caching
└── ui/
    └── waveform_widget.py    # NEW — CTkCanvas-based waveform display with seek interaction
```

### Layer Placement

Following the existing architecture (models = data, services = logic, ui = presentation):

| Component | Layer | Responsibility |
|-----------|-------|----------------|
| `AudioPlayer` | Service | Wraps `pygame.mixer.music`. Singleton-like: one instance owned by `app.py`. Exposes `play(path)`, `pause()`, `resume()`, `stop()`, `seek(seconds)`, `get_position() -> float`, `is_playing() -> bool`, `on_track_end` callback. |
| `WaveformGenerator` | Service | Generates amplitude data from an audio file path. Returns `list[float]` (normalized 0.0-1.0 amplitudes). Handles caching. |
| `WaveformWidget` | UI | Renders amplitude bars on a `tkinter.Canvas`. Handles click-to-seek. Receives amplitude data and playback position updates. |

### Integration with Existing Components

```
app.py
├── owns AudioPlayer instance (created once at startup)
├── passes AudioPlayer reference to SuggestionPanel
│
SuggestionPanel
├── each row gets a play/pause button (column added to grid)
├── on play click → calls AudioPlayer.play(track.full_file_path)
├── on play click → creates/shows WaveformWidget below the row
├── AudioPlayer.on_track_end → resets button state
│
WaveformWidget
├── requests waveform data from WaveformGenerator (async)
├── renders bars on CTkCanvas
├── click → calls AudioPlayer.seek(position)
├── periodic update → redraws playhead position via AudioPlayer.get_position()
```

### Data Flow

```
User clicks ▶ on suggestion row
    │
    ▼
SuggestionPanel._on_play(track)
    │
    ├──▶ AudioPlayer.play(track.full_file_path)
    │       └── pygame.mixer.music.load(path)
    │       └── pygame.mixer.music.play()
    │
    └──▶ WaveformGenerator.get_waveform(track.full_file_path)
            │  (background thread if not cached)
            ▼
         WaveformWidget.set_data(amplitudes, duration)
            └── Renders bars on canvas
            └── Starts position polling timer (self.after(100, update_playhead))
```

## 5. UI Design

### Play Button Placement

Add a **play/pause toggle button** as a new column in the suggestion grid, positioned between the genre column and the existing "+" button.

Updated column layout:
```python
_COL = {
    "score": 48, "artist": 140, "title": 160,
    "key": 48, "bpm": 48, "energy": 32, "genre": 68,
    "play": 32,   # NEW
    "add": 32,
}
```

The button displays `▶` when stopped and `⏸` when playing. Uses the same transparent/hover style as the existing "+" button.

### Waveform Placement: Expandable Row

The waveform appears **below the suggestion row** as an expandable section, NOT inline within the row. Rationale:

1. **Space:** A useful waveform needs at least ~400px width and ~40px height. This does not fit inside a row that is ~30px tall.
2. **Scroll context:** Expanding below the row keeps the other suggestions visible and scrollable.
3. **Precedent:** This is the standard pattern in music apps (Spotify, SoundCloud, Serato itself).

When the user clicks play:
1. The row's play button changes to pause icon.
2. A `WaveformWidget` frame (height ~50px) slides in below that row.
3. Other suggestion rows shift down within the scroll frame.
4. The waveform shows a loading state ("Generating waveform...") until data is ready.

When playback stops (or another track is played):
1. The previous waveform frame is destroyed.
2. The previous row's button reverts to play icon.
3. The new track's waveform appears below its row.

### Click Behavior Interaction

Current behavior: clicking anywhere on a suggestion row calls `_select_track(track)` which makes it the "Now Playing" track and updates suggestions.

**Design decision:** The play button does NOT select the track. It only previews audio. The user must still click the row (or the "+" button) to actually select the track as "Now Playing." This separation is important — DJs want to audition a track before committing to it.

The play button's click event must call `event.stop_propagation()` (via returning `"break"` from the Tkinter binding) to prevent the row-click handler from also firing.

### Visual Design

```
┌─────────────────────────────────────────────────────────┐
│  85%  Artist Name     Track Title     4A  128  6  House  ▶  +  │  ← normal row
├─────────────────────────────────────────────────────────┤
│  ▁▂▃▅▇█▇▅▃▅▇█▇▅▃▂▁▂▃▅▇█▇▅▆▇█▇▅▃▂▁▂▃▅▇█▇▅▃▂▁         │  ← waveform (shown when playing)
│  ──────────────────|────────────────────────────         │     (| = playhead)
│                  1:23 / 4:56                    ■ Stop  │     time display + stop button
└─────────────────────────────────────────────────────────┘
│  72%  Another Artist  Another Track  ...         ▶  +  │  ← next row
```

Waveform colors:
- Bars (unplayed portion): `#555555` (dark gray)
- Bars (played portion, left of playhead): `#1f6aa5` (CTk default blue accent)
- Playhead line: `#ffffff` (white)
- Background: matches the row's alternating background color

## 6. Service Specifications

### `services/audio_player.py`

```python
class AudioPlayer:
    """Singleton audio playback controller wrapping pygame.mixer.music."""

    def __init__(self):
        """Initialize pygame mixer subsystem only (not display)."""

    def play(self, file_path: str) -> bool:
        """Load and play an audio file. Stops any current playback first.
        Returns False if the file cannot be loaded."""

    def pause(self) -> None:
        """Pause current playback. No-op if not playing."""

    def resume(self) -> None:
        """Resume paused playback. No-op if not paused."""

    def stop(self) -> None:
        """Stop playback and unload the current file."""

    def seek(self, seconds: float) -> None:
        """Jump to the given position in the current track."""

    def get_position(self) -> float:
        """Return current playback position in seconds. Returns 0.0 if not playing."""

    def get_duration(self) -> float:
        """Return duration of the loaded track in seconds. Returns 0.0 if nothing loaded."""

    @property
    def is_playing(self) -> bool: ...

    @property
    def is_paused(self) -> bool: ...

    @property
    def current_file(self) -> str | None:
        """Path of the currently loaded file, or None."""

    def set_on_track_end(self, callback: Callable[[], None] | None) -> None:
        """Register a callback invoked when the current track finishes naturally."""

    def shutdown(self) -> None:
        """Clean up pygame mixer. Call on app exit."""
```

**Implementation notes:**
- Call `pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)` in `__init__`. Do NOT call `pygame.init()` — that would try to create a display window.
- `pygame.mixer.music.get_pos()` returns milliseconds since `play()` was called. Track seek offsets by storing a `_seek_offset` that is added to `get_pos()`.
- For track-end detection, use `pygame.mixer.music.set_endevent()` and poll via a tkinter `after()` timer (every 200ms). Do not use a separate thread for event polling.
- Duration: `pygame.mixer.Sound(path).get_length()` returns duration in seconds. Load as Sound briefly to get duration, then unload. Alternatively, use `mutagen` (already a dependency) to read duration from tags without decoding audio: `mutagen.File(path).info.length`.
- Use `mutagen` for duration (already imported elsewhere) to avoid the memory cost of loading the full file as a `Sound` object.

### `services/waveform.py`

```python
class WaveformGenerator:
    """Generates visual amplitude data from audio files."""

    NUM_BARS: int = 300  # Number of amplitude samples for the waveform

    def get_waveform(
        self,
        file_path: str,
        num_bars: int = NUM_BARS,
        callback: Callable[[list[float]], None] | None = None,
    ) -> list[float] | None:
        """Return cached waveform data or generate it asynchronously.

        If cached, returns the data immediately (list of floats 0.0-1.0).
        If not cached, starts background generation and calls callback
        with the data when ready. Returns None in this case.
        """

    def _generate_waveform(self, file_path: str, num_bars: int) -> list[float]:
        """Read the file and produce amplitude samples.

        Strategy:
        - Divide file into num_bars equal-sized chunks.
        - For each chunk, compute the average absolute byte value.
        - Normalize all values to 0.0-1.0 range.
        """

    def clear_cache(self) -> None:
        """Drop all cached waveform data (e.g., after a library re-sync)."""
```

**Implementation notes:**
- Cache is an in-memory `dict[str, list[float]]` keyed by file path. No disk persistence — waveforms are cheap to regenerate (takes ~50-100ms per file for raw byte sampling).
- Background generation runs on a `threading.Thread(daemon=True)`. The callback is invoked on the calling thread via `widget.after(0, callback)` (the caller passes a tkinter-safe callback).
- For MP3 files: read the raw bytes, skip the ID3v2 header (check for "ID3" magic bytes and read the header size), then sample the remaining audio frame bytes. The byte-level amplitude correlates well enough with actual audio amplitude for a visual preview.
- For WAV files: skip the 44-byte header, read raw PCM samples using `struct`.
- For FLAC/AIFF: use raw byte sampling (same as MP3 approach). The visual result is approximate but adequate.
- Memory limit: cache at most 50 waveforms. Use an LRU eviction strategy (collections.OrderedDict or functools.lru_cache).

### `ui/waveform_widget.py`

```python
class WaveformWidget(ctk.CTkFrame):
    """Canvas-based waveform display with seek-on-click."""

    def __init__(
        self,
        master,
        on_seek: Callable[[float], None] | None = None,  # seek callback (0.0-1.0 fraction)
        on_stop: Callable[[], None] | None = None,
        **kwargs,
    ):
        """Create the waveform frame with canvas and time label."""

    def set_data(self, amplitudes: list[float], duration_seconds: float) -> None:
        """Set waveform amplitude data and total duration. Triggers a full redraw."""

    def set_position(self, seconds: float) -> None:
        """Update the playhead position. Called periodically by the parent."""

    def set_loading(self) -> None:
        """Show a loading indicator while waveform data is being generated."""

    def destroy(self) -> None:
        """Clean up timers and canvas."""
```

**Implementation notes:**
- Uses `tkinter.Canvas` (not CTkCanvas, which doesn't exist — CTk wraps standard Canvas).
- Bars are drawn as vertical `create_rectangle()` calls. For 300 bars at 2px width + 1px gap = 900px. Scale to fit available canvas width.
- Playhead is a `create_line()` redrawn on each position update.
- Color split (played vs unplayed) is achieved by drawing bars in two passes or by changing individual bar colors as the playhead passes them.
- Click handler: bind `<Button-1>` on the canvas, compute `click_x / canvas_width` to get the seek fraction, call `on_seek(fraction)`.
- Time label below the canvas shows `"current / total"` in `M:SS` format.

## 7. Waveform Caching Strategy

| Aspect | Decision |
|--------|----------|
| Storage | In-memory only (dict keyed by file path) |
| Max entries | 50 waveforms (LRU eviction) |
| Persistence | None — regeneration is fast (~50-100ms) |
| Invalidation | Clear on library re-sync (file content may have changed) |
| Pre-computation | None — generate on first play request only |
| Memory cost | ~300 floats x 8 bytes = ~2.4KB per waveform, 50 cached = ~120KB total. Negligible. |

**Why not pre-compute?** Generating waveforms for 30 suggestions on every track selection would add ~1.5-3 seconds of background work. Most suggestions are never previewed. On-demand generation with caching is the right tradeoff.

## 8. Playback State Management

### State Machine

```
                    play(path)
    STOPPED ──────────────────▶ PLAYING
       ▲                          │ │
       │ stop()          pause()  │ │ track ends
       │                    ┌─────┘ │
       │                    ▼       │
       │                 PAUSED     │
       │                    │       │
       │     resume()      │       │
       │     ┌─────────────┘       │
       │     ▼                     │
       │  PLAYING                  │
       │                           │
       └───────────────────────────┘
```

### Rules
1. **One track at a time.** Calling `play(new_path)` while another track is playing stops the old track first.
2. **Play button is per-row.** Only the currently-playing row shows a pause icon. All other rows show play icons.
3. **Selecting a suggestion (clicking the row or "+" button) stops playback.** When the user commits to a track, the preview is no longer needed, and the suggestion list is about to refresh anyway.
4. **Re-sync stops playback.** If the user triggers a crate sync while previewing, playback stops. The suggestion list will be rebuilt.
5. **App exit calls `AudioPlayer.shutdown()`.** Ensures pygame mixer is properly closed.

### Position Tracking

`SuggestionPanel` (or `WaveformWidget`) runs a tkinter `after()` timer every 100ms while a track is playing:
```python
def _update_playhead(self):
    if self._audio_player.is_playing:
        pos = self._audio_player.get_position()
        self._waveform_widget.set_position(pos)
        self._poll_id = self.after(100, self._update_playhead)
```

The timer is cancelled when playback stops or the waveform widget is destroyed.

## 9. Performance Considerations

| Concern | Mitigation |
|---------|------------|
| Large audio files (50MB+ WAVs) | Raw byte sampling reads in chunks, does not load entire file into memory. Use `file.seek()` to jump to sample points. |
| Waveform generation blocking UI | Always runs on a background thread. UI shows "loading" state until data arrives. |
| pygame mixer initialization time | Init once at app startup (in `AudioPlayer.__init__`). Takes ~100ms. Acceptable. |
| Memory from cached waveforms | LRU cache capped at 50 entries (~120KB). Negligible. |
| Rapid play/stop cycling | `AudioPlayer.play()` calls `stop()` first, ensuring clean state. pygame handles this gracefully. |
| Canvas redraw performance | 300 rectangles on a tkinter Canvas is well within performance bounds. Redrawing the playhead (one line) every 100ms is trivial. |

## 10. Error Handling

| Error Case | Handling |
|------------|----------|
| File not found (moved/deleted) | `AudioPlayer.play()` returns `False`. SuggestionPanel shows a toast: "File not found: {filename}". Play button reverts to ▶. |
| Unsupported format | `pygame.mixer.music.load()` raises `pygame.error`. Caught in `AudioPlayer.play()`, returns `False`. Toast with: "Cannot play: {filename}". |
| Permission denied | Caught as `OSError` in `AudioPlayer.play()`. Same toast pattern. |
| Corrupt file | pygame raises `pygame.error` on load or play. Caught, toast shown. |
| Waveform generation fails | `WaveformGenerator` catches all exceptions, returns a flat-line waveform (all 0.5 values) as fallback. Logs the error. Playback still works — waveform is cosmetic. |
| pygame init fails | `AudioPlayer.__init__` catches `pygame.error`. Sets `self._available = False`. All play calls become no-ops. Play buttons are hidden or disabled. App still functions for track selection. |

## 11. PyInstaller Bundling Changes

Update `serato-sidecar.spec`:

```python
# Add pygame collection
pg_datas, pg_binaries, pg_hiddenimports = collect_all("pygame")
datas += pg_datas
binaries += pg_binaries

# Add to hidden imports list
hiddenimports += [
    "source.services.audio_player",
    "source.services.waveform",
    "source.ui.waveform_widget",
] + pg_hiddenimports
```

**Bundle size impact:** pygame adds ~3-5MB of SDL2 shared libraries to the distribution. Total installer size increases from ~35MB to ~40MB. Acceptable.

## 12. Implementation Plan

Ordered by dependency. Each phase is a self-contained, testable deliverable.

### Phase 1: Audio Playback Service (no UI)
- Add `pygame` to `requirements.txt`.
- Create `source/services/audio_player.py` with the `AudioPlayer` class.
- Create `AudioPlayer` instance in `app.py.__init__()`, call `shutdown()` in a `protocol("WM_DELETE_WINDOW")` handler.
- Manual testing: verify play/pause/stop/seek works with MP3, WAV, FLAC files.
- **Effort:** Small

### Phase 2: Waveform Data Generation (no UI)
- Create `source/services/waveform.py` with the `WaveformGenerator` class.
- Implement raw byte sampling for MP3 and WAV.
- Add LRU cache.
- Manual testing: verify waveform data output looks reasonable (print amplitude values).
- **Effort:** Small

### Phase 3: Waveform Widget (UI, no integration)
- Create `source/ui/waveform_widget.py` with the `WaveformWidget` class.
- Implement canvas rendering, click-to-seek, playhead updates, time display.
- Test in isolation with hardcoded data.
- **Effort:** Medium

### Phase 4: Integration
- Add play button column to `SuggestionPanel`.
- Wire play button → `AudioPlayer.play()`.
- Wire play → `WaveformGenerator.get_waveform()` → `WaveformWidget`.
- Wire click-to-seek → `AudioPlayer.seek()`.
- Wire track-end → reset UI state.
- Wire track selection (row click / "+") → stop playback.
- Add playhead position polling timer.
- Handle all error cases with toast notifications.
- **Effort:** Medium

### Phase 5: PyInstaller & Polish
- Update `serato-sidecar.spec` with pygame collection.
- Test bundled build on Windows.
- Verify macOS build (CI).
- Polish: loading states, smooth transitions, keyboard shortcuts (Space to pause?).
- **Effort:** Small

## 13. Future Enhancements (Out of Scope)

- **Volume control** — slider on the waveform widget. Low effort, add when users ask.
- **High-fidelity waveforms** — decode to PCM via pygame sndarray + numpy. Better visual accuracy, higher dependency cost.
- **Frequency-colored waveforms** — color bars by frequency content (bass = warm, treble = cool). Requires FFT, significant complexity.
- **Preview in Now Playing dashboard** — play the currently selected track from the dashboard, not just suggestions.
- **Cue point markers** — if Serato cue point data can be read, overlay them on the waveform.
- **Keyboard shortcuts** — Space to play/pause, arrow keys to seek.
