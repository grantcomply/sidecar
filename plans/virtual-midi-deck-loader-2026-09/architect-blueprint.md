# Architect Blueprint: Virtual MIDI Deck Loader

> **Status:** Proposed. **Blocked on open question O1** (see §1.3 and §9) before Phase 4 (deck-load buttons).
> **Date:** 2026-09-19
> **Author:** Architect agent
> **Plan folder:** `plans/virtual-midi-deck-loader-2026-09/`
> **Related ADRs:** ADR-008 (distribution: adds a native-extension dependency and an external driver prerequisite), ADR-009 (lazy-import, degrade-to-no-op service precedent: `AudioPlayer`), ADR-001 (Tk threading constraints). Proposes **ADR-014**.
> **Companion:** `implementation-plan.md` (same folder).

---

## 1. Context

### 1.1 The request (summary)
Add a virtual MIDI output so Sidecar can trigger Serato DJ Pro's "Load to Deck" action. The request asks for:
- a `midi_service.py` module that discovers a loopback port and sends `note_on` then, after 50 ms, `note_off` (Left = note 60, Right = note 62, "Channel 1", velocity 127);
- a MIDI Config / Learn dialog with test buttons that can repeat every 2 s, so the user can bind the notes in Serato's MIDI Assign mode;
- "Load Left Deck" / "Load Right Deck" buttons next to tracks or in the track detail view;
- graceful degradation when no driver is present.

### 1.2 What Sidecar is today (relevant facts)
- Sidecar only **reads** from Serato: it parses `.crate` files and ID3 tags (`source/services/crate_parser.py`) and never writes anything back. This feature is the **first outbound integration**, the first time Sidecar *drives* Serato. That is architecturally significant.
- Services own external I/O and have no UI knowledge (`docs/architecture-overview.md:50-63`). The closest precedent is `AudioPlayer` (`source/services/audio_player.py`). It lazy-imports its optional dependency (`:16-35`), exposes `available` (`:67-70`), turns every method into a no-op when unavailable, is created once in `app.py:40`, and is shut down in `app._on_close` (`source/app.py:118-121`).
- Background work runs on daemon threads, and results come back to the UI thread through `self.after(0, ...)`. See `crate_sync` (`source/services/crate_sync.py:18-37`, consumed at `source/app.py:250-251`), the update check (`source/app.py:202-213`), and waveform generation (`source/services/waveform.py:56-63`, marshalled at `source/ui/suggestion_panel.py:554-560`).
- User settings live in `settings.env` in the platformdirs user data dir (`source/config.py:31`), read and written with `_load_env` / `_save_env` (`source/config.py:54-72`). Accessor pairs such as `get_subcrates_dir` / `save_subcrates_dir` (`source/config.py:75-85`) are the pattern to follow. Tuneable constants live in `config.py` (`docs/coding-standards.md:57-61`).
- Shipping targets are Windows and macOS on a bundled Python **3.11** (PyInstaller one-folder, `serato-sidecar.spec`; CI in `.github/workflows/release.yml:52-64,144-153`). macOS builds exist but no one has run them on a real Mac (`docs/cross-platform-guide.md:10`).

### 1.3 The key semantic problem (the top open question, O1)

> **A MIDI note sent to Serato cannot say *which* track to load.** When a note is mapped to "Load to Deck" in Serato's MIDI Assign mode, Serato loads **whatever track is currently highlighted in Serato's own library browser**. The note carries no track identity. Sidecar has no way to tell Serato "load `/Music/foo.mp3`". Serato DJ Pro has no documented public API, command line, or MIDI/OSC message that loads a specific file path, and this blueprint does not assume one exists.

So the feature as written cannot deliver what the user appears to want, which is clicking a track **in Sidecar** and having **that track** land on a deck. A "Load Left Deck" button next to a Sidecar suggestion row would load an unrelated track (whatever Serato has selected) onto a deck. During a live set that could put the wrong track on a deck the DJ is about to play. **Placing the buttons as the request describes would give a misleading UI.**

Options, with their honest limits. The user must choose. Recommendations are in §9 O1.

