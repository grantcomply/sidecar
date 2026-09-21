# Implementation Plan: Virtual MIDI Deck Loader

> **For:** Engineer agent
> **Companion:** `architect-blueprint.md` (same folder). Read §1.3 (the semantic limit) and §2 (ADR-014, D1–D10) first.
> **Principle:** Phases 1–2 change nothing a user can see (MIDI is opt-in and off by default). Phase 3 adds the config/Learn dialog. **Phase 4 is blocked until the user answers blueprint O1.** Run `python -m pytest` after every phase.
> **Hard rules for this feature:** no `sleep` on the Tk thread; only the `midi-out` worker touches the port; no bare `except Exception` (use `_MIDI_ERRORS` + `logger.warning`); the app must start normally with `mido` / `python-rtmidi` missing or uninstalled.

Legend: each task cites `file:line` for where the change lands. `<!-- UI-designer to revise -->` marks layout, copy, or state choices the UI designer owns. The engineer builds structure and behaviour only.

---

## Phase 0: Validation spike (no app code, ~30 min). Gate for everything else

Goal: prove the MIDI → Serato path on real hardware and settle blueprint §1.3 before writing code.

### T0.1: Manual spike on Windows
- Install loopMIDI and create a port named `loopMIDI Port`.
- In a scratch venv (**not** in the repo): `pip install mido python-rtmidi`.
- Throwaway script in the session scratchpad:
  ```python
  import time, mido
  mido.set_backend("mido.backends.rtmidi", load=True)
  print(mido.get_output_names())                      # expect e.g. 'loopMIDI Port 1'
  name = next(n for n in mido.get_output_names() if n.startswith("loopMIDI"))
  with mido.open_output(name) as port:
      for _ in range(10):
          port.send(mido.Message("note_on", note=60, velocity=127, channel=0))
          time.sleep(0.05)
          port.send(mido.Message("note_off", note=60, velocity=0, channel=0))
          time.sleep(2)
  try:
      mido.open_output("Serato Sidecar", virtual=True)
  except Exception as e:                                # spike only, record the exact type
      print(type(e), e)
  ```
- In Serato DJ Pro: enter MIDI Assign mode, pick the deck-load target, let the script bind note 60. Repeat for note 62 on the other deck.

**Record in this plan folder (append a "Phase 0 findings" section below):**
1. Exact port-name string(s) WinMM reports (confirms the prefix-match need, blueprint R4).
2. The exception type raised by `virtual=True` on Windows (fills `_MIDI_ERRORS`, T2.1).
3. Which Serato UI element or action maps "load to deck", and confirmation that it loads **Serato's highlighted track** (blueprint §1.3).
4. Serato's built-in keyboard shortcut for load-to-deck, if any (the value bar for Option A).
5. Whether "Protect playing deck" exists and blocks loads onto a playing deck (blueprint R2).
6. Whether custom MIDI mapping works in the user's Serato edition (blueprint R8).
7. That `Microsoft GS Wavetable Synth` shows up in `get_output_names()` (the reason auto-fallback is rejected, blueprint D5).

### T0.2: Get the user's answer to blueprint O1 (and O3, O5, O6)
The architect/orchestrator puts these to the user. Record the answers here. Phases 1–3 may go ahead meanwhile. Phase 4 may not.

**Gate:** notes reach Serato and bind; §1.3 confirmed or refuted. If refuted (Serato *can* be told which track to load), stop and return to the architect.

---

## Phase 1: Dependencies, config, pure core (invisible)

### T1.1: Dependencies
**File:** `requirements.txt:5` (append after `pygame>=2.5.0`)
```
mido>=1.3.2,<2
python-rtmidi>=1.5.8,<2
```
- Before committing, check for binary wheels: `pip download python-rtmidi==<pin> --only-binary=:all: --python-version 3.11 --platform win_amd64` and the same for `macosx_11_0_arm64` (the macos-latest runner is Apple Silicon). Adjust the pin to the newest version that has both (blueprint R3).
- Confirm `pip install -r requirements.txt` resolves with the existing `packaging>=23.0` (`requirements.txt:3`). mido depends on `packaging`.

