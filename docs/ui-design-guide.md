# UI Design Guide — Sidecar

> **Status:** Starter draft — seeded from the current codebase, maintained by the `ui-designer` agent
> **Last updated:** 2026-11-07 (ui-designer, at ship of the copy-search-text feature: Success/Error tokens widened, self-confirming action button pattern, local-plus-toast success, "never say Load" rule. Design source: `plans/copy-track-search-text-2026-11/ui-design-brief.md`). Previously 2026-11-05 (architect, library-providers merge: settings dialog, playlist filter, Warning colour, noun rule)
> **Authoritative for:** visual tokens, component patterns, window layout, microcopy, and UI state conventions

This is the design counterpart to `docs/architecture-overview.md`. The architect owns
*structure*; this document owns how the app *looks, reads, and feels*. When the two
conflict, raise it — don't silently diverge.

---

## 1. Design context

Sidecar is a **desktop tool used live, mid-set, in a dark DJ booth**. That single
fact drives every design call:

- **Glanceability over density.** The DJ reads the screen in the half-second between
  beatmatches. Information must resolve at a glance, not reward study.
- **Colour is data, not decoration.** Camelot key and energy level are colour-coded
  (§3). The DJ navigates by colour first, text second.
- **Dark by default.** The app runs in CustomTkinter `dark` appearance mode. A bright
  panel in a dark booth is physically uncomfortable; there is no usable light theme.
- **Low click-count.** Picking the next track is the core loop. Every extra click or
  modal in that loop is a design failure.
- **Forgiving, never blocking.** A failed sync or a missing tag must degrade gracefully —
  the set continues. Never trap the user behind an error.

## 2. Theme & window