| # | Option | What it actually does | Limits |
|---|--------|------------------------|--------|
| A | **Load trigger only** (build as specified, labelled honestly) | Buttons mean "load *Serato's selected track* to Left/Right". Useful as a remote trigger, for example on a second screen. | Adds almost nothing over Serato's own keyboard shortcuts for loading the selected track to a deck (to verify in Phase 0). **Must not** be placed next to Sidecar track rows. |
| B | **Clipboard hand-off + load trigger** | The Sidecar button copies `"Artist Title"` to the clipboard (Tk `clipboard_append`, cross-platform, no new dependency). The DJ pastes it into Serato's search box, which highlights the track, then presses the MIDI load button (or Serato's shortcut). | Still needs manual steps in Serato (focus search, paste, check the top result). Honest, zero-risk, cheap. Search matching is Serato's, so duplicates or remixes may need a manual pick. |
| C | **Library-navigation workaround over MIDI** | Map extra notes to Serato's library "scroll up/down" controls and send N steps to move Serato's selection. | Sidecar cannot know Serato's current sort order, filter, focused crate, or selected row, so it cannot compute N. **Not viable** without reading Serato's live UI state, which is not available. Listed only to rule it out. |
| D | **OS keystroke automation** (focus Serato, type into its search, send the load shortcut) | Can get closest to "load this exact track". | Adds a new dependency (e.g. `pyautogui` / `pynput`). Steals focus from Serato mid-set. On macOS it needs the Accessibility permission, which is extra friction for an unsigned app (ADR-008). Timing is fragile, and there is a risk of typing into the wrong window during a live set. MIDI would be unnecessary for this route. **Not recommended.** |
| E | **Write a temporary Serato crate** containing the chosen track | Not a load action. It only makes the track easy to find. | Serato's behaviour when crate files change while it is running is undocumented (it may not reload them or may overwrite them). This breaks Sidecar's read-only stance towards the `_Serato_` folder. **Not recommended** without evidence. |

**Architect's recommendation:** build the MIDI plumbing (Phases 1–3). The service and the Learn dialog are needed for Options A and B and cost the same either way. **Gate Phase 4 (button placement and labelling) on the user's answer.** Default if the user does not answer: **Option B**. The buttons live in the Now Playing / selected-track context, not on every suggestion row. They copy the search string **and** fire the load trigger, and their labels say what happens. Phase 0 (a 20-minute manual spike against real Serato) must confirm the load-mapping behaviour before any app code is written.

---

## 2. Decision: ADR-014 (proposed)

### ADR-014: Outbound virtual-MIDI integration with Serato (`MidiService`)

- **Status:** Proposed
- **Date:** 2026-09-19
- **Relates to:** ADR-008 (adds `python-rtmidi`, a native extension, plus an OS loopback driver prerequisite on Windows), ADR-009 (mirrors the `AudioPlayer` lazy-import / `available` / no-op degradation pattern), ADR-001 (Tk single-thread rule).

#### Context
See §1. First outbound control channel to Serato. It involves a native dependency, a platform-specific driver, background timing (the 50 ms note-off), and a new failure mode (no port) that must never stop the app from starting.

#### Decision

**D1: Module location and name.** `source/services/midi_service.py`. The request's `midi_service.py` is kept as the file name, but the file goes in `source/services/` per the project convention (`CLAUDE.md` project structure; `docs/architecture-overview.md:50-63`). No top-level module. The request's free function `send_deck_load_signal(deck)` becomes the method `MidiService.send_deck_load_signal(deck)`. A module-level function would need a hidden global singleton, and this codebase wires services explicitly from `app.py`.

**D2: Ownership and injection.** `app.py` creates exactly one `MidiService` next to `AudioPlayer` (`source/app.py:40`) and owns its lifecycle: connect at startup (only when enabled, see D6), `shutdown()` in `_on_close` (`source/app.py:118-121`).
- **Deck-load buttons get callbacks, not the service** (`docs/coding-standards.md:52`: "UI panels should receive callbacks"). `NowPlayingDashboard` receives `on_load_deck: Callable[[Deck], None]` and `midi_available: bool` (or a setter). `app` routes the callback to the service.
- **The MIDI Config dialog receives the service instance.** It is a dedicated control surface for that one service: it lists ports, connects, reports status, and fires tests. Passing a dozen callbacks would be noise. Precedent: ADR-009 passes `AudioPlayer` into `SuggestionPanel` (`source/app.py:94-99`). This is a deliberate, documented exception, scoped to the config dialog.