### T1.2: Config constants
**File:** `source/config.py:110` (after `KEY_OFFSET_RANGE`, before `CAMELOT_COLORS` at `:112`)
Add a `# ── Virtual MIDI (ADR-014) ──` block:
```python
MIDI_CHANNEL = 0              # mido channels are 0-indexed: 0 == "Channel 1" in Serato
MIDI_NOTE_LEFT = 60           # C4 → Deck 1 / left
MIDI_NOTE_RIGHT = 62          # D4 → Deck 2 / right
MIDI_VELOCITY = 127
MIDI_NOTE_OFF_DELAY_S = 0.05  # 50 ms, slept on the midi-out worker only
MIDI_SEND_QUEUE_MAX = 8       # excess presses are dropped, not backlogged
MIDI_LEARN_REPEAT_MS = 2000
MIDI_LEARN_MAX_REPEATS = 15   # auto-stop ≈ 30 s (live-set safety, blueprint D10/R2)
MIDI_VIRTUAL_PORT_NAME = "Serato Sidecar"   # blueprint O6
MIDI_PREFERRED_PORT_PREFIXES: dict[str, tuple[str, ...]] = {
    "win32": ("loopMIDI",),
    "darwin": ("IAC Driver",),
}
```
Do **not** import `mido` in `config.py`.

### T1.3: Settings accessors
**File:** `source/config.py:85` (after `save_subcrates_dir`, following the `:75-85` pattern)
- `get_midi_enabled() -> bool`: `_load_env().get("MIDI_ENABLED", "").strip().lower() == "true"`. Default is `False` (blueprint D6 / O3).
- `save_midi_enabled(enabled: bool) -> None`: writes `"true"` / `"false"`.
- `get_midi_port_name() -> str | None`: empty or missing gives `None`.
- `save_midi_port_name(name: str | None) -> None`: `None` writes an empty string.
Type hints are required (`docs/coding-standards.md:25`).