- CustomTkinter `dark` appearance mode, blue accent theme.
- Main window: `1300x850` default ([app.py:32](../source/app.py#L32)), `1000x650` minimum
  ([app.py:33](../source/app.py#L33)). **Every layout must survive being dragged down to
  the minimum** without clipping or overlap.
- Window layout is a 3-row grid ([app.py:51-110](../source/app.py#L51-L110)):
  - **Row 0** — top bar: toast message (left) + settings gear (right), fixed 32px.
  - **Row 1** — Now Playing dashboard: search + selected-track badges.
  - **Row 2** — a horizontal `tk.PanedWindow` with a user-draggable sash: suggestions
    (left) and setlist (right), 50/50 initial split.

## 3. Colour tokens

Colours are currently **hardcoded string literals** scattered across `config.py`,
`app.py`, and `ui/*.py` — there is no central token module (see §7.1). When citing or
proposing a colour, name it from this table so a future extraction has a vocabulary.

### Status colours (toasts, settings dialog)
Defined once in `source/config.py` (`SUCCESS_COLOR`, `WARNING_COLOR`, `ERROR_COLOR`, `INFO_COLOR`). Text always carries the meaning; colour supports it.

| Token | Hex | Meaning |
|-------|-----|---------|
| Success | `#28a745` | Sync complete, library loaded; the `Sync enabled sources` button fill; a copy completed (the `✓` button fill and the green `Copied "…"` toast) |
| Warning | `#ffc107` | Amber. Needs attention but nothing is broken: a partial sync failure, a background auto-update failure, snapshot warnings, a prompt on an empty field (`Database not found` when nothing is set up), the footer "Skipped …" line, "Turn on at least one source…". Shares its hex with the score "usable" bucket (`suggestion_panel.py`); accepted overlap |
| Error | `#dc3545` | A real failure: a wrongly chosen file, every source failed (toast with an `Open settings` button), a card whose source can't be read; a copy that failed (the `✕` button fill and the red `Couldn't copy…` toast) |
| Info | `#4AB8D4` | Update available, neutral notice, `Syncing…` in progress (cyan, so it isn't confused with amber) |

### Structural / text colours
| Token | Hex | Use |
|-------|-----|-----|
| Sash | `#333333` | PanedWindow divider |
| Card fill | `#2a2a2a` | Stat-badge and settings-card background |
| Primary text | `#ffffff` | Values, titles |
| Secondary text | `#999999` | Artist line, hints, status chips, filter group headers, switched-off card names (`config.SECONDARY_TEXT_COLOR`) |
| Tertiary text | `#666666` | Badge labels, info line. **Not** for text on the card fill (about 2.4:1) |
| Placeholder | `#555555` | Empty badge value (`—`) |

**No provider colours.** rekordbox and Serato are never colour-coded; colour is data (§1). Sources are distinguished by name only.

### Domain colours (these *are* the data — do not restyle casually)
- **Camelot keys** — `CAMELOT_COLORS`, 24 entries forming a hue wheel
  ([config.py:96](../source/config.py#L96)).
- **Energy 1–8** — `energy_color()`, cool blue (low) → hot red (high)
  ([config.py:112](../source/config.py#L112)).

## 4. Typography scale

No font family is set — CustomTkinter default. These are the *de-facto* sizes in use;
treat them as the scale and don't add new sizes without a reason.

| Size / weight | Role | Anchor |
|---------------|------|--------|
| 26 bold | Stat-badge value | [track_detail.py:116](../source/ui/track_detail.py#L116) |
| 24 bold | Now-playing track title | [track_detail.py:79](../source/ui/track_detail.py#L79) |
| 18 | Settings gear glyph | [app.py:72](../source/app.py#L72) |
| 15 | Search entry, artist line | [track_detail.py:28](../source/ui/track_detail.py#L28) |
| 12 | Dropdown rows, toast text | [app.py:66](../source/app.py#L66) |
| 11 | Info line, toast action button | [track_detail.py:97](../source/ui/track_detail.py#L97) |
| 10 bold | Column headers | [track_detail.py:58](../source/ui/track_detail.py#L58) |
| 9 bold | Stat-badge label (uppercase) | [track_detail.py:110](../source/ui/track_detail.py#L110) |

## 5. Component patterns

Cite these file:line anchors when claiming "we already do X."

| Pattern | Anchor | Notes |
|---------|--------|-------|
| **Stat badge** | [track_detail.py:103](../source/ui/track_detail.py#L103) `_make_badge` | Rounded card (corner_radius 10), `#2a2a2a` fill, tiny uppercase label over a large value. |
| **Search + dropdown** | [track_detail.py:24-64](../source/ui/track_detail.py#L24-L64) | Entry with placeholder, 150ms debounce, scrollable results with a column header; rows hover-highlight. |
| **Toast notification** | [app.py:137](../source/app.py#L137) `_show_toast` | Transient top-bar message, colour-coded by outcome, auto-dismiss (default 4000ms), optional inline action button. |
| **Settings dialog** | `source/ui/sync_panel.py` `SettingsDialog` | Modal `CTkToplevel`, title `Settings — Sidecar v{version}`, **640x580 default, 540x420 minimum, resizable**. Heading "Music sources" (15 bold) + one grey subline. Body is a `CTkScrollableFrame` of **one card per provider** in registry order (rekordbox, Serato DJ): an on/off `CTkSwitch`, the name (13 bold; dimmed grey when off), a right-aligned status chip (`Updates automatically · N tracks · M playlists` / `Last updated …`, or `Synced … · …`, `Not synced yet`, `Syncing…`, `Off. Saved library kept.`), then rows generated from the provider's `SettingSpec`s: label + entry + `Browse` for files and folders, `On`/`Off` tiles for a two-choice setting, a grey hint line, and the issue line **under its field** (12 pt, bold red for errors, amber for prompts). A switched-off card collapses to its header plus one grey line. Footer pinned below the scroll area: a status line, an "Unsaved changes" tag, and **Close/Cancel · Save · Sync enabled sources**. Edits are **staged**: Save applies them in one write and reloads from stored snapshots without scanning; Cancel, Esc and the window close drop them with no prompt; Sync saves, then scans every enabled source without an error (others are skipped, named in an amber footer line). Disabled primary buttons use low-chroma fills. The dialog never branches on provider id; per-provider text comes from the provider. The pattern for any settings/secondary window. |
| **Self-confirming action button** | `source/ui/copy_button.py` `CopyButton` | Icon-only `CTkButton`, 36 x 28, corner radius 6, glyph 14 pt, in the **leftmost suggestion-grid column under the header `Copy`** (`suggestion_panel.py`, `"copy": 36`). It confirms its own result in place, with a glyph per state so meaning never rests on colour alone. **Ready** `❐` (U+2750), secondary-grey glyph on the card fill `#2a2a2a`; hover is accent blue `#1f6aa5` with a white glyph. **Copied** `✓` (bold, white) on Success. **Failed** `✕` (bold, white) on Error. **Disabled** `—` (`#555555`) when there is nothing to copy. Copied and failed keep their own fill on hover, so a resting pointer never repaints them blue. **Timing:** reverts to ready after 1.5 s; every click restarts the timer and is never ignored; only one button in the app flashes at a time (a new click resets the previous one); no timer outlives the button when the grid re-renders. **Tooltip follows the state** (ready, copied, failed, disabled wording in §8), is hidden on click and restored when the timer ends. Uses `command=` only, never a `<Button-1>` binding, so a click cannot select the row or stop the preview. **Glyph fallback, if `❐` ever fails to render on a machine:** `⧉` (U+29C9), then `□`, then a 56 px text label `Copy`. There is no Now Playing copy control. Reuse this pattern for any future one-click action whose result the DJ should see without moving their eyes. |
| **Resizable split** | [app.py:88](../source/app.py#L88) `tk.PanedWindow` | Horizontal, flat sash, 50/50 initial. |
| **Hover tooltip** | `source/ui/tooltip.py` | Reusable hover tooltip. |
| **Text truncation** | [utils.py:1](../source/ui/utils.py#L1) `truncate` | Ellipsis at max length — the canonical way to fit text in fixed columns. |
| **Filter pill** | [filter_bar.py](../source/ui/filter_bar.py) `FilterDropdown` | Rounded pill button (corner_radius=16, height=32). Grey background = no filter active; accent blue (`#1f6aa5`) = filter is narrowing results. Label shows compact state ("Playlists", "Playlists: 3/9", "Playlists: Peak", "Playlists: none"; "Crates" when only Serato is on — see the noun rule in §8). The overlay offers **"Select all"** and **"Clear"** side by side. (Reverses the earlier Finding 2 "no Deselect All" decision: Clear is now supported, paired with an intentional empty-state message in the suggestion panel — *"No playlists selected — pick at least one playlist to see suggestions."* — so a fully-cleared filter reads as deliberate, not a bug.) |
| **Grouped, searchable checklist** | [filter_bar.py](../source/ui/filter_bar.py) `FilterDropdown(searchable=True, overlay_size=(300, 320))` | The crate/playlist filter only. With crates from **two or more** providers, a non-clickable header row precedes each group (provider display name in uppercase, `REKORDBOX` / `SERATO DJ`, 10 bold, secondary `#999999`), in registry order; with one provider the list is flat. A provider with no crates gets no header. Inside a group, items sort case-insensitively by folder path. Long labels are truncated **from the start** at a ` / ` or ` - ` separator (`utils.truncate_start`), with the full path in a tooltip. A search box (`Find a playlist`, 150 ms debounce) filters rows; headers hide when their group has no visible rows; while searching, the buttons read **"Select shown" / "Clear shown"** and act on visible rows only. The search clears when the overlay closes. Selections hold crate **ids**, so they survive a live refresh (`preserve_selection`). |
| **Floating overlay panel** | [filter_bar.py](../source/ui/filter_bar.py) `FloatingOverlay` | A `CTkFrame` shown via `place()` + `lift()` over a host widget, positioned below the triggering pill. Closes on outside click or Escape. Only one overlay open at a time (class-level `_open` registry). Not a `CTkToplevel` — no separate window lifecycle. |
| **Inline stepper** | [filter_bar.py](../source/ui/filter_bar.py) `KeyOffsetControl` | Three-part pill: `[◀  label  ▶]`. `CTkButton` arrows (transparent, width=24) flanking a `CTkLabel`. Used for bounded integer controls (like key offset). Buttons disable at range limits. |
| **Preset tile row** | [filter_bar.py](../source/ui/filter_bar.py) `DateRangeControl` | Horizontal row of `CTkButton` tiles representing mutually exclusive preset options. Active tile: accent blue. Default tile: grey. Selecting a tile fires change and closes the overlay. |

## 6. UI states

Every panel and feature must define all four. Current handling:

- **Loading** — sync runs on a daemon thread; the settings cards show `Syncing…` (cyan) only
  for syncs the DJ asked for. There is no global loading indicator elsewhere. Before the
  automatic first rekordbox import of a fresh install, the dashboard reads *"Reading your library…"*.
- **Empty** — dashboard shows the placeholder *"Search for a track to begin"* and badges
  show `—`; the suggestion panel is cleared when no track is selected. With an empty
  library the placeholder says what to do: *"Turn on a music source in Settings (⚙) to begin"*
  or *"Sync your library in Settings (⚙) to begin"* (`library_copy.empty_library_state`).
- **Error** — a red toast for a manual sync that failed for every source (with an `Open settings`
  button); amber for a partial failure (*"Synced rekordbox. Serato DJ sync failed: …"*) and for a
  background auto-update failure (*"rekordbox auto-update failed: …"*, once per distinct error).
  The card shows the error plus *"Using your library from {date}."* — the last good library
  stays loaded.
- **Success** — green toast with a count (*"Synced N tracks from M playlists"*, or naming the sources
  when there are two). **Live refresh is quiet:** no toast, no focus steal, audio and filters
  untouched, and the suggestion list defers its re-render while the pointer is over it or a
  preview plays. The one exception is *"Imported N tracks from rekordbox"* when a quiet refresh
  fills an empty library.
- **Local-plus-toast success** — for a one-click action on a row (copy search text), success shows
  twice: in place on the control that was clicked (the button turns green `✓` for 1.5 s), and in
  the top-bar toast (green `Copied "…"`), which keeps the exact text visible after the button has
  reverted. Failure does the same in red (`✕` plus `Couldn't copy to the clipboard. Try again.`).
  The toast replaces any toast already showing, including a red one with an `Open settings` button:
  the DJ asked for the copy, so theirs wins. Loading and empty need no handling (the action is
  instant; with nothing to copy the button is the disabled `—`).

## 7. Known design debt

Don't re-flag these in audits unless asked to triage them.

1. **No central colour-token module.** Colours are string literals in 3+ files. A
   `COLORS` dict in `config.py` would give panels one shared vocabulary.
2. **Domain colour has no non-colour fallback.** Energy and Camelot value badges lean
   hard on hue — a colour-blind DJ has only the text to fall back on.
3. **Typography is slightly ad hoc** — 24 vs 26 for adjacent large text; no named scale.
4. **Spacing has no rhythm** — `padx`/`pady` of 2/5/8/12/15 all appear with no system.
5. **Dead theme tuples** — `("light","dark")` colour tuples persist though there is no
   light theme; the first value never shows.
6. **No keyboard-navigation story** — the core track-picking loop is mouse-only.

## 8. Microcopy conventions

- **Sentence case** for body text and messages (*"Search for a track to begin"*).
  UPPERCASE only for tiny badge labels (*"KEY"*, *"BPM"*, *"ENERGY"*, *"GENRE"*).
- **Toasts state the outcome plainly**, with a count where it helps
  (*"Synced 412 tracks from 9 crates"*).
- **Errors name what failed and stay short** (*"Serato DJ sync failed: Crates folder not found"*).
  Provider messages have an initial capital, no trailing period, no provider name and no path;
  the UI adds the name. Toasts stay within 75 characters.
- **Placeholders tell the user what to do**, not what is missing
  (*"Search for a track to begin"*, not *"No track selected"*).
- **Product and provider names:** the app is **"Sidecar"** (window title *"Sidecar — DJ Track
  Selector"*). Providers are written as their vendors style them: **"rekordbox"** (lowercase, even at
  the start of a sentence) and **"Serato DJ"**.
- **Crates vs Playlists (noun rule):** the word follows the enabled sources' `crate_noun`
  (`library_copy.crate_noun_for`). Only Serato on (or nothing on) → "crate"/"Crates"; any
  rekordbox → "playlist"/"Playlists". It applies everywhere the word appears: filter pill, overlay
  empty text, search placeholder, cleared-filter message, tooltip heading, status chips and toasts.
- **All user-visible strings for sources, sync and settings live in `source/services/library_copy.py`**
  (pure, unit-tested). Don't inline new ones in widgets.
- **Thousands separators** in counts (*"1,248 tracks"*).
- **Never say "Load"** for copying search text. Sidecar copies text for the DJ to paste; it does not
  load a track into a deck. Also avoid "Sent", "Send", "Deck", "Added", "Selected" there. Say
  "Copy" / "Copied". Provider names do not appear in these strings; the wording is neutral
  (*"your DJ software's search box"*).
- **Icon-only buttons carry their meaning in two places:** a tooltip and a column header (the grid's
  `Copy` header, sentence case, 10 bold). The tooltip follows the button's state.
- **Copy strings** (`library_copy.py`): tooltip ready `Copy to the clipboard:` / `{query}` /
  `Then paste it into your DJ software's search box.`; copied `Copied:` / `{query}` /
  `Now paste it into your DJ software's search box.`; failed `Couldn't copy. Click to try again.`;
  disabled `Nothing to copy: this track has no artist or title`; success toast `Copied "{text}"`
  (text cut with `…` so the toast stays within 75 characters); failure toast
  `Couldn't copy to the clipboard. Try again.` The tooltip and toast show the same stripped query
  (featuring credits and mix suffixes removed), so what the DJ previews is what they paste.

## 9. Open questions

Decisions the user has not yet made — the `ui-designer` agent records answers here as
they land.

- Keyboard-driven track selection for the core loop?
- A colour-blind-safe mode (shapes/labels alongside hue)?
- Commit to a light theme, or delete the dead theme tuples?

Answered (copy-search-text, shipped 2026-11):
- **Icon-only button, 36 px**, glyph `❐`; header cell reads `Copy`.
- **No Now Playing copy control** in v1.
- **Confirmation lasts 1.5 s**, restarted by each click; the button shows the failed state, not only a toast.
- **Tooltip wording is neutral** ("your DJ software's search box"), not named from enabled providers.
- **The success toast stays** and replaces any other toast.
- **Keyboard shortcut for copy** is out of scope for v1 (consistent with §7.6).