**D3: Pure core, thin I/O shell.** Everything decidable without hardware is a pure function, unit-testable headless:
- `Deck` enum (`LEFT = "left"`, `RIGHT = "right"`) plus `Deck.parse(str)`, which accepts `'left'` / `'right'` (the request's signature) and raises `ValueError` otherwise.
- `deck_messages(deck, settings) -> tuple[MidiMsgSpec, MidiMsgSpec]` gives the (note_on, note_off) spec for a deck.
- `choose_port(available, saved_name, preferred_prefixes, virtual_supported) -> PortChoice` is the port-selection algorithm (D5).
The `MidiService` class is the only thing that touches `mido`.

**D4: Threading model. One worker thread owns the port.**
- `MidiService` runs **one** daemon worker thread (`name="midi-out"`) fed by a bounded `queue.Queue` of commands: `Connect(port_name|None)`, `SendDeck(deck)`, `Disconnect`, `Stop`. **All** port open, send, and close calls happen on that thread, so the port object is never used from two threads and no lock around the port is needed. We do not rely on mido or rtmidi being thread-safe.
- `send_deck_load_signal(deck)` is called on the Tk thread. It **only enqueues** (`put_nowait`) and returns at once. It returns `False` if the service is unavailable or the queue is full (logged, dropped). The worker sends `note_on`, then `time.sleep(settings.note_off_delay_s)` (0.05), then `note_off`. The sleep runs on the worker, **never on the Tk thread**.
- **Concurrent presses** (double-click, Left then Right quickly, Learn repeat overlapping a manual press): the FIFO queue serializes them. Each note_on/note_off pair finishes before the next starts, so pairs never interleave and no note is left stuck. Queue `maxsize` = `MIDI_SEND_QUEUE_MAX` (8). Beyond that, presses are dropped rather than building a backlog that would fire late loads seconds after the DJ stopped clicking.
- **Status back to the UI:** the service exposes a thread-safe `status` snapshot (a frozen `MidiStatus` dataclass read under a `threading.Lock`) and calls an optional `on_status_change(MidiStatus)` **from the worker thread**. The service knows nothing about Tk. `app.py` wraps the callback in `self.after(0, ...)`, the same pattern as `source/app.py:250-251`. Because `after()` is called from a non-Tk thread, `app` guards it with a `_closing` flag and catches `RuntimeError` / `tk.TclError`, as the existing callers do implicitly.
- The worker is started lazily on the first `connect()`. When MIDI is disabled, no thread exists and `mido` is never imported.

**D5: Port selection per platform.** `choose_port` order (first hit wins):
1. **Saved port** (`MIDI_PORT_NAME` in `settings.env`): exact match, then **prefix match**. On Windows, rtmidi/WinMM reports port names with an index suffix (e.g. `loopMIDI Port 1`), and that suffix can change between sessions.
2. **Platform-preferred loopback prefixes** from `config.MIDI_PREFERRED_PORT_PREFIXES`: `win32 → ("loopMIDI",)`, `darwin → ("IAC Driver",)`, others `()`.
3. **Create a virtual port** `mido.open_output(MIDI_VIRTUAL_PORT_NAME, virtual=True)`, **only when `sys.platform != "win32"`**. `virtual=True` is **not supported by rtmidi's Windows MM backend**, so on Windows this step is skipped entirely instead of being tried and caught. On macOS this creates a CoreMIDI source that Serato can see with no user setup. Linux/ALSA also supports it (dev only).
4. **Nothing.** Status `NO_PORT`, with the friendly warning (D7).

**Explicit rejection:** the request says to "fall back to standard output ports dynamically". This design **never auto-selects an arbitrary output port.** On Windows, `Microsoft GS Wavetable Synth` is always present. Sending note 60 to it plays an **audible piano note through the system audio output**, which on a DJ laptop may be the master out, mid-set. Hardware controller ports can also react to stray notes (LEDs, mode changes). Any port outside rule 1 or 2 has to be **chosen explicitly by the user** in the MIDI Config dialog. **UI decision (ui-design-brief.md "MIDI Config dialog"):** the port dropdown lists loopback-eligible ports first, unsuffixed; non-loopback ports (e.g. `Microsoft GS Wavetable Synth`, hardware controllers) are appended with the suffix `" (not a loopback port)"` and rendered in muted grey text — visible for debugging, never hidden, never styled as a safe default.

- **Windows:** needs a loopback driver. **loopMIDI** (Tobias Erichsen, free) is the documented default. It is not bundled or installed by us; the README / install guide links to it. Windows MIDI Services on newer Windows 11 builds may offer built-in loopback endpoints that WinMM can see. That is unverified, so it is noted as a future alternative only. The saved-port / prefix rule already covers it if the user selects it.
- **macOS:** the virtual port (rule 3) works with no setup. The IAC Driver (Audio MIDI Setup → IAC Driver → "Device is online") is the alternative and is preferred if already enabled (rule 2), because its name is stable even when Sidecar is not running. Unverified on a real Mac (same caveat as the whole macOS build).

**D6: What is configurable.**
- **User-configurable (`settings.env`), via accessors in `config.py`:** `MIDI_ENABLED` (`true` / `false`, default **false**) and `MIDI_PORT_NAME` (default empty = auto). Both are environment-specific, per `docs/coding-standards.md:61`. The dialog writes them. Choosing a port in the dialog sets `MIDI_ENABLED=true`.
- **Hardcoded constants in `config.py` (not user-editable):** `MIDI_CHANNEL = 0` (mido channels are **0-indexed**: `0` is "Channel 1" in Serato and most DJ software), `MIDI_NOTE_LEFT = 60` (C4), `MIDI_NOTE_RIGHT = 62` (D4), `MIDI_VELOCITY = 127`, `MIDI_NOTE_OFF_DELAY_S = 0.05`, `MIDI_LEARN_REPEAT_MS = 2000`, `MIDI_LEARN_MAX_REPEATS = 15`, `MIDI_SEND_QUEUE_MAX = 8`, `MIDI_VIRTUAL_PORT_NAME = "Serato Sidecar"`, `MIDI_PREFERRED_PORT_PREFIXES`.
- **Why notes and channel are not user settings:** Serato stores MIDI mappings **per input device**. Sidecar's loopback port is its own device, so its notes cannot clash with a real controller's mapping, and the Learn flow binds whatever Sidecar sends. Exposing them would add UI and support burden for no benefit. If a clash ever turns up (for example a user routes several apps into one loopMIDI port), promoting them to `.env` keys is a small change. Recorded as future.
- **Virtual port name:** `"Serato Sidecar"` instead of the request's `"Serato Virtual Controller"`, so users are not led to think it comes from Serato. **UI decision:** keep `"Serato Sidecar"` — it is unambiguous, matches the app name shown in every dialog title, and (per O6 below) the name is load-bearing for Serato's saved mappings once a user has mapped against it, so it should not change again after release.

**D7: Graceful degradation (the app must always start).**
- `mido` is **lazy-imported** inside the service (`_ensure_mido()`, mirroring `source/services/audio_player.py:22-35`), and only when MIDI is enabled or the dialog is opened. Missing packages or a failed native load (`ImportError`, `OSError`) move the status to `UNAVAILABLE`, with a reason logged. No exception reaches Tk.
- The backend is set explicitly with `mido.set_backend("mido.backends.rtmidi", load=True)` inside the guarded block. mido loads backends by name via `importlib`, which is also why PyInstaller needs hidden imports (D8).
- All mido/rtmidi calls are wrapped in a **specific** exception tuple (`_MIDI_ERRORS = (OSError, IOError, RuntimeError, NotImplementedError, ValueError)` plus `rtmidi.RtMidiError` / `SystemError` classes when importable). **No bare `except Exception: pass`** (`docs/coding-standards.md:39`; debt #6). Every caught error is logged with `logger.warning` (debt #7: `logging` is configured at `main.py:6-9`).
- **User-facing messaging:** at startup, if `MIDI_ENABLED=true` and no port is found, show one non-blocking toast via the existing `_show_toast` (`source/app.py:137-171`) with an action button that opens MIDI Config. No modal at startup. If MIDI is disabled (the default), say nothing. The dialog shows the full platform-specific setup instructions. **UI decision (ui-design-brief.md "Warning toast"):** this needs a new **Warning** colour token, `#ffc107` (proposed addition to `docs/ui-design-guide.md` §3, not yet applied). Copy: Windows — *"MIDI enabled but no port found. Start loopMIDI, then reconnect."*; macOS — *"MIDI enabled but no port found. Enable the IAC Driver, then reconnect."*; driver unavailable — *"MIDI driver not available on this system."* Action button label `"MIDI Setup"`. Duration 10000ms. Fire at most once per state transition into a warning state, not on every retry.
- **UI decision (ui-design-brief.md "States"):** deck-load buttons are **hidden entirely** (not disabled) when `MIDI_ENABLED=false` (the default) — a DJ who hasn't opted in shouldn't see non-functional controls; discovery happens via the always-visible top-bar MIDI entry point instead. When MIDI is enabled but not `CONNECTED`, the row is shown but the Load buttons are disabled with a tooltip explaining why (see brief). The **Copy Track Name** button (new, see D-COPY below) is never gated on MIDI status.

**D8: Packaging.** Add `mido` and `python-rtmidi` to `requirements.txt`. Add the hidden imports `mido.backends.rtmidi` and `rtmidi` to `serato-sidecar.spec:53-74`, because mido's dynamic backend load is invisible to PyInstaller's static analysis. Confirm that binary wheels for CPython 3.11 exist on `windows-latest` (win_amd64) and `macos-latest` (arm64 / universal2) at the pinned versions before merging. python-rtmidi builds from source need a C++ toolchain and would break CI. Add a CI guard: `pip install --only-binary=python-rtmidi`. No installer changes: loopMIDI is a user-installed prerequisite. No macOS entitlements are needed for CoreMIDI in an unsigned app (to verify on first real-Mac run).

**D9: Port lifecycle.**
- **Open:** at startup on the worker (non-blocking for the UI, which guards against slow driver enumeration), only if `MIDI_ENABLED`. Also on dialog "Connect" or a port selection.
- **Reconnect:** there is no background polling. Reconnect happens (a) explicitly from the dialog ("Refresh / Reconnect"), and (b) **once, lazily**: if a send fails, the worker marks status `ERROR`, closes the port, and on the **next** `SendDeck` attempts one re-open of the saved port before sending. Limitation: WinMM does not signal that a loopMIDI port has disappeared, and a send to a port whose loopMIDI app has quit may "succeed" silently. Documented, not solvable at this layer.
- **Close:** `shutdown()` enqueues `Stop` **behind** any pending sends (so every in-flight note_on gets its note_off), joins the worker with a timeout (`0.5 s`), and the worker closes the port on its own thread. Daemon thread as the backstop so a wedged driver never blocks exit.

**D10: Learn mode repeat lives in the dialog, driven by Tk `after()`, and is bounded.**
- "Emit test signal: Deck 1/Deck 2" is **on-demand** (a single `send_deck_load_signal`). A separate "Repeat every 2 s" toggle re-fires via `self.after(MIDI_LEARN_REPEAT_MS, ...)`. It is scheduling only; each tick just enqueues, so it never blocks. **UI decision:** the toggle is a `CTkSwitch` (not a checkbox), and while active it must read as visually "hot" — filled/accent track colour, not just a position change — plus a live label `"Repeating — {n} left (stops in ~{n*2}s)"`. This is the clear firing state D10 requires; see `ui-design-brief.md` "MIDI Config dialog."
- **Only one deck may repeat at a time.** Starting Deck 2's repeat cancels Deck 1's. Serato's assign mode binds the *last* message received, so alternating repeats would bind the wrong note.
- **Auto-stop after `MIDI_LEARN_MAX_REPEATS` (15 ≈ 30 s).** Once a mapping exists, every repeat really loads a track in Serato. A forgotten repeat must not keep loading tracks onto decks. **UI decision:** the warning copy is persistent near the repeat switches (not only shown while firing): `"Once mapped, every signal really loads a track in Serato. Stop repeating before you play."`
- **Stopped by:** the toggle, the other deck's toggle, the auto-stop cap, a disconnect or status leaving `CONNECTED`, dialog close (`WM_DELETE_WINDOW` handler plus a `destroy()` override that calls `after_cancel`), and app exit (`app._on_close` destroys the dialog **before** `midi.shutdown()`).
- Rationale for putting this in the dialog instead of the service: the repeat is a UI-session concern tied to the dialog's lifetime. Keeping it in Tk `after()` means no second timer thread and no way for a repeat to outlive its UI.

**D-COPY (UI decision, revises the request's and this blueprint's original single-click model): Copy and Load are separate controls, not one combined click.**
The request (and this blueprint's original T4.3) implied one click both copies the track name to the clipboard *and* fires the MIDI load. That doesn't work: the MIDI load fires immediately on click, before the DJ has alt-tabbed to Serato, pasted, and confirmed the right track is highlighted — so a combined click loads whatever Serato had highlighted *before* the click, silently. See `ui-design-brief.md` "Central design decision" for the full reasoning.
- **Copy Track Name** — copies `"Artist Title"` to the clipboard via Tk `clipboard_append`. No MIDI dependency; always enabled once a track is selected.
- **Load Left/Right Deck** — fires only `send_deck_load_signal(deck)`. Gated on `MidiState.CONNECTED`.
- The DJ's flow becomes: Copy → alt-tab to Serato → paste + confirm → alt-tab back (or use Serato's shortcut) → Load. Still low click-count, but no longer race-conditioned.
- This is flagged in the design brief's Open Questions for explicit user sign-off, since it changes the click-count promise implicit in the original request.

#### Consequences
- Pro: The service follows existing patterns (AudioPlayer degradation, crate_sync marshalling) and adds no new architecture concepts beyond one command-queue worker.
- Pro: The pure core (`Deck`, `deck_messages`, `choose_port`) plus a fake-port worker test give headless coverage of all the timing and ordering logic.
- Pro: Zero impact on users who don't enable MIDI: no import, no thread, no toast.
- Con: A native dependency (`python-rtmidi`) enters the build (ADR-008 risk: wheel availability, PyInstaller hidden imports).
- Con: Windows users must install loopMIDI themselves. Setup cannot be one-click.
- Con: **Does not, and cannot, load a specific Sidecar track** (§1.3). Delivered value depends on the O1 answer.
- Con: One more exception to "panels get callbacks" (the config dialog gets the service), documented.

---

## 3. Component design

```
app.py (DJTrackSelectorApp)
 ├─ self._midi = MidiService(settings=MidiSettings.from_config(),
 │                           on_status_change=self._on_midi_status_threadsafe)
 ├─ startup: if config.get_midi_enabled(): self._midi.connect(config.get_midi_port_name())
 ├─ NowPlayingDashboard(on_load_deck=self._on_load_deck)      # callback only
 ├─ MidiConfigDialog(self, midi=self._midi, on_saved=...)      # service instance (D2)
 └─ _on_close: dialog.destroy() → self._midi.shutdown() → audio.shutdown() → destroy()

source/services/midi_service.py
 ├─ class Deck(str, Enum)             LEFT="left", RIGHT="right"; parse()
 ├─ @dataclass(frozen) MidiSettings    channel, note_left, note_right, velocity, delay, queue_max, virtual_name, prefixes
 ├─ @dataclass(frozen) MidiMsgSpec     type, note, channel, velocity
 ├─ class MidiState(Enum)             DISABLED | UNAVAILABLE | NO_PORT | CONNECTING | CONNECTED | ERROR
 ├─ @dataclass(frozen) MidiStatus      state, port_name, message
 ├─ @dataclass(frozen) PortChoice      name | None, virtual: bool, reason
 ├─ def deck_messages(deck, settings) -> tuple[MidiMsgSpec, MidiMsgSpec]      # pure
 ├─ def choose_port(available, saved, prefixes, virtual_supported) -> PortChoice  # pure
 └─ class MidiService
      available: bool (property), status: MidiStatus (property, locked)
      list_output_ports() -> list[str]          # sync enumeration, UI thread, guarded
      connect(port_name: str | None) -> None    # enqueue Connect
      disconnect() -> None                      # enqueue Disconnect
      send_deck_load_signal(deck: Deck | str) -> bool   # enqueue SendDeck; never blocks
      shutdown(timeout: float = 0.5) -> None
      _worker_loop()  / _open(choice) / _send_pair(deck) / _close()
      # DI seam for tests: backend: MidoLike | None = None (defaults to lazy mido)
```

`list_output_ports()` enumerates on the UI thread for simplicity; enumeration does not open ports. If Phase 0 or 2 testing shows slow enumeration on any driver, move it onto the worker with a callback. (R6)

### Status state machine
```
DISABLED ──connect()──▶ CONNECTING ──ok──▶ CONNECTED ──send error──▶ ERROR ──next send / Reconnect──▶ CONNECTING
    │                        │ no port ─▶ NO_PORT ──Reconnect──▶ CONNECTING
    │                        └ import fail ─▶ UNAVAILABLE (terminal for the session)
    └── disconnect()/shutdown() from any state ─▶ DISABLED
```

---

## 4. Thread-safety summary

| Concern | Resolution |
|---|---|
| 50 ms note-off delay must not block Tk | `time.sleep` runs on the `midi-out` worker only. The Tk-thread API only enqueues. |
| Worker → UI callbacks | Service calls `on_status_change` on the worker. `app` wraps it in `self.after(0, ...)` (precedent `source/app.py:250-251`). Guarded by a `_closing` flag. |
| Port used from multiple threads | Impossible by construction: only the worker touches the port. |
| Concurrent presses | FIFO serialization; pairs never interleave. Bounded queue (8) drops excess presses. |
| Status reads from Tk thread | `MidiStatus` is frozen; replaced atomically under `threading.Lock`. |
| Shutdown with sends pending | `Stop` is queued after the pending sends, so every note_on gets its note_off. Join timeout 0.5 s; daemon backstop. |
| Learn repeat outliving the dialog | Tk `after()` owned by the dialog; cancelled in `destroy()`. The app destroys the dialog before `midi.shutdown()`. |

---

## 5. Affected files

| File | Change |
|------|--------|
| `source/services/midi_service.py` | **New.** D1–D10. |
| `source/config.py` | MIDI constants after `KEY_OFFSET_RANGE` (`:110`); `get_midi_enabled` / `save_midi_enabled` / `get_midi_port_name` / `save_midi_port_name` after `save_subcrates_dir` (`:81-85`). |
| `source/app.py` | Import (`:12`), create `MidiService` (`:40`), startup connect (`:44`), status marshalling + toast (`:137-171` reused), MIDI Config dialog opener modelled on `_open_settings` (`:227-237`), entry-point button in the top bar (`:56-78`), `_on_load_deck` handler, `_on_close` ordering (`:118-121`). |
| `source/ui/midi_config_dialog.py` | **New.** `MidiConfigDialog(ctk.CTkToplevel)`: port list, connect / refresh, status line, platform setup help, Deck 1/2 test buttons, bounded repeat. Modelled on `SettingsDialog` (`source/ui/sync_panel.py:7-83`) for construction/centring only. **UI decision:** non-modal, `transient(master)`, no `grab_set()`. Full layout and copy in `ui-design-brief.md` "MIDI Config dialog." New dialog shape for the codebase; propose a new design-guide §5 pattern row. | |
| `source/ui/track_detail.py` | **Phase 4, gated on O1.** `on_load_deck` callback + `set_midi_available(bool)`. **UI decision:** row 4 of `track_frame` (`:67-99`) holds three controls — `Copy Track Name` (always enabled, no MIDI dependency, per D-COPY) plus `◀ Load Left Deck` / `Load Right Deck ▶` (gated on `CONNECTED`). Full copy, states, and a "Sending…/Sent ✓" transient feedback pattern (doubles as the R2 debounce) in `ui-design-brief.md`. | |
| `source/ui/suggestion_panel.py` | **No change by default.** Per-row deck buttons are **not recommended** (§1.3). Only if the user explicitly picks Option A with per-row placement (columns `_COL` `:75-79`, header list `:138-147`, row buttons `:430-453`). |
| `source/ui/sync_panel.py` | **No change.** **UI decision (settles O4):** the MIDI entry point is a standalone top-bar button, not a link inside `SettingsDialog` — one source of truth for opening the dialog singleton. |
| `source/app.py` (top bar) | **UI decision (settles O4):** single MIDI entry point — a 32×32 icon-style button labelled `"MIDI"` (text, not a Unicode glyph — inconsistent font coverage across platforms), placed left of the existing gear (`:70-78`), styled identically (transparent, grey, hover-highlight). Always visible even when MIDI is disabled — it is the feature's only discovery path since the dashboard row hides when disabled. | |
| `requirements.txt` | Add `mido`, `python-rtmidi` (`:5`). |
| `serato-sidecar.spec` | Hidden imports (`:53-74`). |
| `.github/workflows/release.yml` | Binary-wheel guard on both install steps (`:58-64`, `:150-153`). |
| `tests/services/test_midi_service.py` | **New.** Pure-function and fake-port worker tests. |
| `README.md`, `docs/install-guide-for-friends.md` | loopMIDI / IAC setup and Serato mapping steps. |
| `docs/architecture-decisions.md` | ADR-014 (at merge). |
| `docs/architecture-overview.md` | Add `midi_service.py` to the services table (`:53-63`), `midi_config_dialog.py` to the UI table (`:68-76`), and note the first outbound integration. |
| `docs/cross-platform-guide.md` | New "Virtual MIDI" section (per-platform table as in D5). |
| `docs/testing-strategy.md` | Add the midi_service coverage expectations. |
| `docs/ui-design-guide.md` | **Proposed (not applied by this brief — apply at merge):** add a `Warning` colour token `#ffc107` to §3; add a "Non-modal control dialog" row to §5; add a "Transient button text-swap with auto-revert" row to §5. See `ui-design-brief.md` "Design-guide conflicts." |
| `CLAUDE.md` | Project structure lists the new files. Also debt #12 (stale `comments_parser.py`) can be fixed in the same edit, though that is out of scope. |

---

## 6. Phases (high level; see `implementation-plan.md`)

- **Phase 0: Validation spike (no app code). Must pass before Phase 1.** Throwaway script plus real Serato on Windows with loopMIDI. Confirm: notes arrive; Serato's MIDI Assign can bind a note to load-to-deck; it loads **Serato's selected track** (confirming §1.3); what Serato's built-in keyboard shortcut for load is (sets the value bar for Option A); whether "Protect playing deck" blocks loads. Also get the user's answer to O1.
- **Phase 1: Dependencies, config, pure core (invisible).** Requirements, config constants and accessors, `Deck`, `MidiSettings`, `deck_messages`, `choose_port`, unit tests.
- **Phase 2: `MidiService` worker + app lifecycle (invisible unless `MIDI_ENABLED=true` is set by hand).** Worker, lazy import, status, app ownership, startup connect, shutdown, warning toast. Fake-port tests.
- **Phase 3: MIDI Config / Learn dialog + entry point.** First user-visible change. Usable on its own for mapping.
- **Phase 4: Deck-load buttons (gated on O1).** Placement and semantics per the user's chosen option (default Option B in the Now Playing dashboard).
- **Phase 5: Packaging + docs.** Spec hidden imports, CI wheel guard, a PyInstaller build smoke test, README / install guide, ADR-014, overview, cross-platform guide, testing strategy.

---

## 7. Conflicts and tensions with existing ADRs / debt

| Item | Tension | Resolution |
|---|---|---|
| Request vs convention (`midi_service.py` at top level; module-level `send_deck_load_signal`) | Project convention is `source/services/` plus app-owned instances. | D1: `source/services/midi_service.py`, method on `MidiService`. |
| Request "fall back to standard output ports dynamically" | Safety: GS Wavetable Synth or hardware ports. | D5: rejected. Arbitrary ports only by explicit user choice. |
| Request "on startup attempt to connect" | Would nag every non-MIDI user with a warning. | D6/D7: startup connect only when `MIDI_ENABLED=true` (opt-in). |
| Request "buttons next to each track item" | §1.3: would load the wrong track. | Phase 4 gated on O1. Per-row buttons not recommended. |
| `docs/coding-standards.md:52` (panels get callbacks) vs ADR-009 precedent | Config dialog needs the whole service. | D2: dashboard gets callbacks. The config dialog gets the service as a documented, scoped exception. |
| ADR-008 (distribution) | New native dependency and an external driver the installer cannot provide. | D8: wheel guard, hidden imports, docs. loopMIDI stays a user prerequisite. ADR-008 is unchanged. |
| Debt #6 (bare except) | `AudioPlayer` precedent uses `except Exception` (`audio_player.py:62,147,216`). | Do **not** copy it. Use the specific `_MIDI_ERRORS` tuple and log. |
| Debt #7 (logging) | None. `logging` is configured at `main.py:6-9`. | Use `logger = logging.getLogger(__name__)`. |
| Sidecar's read-only stance towards Serato | Option E would write into `_Serato_`. | Not recommended. MIDI is outbound control, not data writes, so the read-only stance for files holds. |
| `serato-sidecar.spec:53-74` hidden-import list is already incomplete (no `audio_player`, `waveform`, `filter_bar`, `suggestion_filters`, …) | Pre-existing drift. Static analysis still finds them. | Add the new modules for consistency. Flag the drift. Out of scope to fix here. |

---

## 8. Risks

- **R1 (critical, product): the feature may not deliver the user's goal.** §1.3 / O1. Mitigation: Phase 0 spike plus a user decision before Phase 4. Honest labels.
- **R2: live-set safety.** Any mapped trigger really loads a track. A mis-click or a forgotten Learn repeat can replace the track on a deck. Mitigations: bounded repeat (D10); queue cap drops backlog (D4); buttons disabled unless connected; Serato's own "Protect playing deck" preference (verify in Phase 0) is recommended in the setup docs. **UI decision:** the "Sending…/Sent ✓" transient text-swap on the Load buttons (`ui-design-brief.md` "States") both confirms the click registered *and* disables the button for the swap's duration (~750 ms total), which serves as the double-click guard — no separate timer needed. Whether a plain fast click is safe enough, versus adding further in-app friction (press-and-hold, confirm-on-first-use), is left as an open question for the user (brief, Open Questions #3) — a live-safety tradeoff, not a styling call.
- **R3: python-rtmidi wheel availability / PyInstaller.** No wheel means a source build means a broken CI. Mitigation: pin versions after checking wheels for cp311 on both runners; `--only-binary` guard; hidden imports; Phase 5 smoke test of the frozen exe (dialog opens, port list populates).
- **R4: Windows port-name instability.** WinMM index suffixes (`loopMIDI Port 1`) can change, and Serato's mapping is keyed by device name. Mitigation: prefix match (D5). Document "keep the same loopMIDI port name". Serato may still need re-mapping if the name changes.
- **R5: macOS is unverified.** Virtual ports and IAC are standard CoreMIDI, but no one has run the Mac build (`docs/cross-platform-guide.md:10`). A virtual port only exists while Sidecar runs, so Serato may need to be restarted or re-scan MIDI devices if Sidecar starts after Serato (to verify). IAC is the more robust option if so.
- **R6: slow driver enumeration** on the UI thread (`list_output_ports`). Low likelihood. Mitigation noted in §3.
- **R7: Tk `after()` from a worker thread.** Technically outside Tk's thread contract but used throughout the codebase (crate_sync, updater, waveform). Mitigation: same pattern plus a `_closing` guard; the worker is joined before `destroy()`.
- **R8: Serato edition / licensing.** Custom MIDI mapping may be a Serato DJ **Pro** feature, not available in DJ Lite (to verify in Phase 0; do not promise it in docs until verified).

---

## 9. Open questions (for the user)

**O1 (top, blocking Phase 4): what should "Load Left/Right Deck" do, given that MIDI can only load Serato's selected track?**
Options A–E in §1.3. **Recommendation: Option B** (copy "Artist Title" to the clipboard + fire the MIDI load trigger). The buttons go in the Now Playing dashboard, or on the currently selected/next track context, **not** on every suggestion row. Label and tooltip copy must say "Loads the track selected in Serato". If the user only wants the remote trigger, use Option A with global (not per-track) buttons. Options C, D, and E are not recommended, for the reasons given.

**O2: should the deck buttons be per-row at all?** **Settled — no.** Architecturally discouraged (grid density at `source/ui/suggestion_panel.py:75-79`; misleading association) and confirmed by the UI designer: per-row buttons would imply "load *this* track," which is false under any option in §1.3. Buttons live only in the Now Playing dashboard (Option B) or the top bar (Option A). See `ui-design-brief.md`.

**O3: default for `MIDI_ENABLED`.** Recommended default `false` (opt-in; no startup warnings for non-users). Confirm with the user.

**O4: entry point for MIDI Config.** **Settled — top-bar button only.** A 32×32 icon-style `"MIDI"` button left of the existing ⚙ (`source/app.py:70-78`), always visible (even when MIDI is disabled, since it's the feature's only discovery path). No secondary entry point inside `SettingsDialog` — one source of truth for the dialog singleton. Confirmed that `SettingsDialog` calls `grab_set()` (`source/ui/sync_panel.py:16`); `MidiConfigDialog` must not, since the user needs to interact with Serato while it's open (`transient()` only). If discoverability turns out to be a problem in practice, a second entry point inside `SettingsDialog` is cheap to add later (brief, Open Questions #5).

**O5: 4-deck Serato setups.** "Left/Right" maps to Deck 1/Deck 2 in 2-deck mode. In 4-deck mode, left can be Deck 1 or 3, depending on Serato's deck focus. Out of scope for v1. Confirm the user only uses 2 decks.

**O6: virtual port name** (`"Serato Sidecar"` vs the request's `"Serato Virtual Controller"`). Low stakes. Once users have mapped against a name, changing it breaks their Serato mappings, so decide before release.
