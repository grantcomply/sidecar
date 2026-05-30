# UI Design Guide — Serato Sidecar

> **Status:** Starter draft — seeded from the current codebase, maintained by the `ui-designer` agent
> **Last updated:** 2026-05-30
> **Authoritative for:** visual tokens, component patterns, window layout, microcopy, and UI state conventions

This is the design counterpart to `docs/architecture-overview.md`. The architect owns
*structure*; this document owns how the app *looks, reads, and feels*. When the two
conflict, raise it — don't silently diverge.

---

## 1. Design context

Serato Sidecar is a **desktop tool used live, mid-set, in a dark DJ booth**. That single
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

### Status colours (toasts, [app.py:137](../source/app.py#L137))
| Token | Hex | Meaning |
|-------|-----|---------|
| Success | `#28a745` | Sync complete, library loaded |
| Error | `#dc3545` | Sync failed, operation failed |
| Info | `#4AB8D4` | Update available, neutral notice |

### Structural / text colours
| Token | Hex | Use |
|-------|-----|-----|
| Sash | `#333333` | PanedWindow divider |
| Card fill | `#2a2a2a` | Stat-badge background |
| Primary text | `#ffffff` | Values, titles |
| Secondary text | `#999999` | Artist line |
| Tertiary text | `#666666` | Badge labels, info line |
| Placeholder | `#555555` | Empty badge value (`—`) |

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
| **Modal dialog** | `source/ui/sync_panel.py` `SettingsDialog` | Folder picker + sync trigger + status line. The pattern for any settings/secondary window. |
| **Resizable split** | [app.py:88](../source/app.py#L88) `tk.PanedWindow` | Horizontal, flat sash, 50/50 initial. |
| **Hover tooltip** | `source/ui/tooltip.py` | Reusable hover tooltip. |
| **Text truncation** | [utils.py:1](../source/ui/utils.py#L1) `truncate` | Ellipsis at max length — the canonical way to fit text in fixed columns. |
| **Filter pill** | [filter_bar.py](../source/ui/filter_bar.py) `FilterDropdown` | Rounded pill button (corner_radius=16, height=32). Grey background = no filter active; accent blue (`#1f6aa5`) = filter is narrowing results. Label shows compact state ("Crates", "Crates: 3/9", "Crates: House"). |
| **Floating overlay panel** | [filter_bar.py](../source/ui/filter_bar.py) `FloatingOverlay` | A `CTkFrame` shown via `place()` + `lift()` over a host widget, positioned below the triggering pill. Closes on outside click or Escape. Only one overlay open at a time (class-level `_open` registry). Not a `CTkToplevel` — no separate window lifecycle. |
| **Inline stepper** | [filter_bar.py](../source/ui/filter_bar.py) `KeyOffsetControl` | Three-part pill: `[◀  label  ▶]`. `CTkButton` arrows (transparent, width=24) flanking a `CTkLabel`. Used for bounded integer controls (like key offset). Buttons disable at range limits. |
| **Preset tile row** | [filter_bar.py](../source/ui/filter_bar.py) `DateRangeControl` | Horizontal row of `CTkButton` tiles representing mutually exclusive preset options. Active tile: accent blue. Default tile: grey. Selecting a tile fires change and closes the overlay. |

## 6. UI states

Every panel and feature must define all four. Current handling:

- **Loading** — sync runs on a daemon thread; `SettingsDialog` shows a syncing state
  via `set_syncing()`. There is no global loading indicator elsewhere.
- **Empty** — dashboard shows the placeholder *"Search for a track to begin"* and badges
  show `—`; the suggestion panel is cleared when no track is selected.
- **Error** — surfaced as a red toast (*"Sync failed: …"*). Note: `crate_parser`
  swallows ID3 read errors silently — a known debt, not a pattern to copy.
- **Success** — green toast with a count (*"Synced N tracks from M crates"*).

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
- **Errors name what failed and stay short** (*"Sync failed: &lt;reason&gt;"*).
- **Placeholders tell the user what to do**, not what is missing
  (*"Search for a track to begin"*, not *"No track selected"*).

## 9. Open questions

Decisions the user has not yet made — the `ui-designer` agent records answers here as
they land.

- Keyboard-driven track selection for the core loop?
- A colour-blind-safe mode (shapes/labels alongside hue)?
- Commit to a light theme, or delete the dead theme tuples?