### T1.4: Pure core in the new service module
**File:** `source/services/midi_service.py` (new). Top of file only; no `mido` import at module level.
- Module docstring: purpose, ADR-014, and the §1.3 limitation in one sentence ("loads the track selected **in Serato**, not in Sidecar").
- `logger = logging.getLogger(__name__)`.
- `class Deck(str, Enum)`: `LEFT = "left"`, `RIGHT = "right"`; `@classmethod parse(value: Deck | str) -> Deck` (case-insensitive, strips whitespace, `ValueError` on anything else).
- `@dataclass(frozen=True) class MidiSettings`: fields as in blueprint §3, plus `@classmethod from_config()` reading the T1.2 constants and picking prefixes via `MIDI_PREFERRED_PORT_PREFIXES.get(sys.platform, ())`.
- `@dataclass(frozen=True) class MidiMsgSpec`: `type: str`, `note: int`, `channel: int`, `velocity: int`.
- `def deck_messages(deck: Deck, settings: MidiSettings) -> tuple[MidiMsgSpec, MidiMsgSpec]`: returns `(note_on vel=settings.velocity, note_off vel=0)` for the deck's note.
- `class MidiState(Enum)`: `DISABLED, UNAVAILABLE, NO_PORT, CONNECTING, CONNECTED, ERROR`.
- `@dataclass(frozen=True) class MidiStatus`: `state: MidiState`, `port_name: str | None = None`, `message: str = ""`.
- `@dataclass(frozen=True) class PortChoice`: `name: str | None`, `virtual: bool`, `reason: str`.
- `def choose_port(available: list[str], saved: str | None, preferred_prefixes: tuple[str, ...], virtual_supported: bool, virtual_name: str) -> PortChoice`, implementing blueprint D5 exactly:
  1. `saved` exact match → return it.
  2. `saved` prefix match (`name.startswith(saved)` or `saved.startswith(name)`, which covers WinMM's `" 1"` suffix appearing or disappearing) → return the first match.
  3. First `available` name starting with any of `preferred_prefixes`.
  4. If `virtual_supported` → `PortChoice(virtual_name, virtual=True, ...)`.
  5. Else `PortChoice(None, False, "no loopback port found")`.
  - **Never** returns an arbitrary non-matching port (blueprint D5 rejection). Add a comment saying why (GS Wavetable Synth).
- `def virtual_ports_supported(platform: str = sys.platform) -> bool`: `platform != "win32"`.

### T1.5: Unit tests for the pure core
**File:** `tests/services/test_midi_service.py` (new; mirrors `tests/services/test_file_times.py` style; names `test_<what>_<condition>_<expected>`, `docs/coding-standards.md:85`)
- `Deck.parse`: `"left"`, `"LEFT "`, `Deck.RIGHT` pass; `"centre"` raises `ValueError`.
- `deck_messages`: left gives note 60, right gives 62, channel 0, on-velocity 127, off-velocity 0, in the order (note_on, note_off).
- `choose_port`:
  - saved exact match wins over a preferred prefix;
  - saved `"loopMIDI Port"` matches available `"loopMIDI Port 1"` (the R4 case);
  - no saved port, preferred prefix picks loopMIDI;
  - **only `["Microsoft GS Wavetable Synth"]` available on win32 gives `name=None`** (the safety test);
  - darwin with nothing available gives virtual `"Serato Sidecar"`;
  - `virtual_supported=False` with nothing gives `None`.
- `MidiSettings.from_config()` channel is `0` (locks the 0-index decision).
- Config accessors: monkeypatch `source.config.ENV_FILE` to `tmp_path / "settings.env"`; round-trip enabled/port; missing keys give `False` / `None`.

**Gate:** `python -m pytest` green. App unchanged.

---

## Phase 2: `MidiService` worker + app lifecycle (invisible unless `MIDI_ENABLED=true` is set by hand)

### T2.1: Lazy import and error tuple
**File:** `source/services/midi_service.py` (below the T1.4 code). Pattern: `source/services/audio_player.py:16-35`.
- Module globals `_mido = None`, `_MIDI_ERRORS: tuple[type[BaseException], ...] = (OSError, RuntimeError, NotImplementedError, ValueError)`.
- `def _ensure_mido() -> bool`: `import mido`; `mido.set_backend("mido.backends.rtmidi", load=True)`; then try `import rtmidi` and extend `_MIDI_ERRORS` with the rtmidi error base class(es) that exist in the installed version (e.g. `rtmidi.RtMidiError`; use `getattr` so a version difference can't crash). Catch `(ImportError, OSError)` → `logger.warning(...)`, return `False`. Include the exception type recorded in T0.1 #2.

### T2.2: `MidiService` class
**File:** `source/services/midi_service.py`
- `__init__(self, settings: MidiSettings, on_status_change: Callable[[MidiStatus], None] | None = None, backend: object | None = None)`.
  - `backend` is the **test seam**: an object with `get_output_names()`, `open_output(name, virtual=False)`, and `Message(...)`. `None` means use lazy `mido` on first need.
  - Initial status `MidiStatus(MidiState.DISABLED)`. **No thread started, no import** here.
- Commands: small private frozen dataclasses (`_Connect(port_name)`, `_SendDeck(deck)`, `_Disconnect()`, `_Stop()`) or a tagged tuple. Engineer's choice; keep them private.
- `self._queue = queue.Queue(maxsize=settings.queue_max)`; `self._lock = threading.Lock()`; `self._status`; `self._thread: threading.Thread | None = None`; worker-only fields `self._port`, `self._port_name`, `self._saved_port_name`.
- Properties:
  - `available -> bool`: backend importable (calls `_ensure_mido()` once when `backend is None`).
  - `status -> MidiStatus`: read under `_lock`.
- `_set_status(status)`: set under `_lock`, then call `on_status_change(status)` **outside** the lock. The service does not guard the callback with any Tk-specific handling (it knows nothing about Tk). `app`'s wrapper does its own guarding (T2.4).
- `_ensure_worker()`: start a daemon `threading.Thread(target=self._worker_loop, daemon=True, name="midi-out")` if not running.
- Public API (all non-blocking; all callable from the Tk thread):
  - `list_output_ports() -> list[str]`: synchronous enumeration; returns `[]` and logs on `_MIDI_ERRORS` or when unavailable.
  - `connect(port_name: str | None) -> None`: if not `available`, set `UNAVAILABLE` and return. Else `_ensure_worker()`, set `CONNECTING`, enqueue `_Connect`. If the queue is full, log and set `ERROR`.
  - `disconnect() -> None`: enqueue `_Disconnect` if the worker is running.
  - `send_deck_load_signal(deck: Deck | str) -> bool`: `Deck.parse(deck)` (let `ValueError` propagate, since that is a programming error). If the state is not `CONNECTED` **and** not `ERROR` (ERROR triggers a lazy reconnect, blueprint D9) → return `False`. `put_nowait(_SendDeck)`; on `queue.Full`, `logger.warning("MIDI send queue full, dropping %s", deck)` and return `False`. Return `True`.
  - `shutdown(timeout: float = 0.5) -> None`: if the worker is running, `put(_Stop(), timeout=timeout)` (blocking put with timeout, so `Stop` is always enqueued **after** pending sends), then `join(timeout)`. Log if still alive (daemon backstop). Set `DISABLED` without firing the callback (the app is closing).
- Worker (`_worker_loop`), the **only** code that touches the port:
  - `_Connect`: `_close()` any open port; `choose_port(backend.get_output_names(), port_name, settings.prefixes, virtual_ports_supported(), settings.virtual_name)`; `open_output(choice.name, virtual=choice.virtual)` when `choice.name`; status `CONNECTED(port_name)` or `NO_PORT` / `ERROR(message)`. Remember `_saved_port_name = port_name` for lazy reconnect.
  - `_SendDeck`: if `self._port is None` (state ERROR), try one re-open via the `_Connect` logic with `_saved_port_name`; if that fails, drop and keep `ERROR`. Then `_send_pair(deck)`: build messages from `deck_messages(...)`, send note_on, `time.sleep(settings.note_off_delay_s)`, send note_off. On `_MIDI_ERRORS` → log, `_close()`, status `ERROR("Lost connection to <port>")`. **Always attempt note_off in a `finally`** if note_on succeeded, to avoid stuck notes.
  - `_Disconnect`: `_close()`, status `DISABLED`.
  - `_Stop`: `_close()`, return from the loop.
  - `_close()`: `port.close()` guarded by `_MIDI_ERRORS`; `self._port = None`.
  - Wrap each command's handling so an unexpected `_MIDI_ERRORS` never kills the worker loop.

### T2.3: Worker tests with a fake backend
**File:** `tests/services/test_midi_service.py` (extend)
- `FakePort` records `(monotonic_time, msg)` and can be told to raise on send. `FakeBackend.get_output_names()` returns a configurable list; `open_output` returns a `FakePort` (or raises).
- Tests (use `MidiSettings(... note_off_delay_s=0.05)`; poll the fake with a short deadline instead of long sleeps):
  - connect to `loopMIDI Port 1` gives status CONNECTED and fires the callback.
  - `send_deck_load_signal("left")` **returns in < 10 ms** (proves it doesn't block the caller), and the fake then receives note_on 60 followed by note_off 60 with Δt ≥ 0.045 s.
  - 5 rapid alternating left/right sends: messages arrive as strictly paired on/off, never interleaved (on L, off L, on R, off R …).
  - queue overflow: with a tiny `queue_max`, extra sends return `False` and don't raise.
  - send while DISABLED returns `False`, no messages.
  - send error on note_on gives status ERROR; the next send re-opens once (fake `open_output` called twice) and succeeds.
  - `shutdown()` with 3 pending sends: all 3 pairs are delivered before the port is closed; the worker thread is no longer alive.
  - backend unavailable (simulate `_ensure_mido` returning False via monkeypatch) → `connect()` sets UNAVAILABLE, and `send` returns `False`. **No exception.**
  - only `["Microsoft GS Wavetable Synth"]` on win32 (monkeypatch `sys.platform`) → NO_PORT, `open_output` never called.

### T2.4: App ownership, startup connect, status marshalling
**File:** `source/app.py`
- Imports (`:8`, `:12`): add `get_midi_enabled, get_midi_port_name` to the `source.config` import; `from source.services.midi_service import Deck, MidiService, MidiSettings, MidiState, MidiStatus`. This is safe because `midi_service` does not import `mido` at module level (T1.4).
- `__init__` (`:36-40`): add `self._closing = False`, `self._midi_dialog = None`, and after `self._audio_player = AudioPlayer()` (`:40`):
  `self._midi = MidiService(MidiSettings.from_config(), on_status_change=self._on_midi_status_threadsafe)`.
- After `self._check_for_updates_async()` (`:44`): `self._start_midi_if_enabled()`.
- New section `# ── MIDI (ADR-014) ──` after the update-check section (after `:223`):
  - `_start_midi_if_enabled()`: `if get_midi_enabled(): self._midi.connect(get_midi_port_name())`.
  - `_on_midi_status_threadsafe(status)`: called on the **worker** thread. `if self._closing: return`; `try: self.after(0, lambda s=status: self._on_midi_status(s))` / `except (RuntimeError, tk.TclError): logger.debug(...)`. Precedent: `:250-251`.
  - `_on_midi_status(status)` (Tk thread): update deck-button availability (Phase 4 hook; a no-op until then); forward to the open MIDI dialog if any; **toast policy:** if `status.state in (NO_PORT, UNAVAILABLE, ERROR)` **and** `get_midi_enabled()`, `_show_toast(<warning>, "#ffc107", duration=10000, action_label="MIDI Setup", action_callback=self._open_midi_config)` (`:137-171`). Show it at most once per state transition, not on every retry. **UI decision (ui-design-brief.md "Warning toast"):** colour `#ffc107` is a new **Warning** token, proposed for design-guide §3 (not yet applied). Copy — Windows: `"MIDI enabled but no port found. Start loopMIDI, then reconnect."` macOS: `"MIDI enabled but no port found. Enable the IAC Driver, then reconnect."` Driver unavailable: `"MIDI driver not available on this system."` Action button label `"MIDI Setup"`.
  - `_on_load_deck(deck: Deck)`: Phase 4 wiring (T4.x); in Phase 2 it is just `self._midi.send_deck_load_signal(deck)` and a `logger.info`.

### T2.5: Shutdown ordering
**File:** `source/app.py:118-121` (`_on_close`)
New order:
1. `self._closing = True`
2. Destroy the MIDI dialog if it exists (cancels any Learn repeat, T3.3), guarded by `tk.TclError`.
3. `self._midi.shutdown()`
4. `self._audio_player.shutdown()` (existing)
5. `self.destroy()` (existing)

**Gate (manual):** with `MIDI_ENABLED` absent, the app starts exactly as before (no import of `mido`: check with `python -X importtime main.py 2>&1 | findstr mido` → nothing). With `MIDI_ENABLED=true` and loopMIDI running, the log shows CONNECTED. With loopMIDI closed, the warning toast appears once and the app is otherwise normal. With `pip uninstall python-rtmidi`, the app starts, the toast says unavailable, and there is no traceback. `python -m pytest` green.

---

## Phase 3: MIDI Config / Learn dialog + entry point (first visible change)

### T3.1: Dialog skeleton
**File:** `source/ui/midi_config_dialog.py` (new). Model on `SettingsDialog` (`source/ui/sync_panel.py:7-83`) for construction and centring (`:57-64`).
- `class MidiConfigDialog(ctk.CTkToplevel)`, `__init__(self, master, midi: MidiService, on_port_saved: Callable[[str | None], None])` (blueprint D2: the dialog receives the service; persistence goes back through the callback so the dialog doesn't import config writers).
- **Not modal (confirmed):** no `grab_set()`, because the user must click in Serato while it's open (blueprint O4, settled). `transient(master)` only. This is a new dialog shape for the codebase — `SettingsDialog` is the only other `CTkToplevel` and it *is* modal (`sync_panel.py:16`); don't copy `grab_set()` from it by habit. Propose a "Non-modal control dialog" row for design-guide §5 at merge.
- `protocol("WM_DELETE_WINDOW", self.destroy)`; override `destroy()` to call `self._stop_repeat()` before `super().destroy()`.

**UI decision (settled — full detail in `ui-design-brief.md` "MIDI Config dialog"):**
- Row 0: **Port** label + dropdown (`CTkOptionMenu` fed by `midi.list_output_ports()`; loopback-eligible ports listed first, unsuffixed; non-loopback ports appended `" (not a loopback port)"` and shown in muted grey; empty list shows a disabled `"No ports found"` row), plus **Refresh** and **Connect** buttons. Default selection label `"Auto (recommended)"`.
- Row 1: **Status** line from `midi.status`, with a glyph **and** text (never colour alone, per design-guide §7.2): `"● Connected — {port name}"` (green) / `"Connecting…"` / `"⚠ No port found"` (amber) / `"✕ Lost connection to {port name}"` or `"✕ MIDI driver not available on this system"` (red).
- Row 2: **Setup help** text, chosen by `sys.platform`. Windows: `"Serato needs a virtual MIDI port to receive signals from Sidecar. Install loopMIDI (free), create a port, then select it above."` plus a `"Download loopMIDI"` link button (opens browser, same pattern as the update toast's action button, `app.py:215-223`). macOS: `"Open Audio MIDI Setup → IAC Driver → check 'Device is online' — or leave this on Auto to use Sidecar's own virtual port."` A permanent one-line note of the §1.3 limit, always visible (not just in setup help): `"Serato loads whichever track is currently highlighted in its own library — not the track selected in Sidecar."`
- Row 3: section header `"Test & mapping"`, then **`Emit Test Signal — Deck 1`** and **`Emit Test Signal — Deck 2`** buttons (one-shot; button text matches the original feature request's naming for user familiarity).
- Row 4: `CTkSwitch` **`Repeat every 2s`**, one per deck, mutually exclusive. While active, label becomes `"Repeating — {n} left (stops in ~{n*2}s)"` and the switch itself should read visually "hot" (filled/accent track), not just a position change — this is the clear "firing" state blueprint D10 asks for. Persistent safety line near the switches (not just while firing): `"Once mapped, every signal really loads a track in Serato. Stop repeating before you play."`
- Row 5: Serato mapping steps, header `"Map these signals in Serato"`, short numbered list. **Wording is a placeholder pending Phase 0 findings** — do not invent exact menu names; draft copy: `"1. In Serato, turn on MIDI Assign mode. 2. Click the deck's Load control in Serato. 3. Click 'Emit Test Signal' for the matching deck here. 4. Turn off MIDI Assign mode to save the mapping."` Tighten once T0.1 reports back.

### T3.2: Dialog behaviour
**File:** `source/ui/midi_config_dialog.py`
- Refresh: repopulate the dropdown from `midi.list_output_ports()`; keep the current selection if it's still present.
- Connect: `name = None if selection == "Auto" else selection`; `self._on_port_saved(name)`; `self._midi.connect(name)`.
- `set_status(status: MidiStatus)`: public, called by `app._on_midi_status` (T2.4) on the Tk thread; updates the status line, enables or disables the test and repeat buttons (only when `CONNECTED`), and stops any running repeat if the state leaves `CONNECTED`.
- Test buttons: `self._midi.send_deck_load_signal(Deck.LEFT / Deck.RIGHT)`; if it returns `False`, flash a status message.

### T3.3: Learn-mode repeat (blueprint D10)
**File:** `source/ui/midi_config_dialog.py`
- State: `self._repeat_deck: Deck | None`, `self._repeat_after_id: str | None`, `self._repeat_count: int`.
- `_start_repeat(deck)`: `_stop_repeat()` first (mutual exclusion); set the deck, `count = 0`; `_repeat_tick()`.
- `_repeat_tick()`: if the state is not `CONNECTED` or `count >= MIDI_LEARN_MAX_REPEATS`, then `_stop_repeat()` and return. Otherwise send, `count += 1`, update the label, and `self._repeat_after_id = self.after(MIDI_LEARN_REPEAT_MS, self._repeat_tick)`.
- `_stop_repeat()`: `after_cancel` if an id is set (guard `tk.TclError`); reset state; reset the toggle visuals. **Idempotent**, since it is called from destroy, the toggles, `set_status`, and the cap.
- No threads. Each tick only enqueues on the service.

### T3.4: Entry point and dialog singleton in app
**File:** `source/app.py`
- Top bar (`:56-78`): add a MIDI button **left of** ⚙ (column 1, with ⚙ moved to column 2), same styling as `settings_btn` (`:70-77`: 32×32, transparent, grey, hover-highlight). **UI decision (settles O4):** label is the text `"MIDI"` at 11pt, not a Unicode icon (music/plug glyph coverage is inconsistent across Windows/macOS fonts). Always visible, even when MIDI is disabled — it's the feature's only discovery path. No duplicate entry point in `SettingsDialog` (`source/ui/sync_panel.py:41-55`) — one source of truth for the dialog singleton.
- `_open_midi_config()`: singleton pattern copied from `_open_settings` (`:227-237`). Construct with `midi=self._midi, on_port_saved=self._on_midi_port_saved`; immediately call `dialog.set_status(self._midi.status)`.
- `_on_midi_port_saved(name)`: `save_midi_port_name(name)`; `save_midi_enabled(True)`. Import both from `source.config` (`:8`).
- `_on_midi_status` (T2.4): if the dialog exists, call `self._midi_dialog.set_status(status)` (guard `tk.TclError`, as at `:271-277`).

**Gate (manual, Windows + Serato):** open the dialog; the port list shows loopMIDI first and GS Wavetable Synth marked; Connect → CONNECTED; the Deck 1 test binds in Serato's assign mode; the repeat fires every 2 s and stops after 15, on toggle, on switching deck, on closing the dialog, and on closing the app (check the log: no sends after close). Restart the app: it auto-connects to the saved port.

---

## Phase 4: Deck-load buttons. **BLOCKED on blueprint O1**

Do not start until the user has answered O1 and the answer is recorded under T0.2. The tasks below implement the **default recommendation (Option B), revised by the UI designer to split "copy" and "load" into two separate controls** (see `architect-blueprint.md` D-COPY and `ui-design-brief.md` "Central design decision"): a single combined click cannot work correctly, because the MIDI load fires immediately, before the DJ has pasted into Serato and confirmed the right track is highlighted. If the user picks Option A instead, drop T4.1-T4.3 and see the Option A note below. If they insist on per-row buttons, see T4.5.

**UI decision (settled — full detail in `ui-design-brief.md`):** `track_frame` row 4 holds three controls left-to-right: `Copy Track Name` (secondary/grey styling, always enabled once a track is selected, no MIDI dependency) → `◀ Load Left Deck` (accent styling, gated on `CONNECTED`) → `Load Right Deck ▶` (same). A 24px gap separates the Copy button from the Load pair to signal "prep" vs. "fire." Feedback on click is a transient text-swap-and-revert (`"Copy Track Name"` → `"Copied ✓"`; `"◀ Load Left Deck"` → `"Sending…"` → `"Sent ✓"` → back), modelled on `SettingsDialog.set_syncing()`'s text swap (`sync_panel.py:75-80`) but timed and self-reverting. The disabled window during the swap (~750 ms) doubles as the R2 double-click debounce — no separate timer needed.

### T4.1: Dashboard API
**File:** `source/ui/track_detail.py`
- `__init__` signature (`:15`): add `on_load_deck: Callable[[Deck], None] | None = None` and `on_copy_track: Callable[[Track], None] | None = None`. Store both. Add `self._current_track: Track | None = None`.
- `set_track` (`:127`): store `self._current_track = track`; enable the Copy button (always, once a track is set); enable the Load buttons only if MIDI is currently available.
- New `set_midi_available(available: bool) -> None`: shows/hides the deck-action row per `MIDI_ENABLED`, and within a shown row, enables/disables the two Load buttons per connection state. The Copy button's enabled state is independent — driven only by `set_track`, never by this method.

### T4.2: Buttons
**File:** `source/ui/track_detail.py:99` (after `info_label`, as `track_frame` row 4)
- A frame with three `CTkButton`s in order: `Copy Track Name`, `◀ Load Left Deck`, `Load Right Deck ▶`. Exact copy, styling, and tooltips per `ui-design-brief.md` "Now Playing dashboard: deck-action row" and "Microcopy."
- `Copy Track Name.command` → `self._on_copy_track(self._current_track)` when a track is set; flashes `"Copied ✓"` locally (no MIDI/app round-trip needed for the flash itself).
- Load buttons' `command` → `self._on_load_deck(Deck.LEFT/RIGHT)` when `self._current_track` is set and the button is enabled; flashes `"Sending…"` immediately, then `"Sent ✓"` after the callback returns, then reverts.
- Row hidden entirely when `MIDI_ENABLED=false` (default). Load buttons individually disabled (not hidden) when MIDI is enabled but not `CONNECTED`, with a `Tooltip` (`source/ui/tooltip.py`) explaining why (copy in brief).
- The `750ms` disabled window during the text-swap is the double-click guard (blueprint R2) — no separate debounce timer.

### T4.3: Clipboard hand-off (Option B only)
**File:** `source/app.py`
- New `_on_copy_track(track)`: Tk-native, cross-platform, no dependency — `self.clipboard_clear(); self.clipboard_append(f"{track.artist} {track.title}".strip())`.
- `_on_load_deck(deck)` (from T2.4): **only** calls `self._midi.send_deck_load_signal(deck)`; on `False`, `_show_toast("MIDI not connected", "#dc3545")`. It does **not** touch the clipboard — that is `_on_copy_track`'s job, fired by a separate button (see T4.2). This is the change from the original combined-click design.

### T4.4: Wiring
**File:** `source/app.py:81-85`
- `NowPlayingDashboard(self, on_track_selected=..., on_load_deck=self._on_load_deck, on_copy_track=self._on_copy_track)`.
- In `_on_midi_status` (T2.4): `self.dashboard.set_midi_available(status.state == MidiState.CONNECTED)`.

### T4.5: (Only if explicitly requested) per-row buttons in suggestions
**File:** `source/ui/suggestion_panel.py`. **Not recommended** — confirmed (blueprint §1.3, O2 settled). Do not build unless the user explicitly overrides this recommendation. If overridden: extend `_COL` (`:75-79`), the header list (`:138-147`), and add buttons after the add button (`:445-453`). Pass the callback via the constructor (`:85-92`), not the service.

**Option A note (if the user picks the simpler global trigger instead of Option B):** drop T4.1-T4.3 entirely. Instead add two small buttons near the top-bar MIDI entry point (not track-specific, not in the dashboard), always enabled once `CONNECTED`, tooltip `"Loads whichever track is selected in Serato onto this deck."` No Copy button, no clipboard code, no `on_copy_track` callback.

**Gate (manual, with Serato):** select a track in Sidecar → click **Copy Track Name** → clipboard holds `"Artist Title"` and the button flashes `"Copied ✓"` → paste into Serato's search and confirm the right track is highlighted → click **Load Left Deck** → button flashes `"Sending…"` then `"Sent ✓"` and Serato loads its selected track to Deck 1. With MIDI disconnected, the Load buttons are disabled (Copy still works). A double-click on either button sends only one action.

---

## Phase 5: Packaging + docs

### T5.1: PyInstaller hidden imports
**File:** `serato-sidecar.spec:53-74`
Add `"source.services.midi_service"`, `"source.ui.midi_config_dialog"`, `"mido"`, `"mido.backends"`, `"mido.backends.rtmidi"`, `"rtmidi"`. mido loads its backend by name via `importlib`, so static analysis will miss `mido.backends.rtmidi`. If the frozen build still fails to load the backend, use `collect_submodules("mido.backends")` + `collect_dynamic_libs("rtmidi")` (import from `PyInstaller.utils.hooks`, `:17`).
Note in the PR: the hidden-import list already lacks several existing modules (`audio_player`, `waveform`, `filter_bar`, …). That is pre-existing drift, out of scope.

### T5.2: CI binary-wheel guard
**File:** `.github/workflows/release.yml:64` and `:153`
Change to `pip install --only-binary=python-rtmidi -r requirements.txt pyinstaller` so a missing wheel fails fast instead of trying a C++ source build.

### T5.3: Frozen-build smoke test (manual, Windows)
`pyinstaller serato-sidecar.spec --noconfirm` → run `dist/SeratoSidecar/SeratoSidecar.exe`. Open MIDI Config: the port list populates (proves the backend is bundled); Connect to loopMIDI; the test signal reaches Serato. Also run with no loopMIDI installed and confirm the app is normal.

### T5.4: User docs
- `README.md` and `docs/install-guide-for-friends.md`: an optional "Serato deck loading (MIDI)" section covering the loopMIDI install (Windows), IAC / Auto (macOS), mapping steps from the Phase 0 findings, the §1.3 limitation stated plainly, and a recommendation to enable Serato's "Protect playing deck" if Phase 0 confirmed it.

### T5.5: Architecture docs (architect to review wording at merge)
- `docs/architecture-decisions.md`: append ADR-014 from blueprint §2 (Status: Accepted once merged).
- `docs/architecture-overview.md`: services table (`:53-63`) + `midi_service.py`; UI table (`:68-76`) + `midi_config_dialog.py`; diagram (`:28-37`) + `Midi`; add a sentence to "Data Flow" (`:78-98`): first outbound path (Sidecar → loopback port → Serato).
- `docs/cross-platform-guide.md`: new "Virtual MIDI" section after "File creation time" (`:79-92`), with the per-platform table from blueprint D5 and the Windows `virtual=True` limitation.
- `docs/testing-strategy.md`: add the `midi_service` pure-core and fake-backend coverage.
- `CLAUDE.md` project structure: add the two new files.

**Gate:** `python -m pytest` green; frozen build smoke test passes; docs updated.

---

## Execution order summary
1. **T0.1 → T0.2** (spike + user answers). Must pass before any code.
2. T1.1 → T1.2 → T1.3 → T1.4 → T1.5 (invisible; tests green)
3. T2.1 → T2.2 → T2.3 → T2.4 → T2.5 (service + lifecycle; opt-in only)
4. T3.1 → T3.2 → T3.3 → T3.4 (config / Learn dialog)
5. **T4.x only after O1 is answered**
6. T5.1 → T5.5 (packaging + docs)

## Phase 0 findings
_(Engineer: fill in during T0.1 / T0.2.)_

---

## UI revisions applied

Applied by the `ui-designer` agent on 2026-09-19. Full rationale, exact copy, and open questions
live in `ui-design-brief.md` (same folder) — this section is a change log, not the source of
truth.

1. **Split "Copy" from "Load" (biggest change).** The blueprint's T4.3 combined clipboard-copy
   and MIDI-fire into one click. That doesn't work: the MIDI load fires before the DJ can paste
   into Serato and confirm the right track, so a combined click silently loads the *wrong* track.
   Replaced with two separate controls (`Copy Track Name`, then `Load Left/Right Deck`), used in
   sequence. Recorded as a new decision `D-COPY` in the blueprint and reworked T4.1-T4.4 and the
   Phase 4 gate accordingly. Flagged for explicit user sign-off (brief, Open Questions #2) since
   it changes the click-count promise implied by the original request.
2. **Deck-action row visibility.** Settled as *hidden* (not disabled) when `MIDI_ENABLED=false`;
   shown-but-disabled with a tooltip when enabled but not `CONNECTED`. Discovery happens through
   the top-bar entry point, not a disabled dashboard row.
3. **Transient button feedback + debounce, unified.** A timed text-swap-and-revert
   (`"Sending…"` → `"Sent ✓"`, `"Copy Track Name"` → `"Copied ✓"`) both confirms the click and
   serves as the R2 double-click guard — no separate debounce timer needed. New micro-pattern,
   proposed for design-guide §5.
4. **MIDI Config dialog fully specified.** Non-modal (`transient()`, no `grab_set()`) — flagged
   as a new dialog shape since `SettingsDialog` is the only other `CTkToplevel` and it *is*
   modal. Full row-by-row layout, status-line glyph+text convention (colour-blind fallback),
   platform setup copy, and repeat-toggle "firing" state specified in the brief and inlined at
   T3.1.
5. **Entry point (O4) settled.** Single top-bar `"MIDI"` text button (not an icon glyph — font
   coverage is inconsistent cross-platform), left of the gear, always visible. No duplicate
   entry point in `SettingsDialog`.
6. **Warning toast colour + copy specified.** New `Warning` / `#ffc107` token (proposed addition
   to design-guide §3, not yet applied) with exact per-platform copy and a 10000ms duration,
   matching the existing toast scale.
7. **O2 and R2 settled as design calls**, not left open: no per-row suggestion buttons; debounce
   is the transient-feedback disabled window (~750ms), not a separate mechanism.
8. **Still open (deliberately, not settled here):** O1 itself (Option A vs B — this plan builds
   for B); whether the plain-click Load button needs extra in-app friction beyond Serato's own
   "Protect playing deck" setting; whether the top-bar MIDI button should carry a connection-status
   indicator; the exact Serato menu wording in the dialog's mapping-steps list (blocked on Phase 0
   findings). See `ui-design-brief.md` "Open questions."
