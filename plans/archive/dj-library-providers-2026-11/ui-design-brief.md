# UI Design Brief: DJ Library Providers (Serato + rekordbox)

> **Author:** UI designer agent. **First written:** 2026-11-05. **Revised:** 2026-11-05 for Phase 3c (after Phases 1, 2, 3a and 3b were implemented).
> **Companions:** `architect-blueprint.md` (§3 contract, §6 settings surface, §7 branding) and `implementation-plan.md` (**Phase 3c**, T3c.1 to T3c.9, is the build list; Phase 5 keeps attribution and filter work).
> **Rule of this brief:** it lays out options and a recommended default for each taste call. The user owns those calls (§8). Items marked *Default* are what the plan assumes until the user says otherwise.
> **Citation note:** `file:line` references are against the working tree after Phase 3b (uncommitted). `docs/ui-design-guide.md` is cited as "guide §n". The guide has **not** been edited (instruction for this revision); §10 lists what it needs.

---

## 0. What changed since the first brief

- rekordbox is read from its **database** (`master.db`, a private copy, via pyrekordbox). All XML content (export file, export age, "File > Export Collection", stale-export toast, source tiles) is **removed**.
- There is **no key setup**. The rekordbox card has two settings only: `Database` (auto-detected, must be the file named `master.db`) and `Update automatically` (on/off). Provider specs: `source/providers/rekordbox/provider.py:82-101`.
- Live refresh is **quiet** (Phase 3b). The settings dialog is still the Serato-only stub (`sync_panel.py:7-83`) and `app.py` still uses the `_prepare_sync` stop-gap (`app.py:480-499`). **Phase 3c is a release gate** (plan, Phase 3a review).
- App name **Sidecar** is confirmed (O1 closed). The logo is untouched (T5.10 deferred).
- Load to deck is in the provider interface but no provider supports it, so **no UI exists or is added**.
- The user's earlier open questions (O2 to O10) were not answered. This brief applies the recommended defaults and marks each one overridable (§8).
- **New finding that changes sequencing:** `library_merge.merge` currently uses **only the first snapshot** when two providers are enabled (`library_merge.py:27-35`; the full merge is Phase 4). A dialog that lets the DJ switch both sources on would silently show only rekordbox. See §5.9.

---

## 1. User goal

A DJ who plays from rekordbox (and may keep Serato) wants Sidecar to read their library with no setup, to see at a glance that it loaded and stays current, and to keep picking the next track exactly as before. The core loop (dashboard search, suggestion grid, setlist) does **not** change. New UI lives in Settings, the top-bar toasts, the empty/first-run states and the noun used for crates/playlists.

---

## 2. Panels / components affected

| Where | Component | Change | Phase |
|---|---|---|---|
| Modal dialog, opened from the gear (`app.py:117-125`) | `SettingsDialog` (`sync_panel.py:7-83`) | **Rewritten**: provider cards, scrollable body, pinned footer, resizable. | 3c |
| Row 0, top bar | Toast (`app.py:357-391`) | New copy, an amber Warning colour, first-import toast, empty-library toast with an action button. No new widget. | 3c |
| Row 1, dashboard | Placeholder (`track_detail.py:81`) | `set_empty_message()` with three variants. Info line label `Crates:` (`track_detail.py:184`) takes the noun. | 3c |
| Row 2 left pane, filter bar | Crate pill (`filter_bar.py:940`), overlay empty text, cleared-filter message (`suggestion_panel.py:64-65`), tooltip heading (`suggestion_panel.py:587`) | Noun only ("Crates" or "Playlists"). | 3c (noun), 5 (rest) |
| Row 2 left pane, filter bar | Crate overlay (`filter_bar.py` `FilterDropdown`) | Provider group headers, wider overlay, case-insensitive sort, leaf-name pill, type-to-filter. | 5 |
| Window chrome | Window title (`app.py:52`), dialog title (`sync_panel.py:12`) | "Sidecar" branding strings. | 3c |

**Not affected:** setlist panel, Now Playing badges, suggestion columns, the paned split, the filter Apply/Cancel bar (ADR-012). `Track.sources` is not shown on rows.

---

## 3. Pattern precedent

| New element | Precedent (extends, does not reinvent) |
|---|---|
| Dialog shell: modal, centred, status line, green primary button | `sync_panel.py:12-16` (title with version, `transient`, `grab_set`), `:42-48` (green `#28a745` button, 14 bold), `:51-55` (status label), `:60-64` (centre). **Extended** to resizable, scrollable, with a pinned footer. |
| Provider card | Rounded card on `#2a2a2a`, radius 10: stat badge `track_detail.py:103`. Larger, same fill and radius. |
| Provider on/off control | **No exact precedent.** Closest: `CTkCheckBox` in the filter checklist (`filter_bar.py:344-349`). `CTkSwitch` is a toolkit widget new to the app (O4). |
| Path row: label, entry, Browse | `sync_panel.py:22-39`, file dialog call `:66-69`. |
| "Update automatically" On/Off tiles | Preset tile row: `DateRangeControl` (`filter_bar.py:815-818`; active `ACCENT_BLUE` `#1f6aa5` `filter_bar.py:39`, others `NEUTRAL_PILL`). |
| "Unsaved changes" label | `STAGED_TINT` `#3a88c8` (`filter_bar.py:40`), the deferred-apply colour (ADR-012). No new token. |
| Warning-line tooltip ("+N more") | `source/ui/tooltip.py`, used in `suggestion_panel.py` row tooltips. |
| Toast with action button (empty library) | `_show_toast(... action_label, action_callback)` (`app.py:357-391`) and `_show_update_toast` (`app.py:435-443`, 15 000 ms). |
| Per-provider busy state | `set_syncing` (`sync_panel.py:75-80`), now per card plus a global busy flag. |
| Quiet refresh (Phase 3b) | `SuggestionPanel.show_suggestions_quietly` (`suggestion_panel.py:414-441`). Reviewed in §5.6. |
| Amber Warning colour | **No guide token.** See §5.7. |

---

## 4. Window and dialog structure

Modal `CTkToplevel` (keep `transient` and `grab_set`). **Default 640x580, minimum 540x420, resizable**, with the default height clamped to about 85% of the screen height. The old fixed `600x220` (`sync_panel.py:13-14`) cannot hold two cards.

```
┌ Settings — Sidecar v0.2.0 ─────────────────────────────┐
│ Music sources                                           │  13 bold
│ Turn on the DJ software you use. Sidecar reads its      │  11, secondary #999999
│ crates and playlists and never changes your libraries.  │
│ ┌ scrollable body ───────────────────────────────────┐ │
│ │ ┌ rekordbox card ────────────────────────────────┐ │ │
│ │ │ [ON]  rekordbox   Updates automatically · 1,248│ │ │
│ │ │                   tracks · 75 playlists        │ │ │
│ │ │                   Last updated 2 minutes ago   │ │ │
│ │ │ Database  [C:\Users\...\master.db ] [Browse]   │ │ │  (grey placeholder = detected)
│ │ │ Leave empty to use the database rekordbox made.│ │ │  hint, 11, #999999
│ │ │ Update automatically   [ On ][ Off ]           │ │ │
│ │ │ Checks about once a minute and updates quietly.│ │ │
│ │ │ ! 12 tracks have no file on this computer (+1) │ │ │  amber
│ │ └────────────────────────────────────────────────┘ │ │
│ │ ┌ Serato DJ card ────────────────────────────────┐ │ │
│ │ │ [OFF] Serato DJ   Off. Saved library kept.     │ │ │
│ │ └────────────────────────────────────────────────┘ │ │
│ └────────────────────────────────────────────────────┘ │
│ status line                            Unsaved changes  │
│              [Close]  [Save]  [ Sync enabled sources ]  │  pinned footer
└─────────────────────────────────────────────────────────┘
```

- **Cards in registry order** (rekordbox first). **The dialog never branches on `provider.id`.** Everything comes from `SettingSpec`, `ProviderSettingsView` and `ProviderIssue`.
- **Body** = `CTkScrollableFrame`; footer = plain frame pinned below (grid weight on the body row). At 540x420 the cards scroll and the footer never moves. Column 1 (the entry) takes the spare width, so the entry shrinks first.
- **A card that is off** collapses to its header plus one grey line. Off cards never show validation errors.
- **Hint text is 11 pt secondary `#999999`, not tertiary `#666666`** (changed from the first brief). `#666666` on the `#2a2a2a` card is about 2.4:1 and unreadable in a dim booth. Tertiary stays for badge labels only (guide §3).
- **Keyboard:** Tab order follows the visual order; **Esc closes** (same as Close/Cancel); Enter does **not** start a sync. The window's close button behaves like Cancel. No confirmation prompt when closing with unsaved edits (the "Unsaved changes" label is visible; a modal on a modal is worse).

### 4.1 Save semantics (O2, default staged)

Toggling a provider off removes its tracks from live suggestions, so edits are **staged**:

- Footer: **`Close`** while the form is unchanged (relabels to **`Cancel`** when it differs from the saved state), **`Save`** (disabled while unchanged), and the green primary **`Sync enabled sources`**.
- "Unsaved changes" in `STAGED_TINT` while the form differs.
- `Save` applies enable/disable and path/auto-update values, then reloads from stored snapshots with no scan (instant). `Sync enabled sources` saves, then scans.
- *Alternative (O2b):* live apply with only `Close` and `Sync`. Fewer buttons, but a stray toggle changes the live library.
- *Auto-refresh interplay:* after `Save` enables rekordbox with no snapshot, the watcher imports it by itself within about 5 to 15 s (Phase 3b). The card then updates by itself (§5.3).

### 4.2 Sync button rules (corrects the first plan)

`Sync enabled sources` is **disabled only when no enabled provider can sync**. A provider with an error issue is **skipped, not a blocker for the others** (blueprint §6 rule 2: "errors block sync for that provider"; the earlier T5.1 text said any error disables the button, which contradicts it). When providers are skipped, the footer line is amber: `Skipped rekordbox: Database not found` (name and message of the first skipped provider, `(+N more)` if several). Zero enabled: the button is disabled and the footer line (amber) reads `Turn on at least one source to load tracks.`; `Save` stays enabled (zero providers is a valid saved state).

---

## 5. Design

### 5.1 Card anatomy (generic) and the four states

Header row: on/off control, provider `display_name` (13 bold, primary), right-aligned **status chip** (11, secondary `#999999`, may wrap to a second or third line). Below: one row per visible `SettingSpec`, `spec.hint`, then issue lines.

| State | What the card shows | Convention (guide §6) |
|---|---|---|
| **Loading** | Dialog-level busy: every control disabled, footer button `Syncing…`, each **enabled** card's chip reads `Syncing…` in Info cyan `#4AB8D4`. The coordinator does not report which provider is running (`library_sync.py:123-235`), so there is **no per-provider "Waiting…"** and no "12 of 75" progress in v1 (drops the first brief's optional item). `Close` stays enabled and closing does not cancel the sync. | `set_syncing` precedent (`sync_panel.py:75-80`); orange text replaced by Info colour (§5.7). |
| **Empty** | Enabled, never synced: chip `Not synced yet`. A provider that updates automatically and has no snapshot imports itself within seconds, and the chip then changes by itself. An empty field with an error shows as an **amber prompt**, never red (rule in §5.2). | Placeholders tell the user what to do (guide §8). |
| **Error** | Red issue line with the provider's message (no path, no provider name). If an older snapshot exists, the second grey line is `Using your library from 3 Nov, 14:20.` The card never blanks and the library never empties. | Errors name what failed and stay short (guide §8); forgiving, never blocking (guide §1). |
| **Success** | Chip as in §5.4. After a sync, the footer shows a green `Synced …` line. Snapshot warnings: one amber line plus `(+N more)` with a tooltip for the rest. Warnings never block. | Success is green and counted (guide §6). |

**Off:** header with the control off, plus one grey line: `Off. Saved library kept.` (a snapshot exists) or `Off`.

### 5.2 Issue colour rule (provider-agnostic)

For each `ProviderIssue`:
- **Warning severity** → amber.
- **Error severity whose `setting_key` field is currently empty** → amber (a prompt: the DJ has not chosen anything wrong).
- **Any other error** → red (`Choose the file named master.db` after the DJ picked a wrong file; `Support isn't available in this build`, which has no `setting_key`).

Validation runs when the dialog opens, after Browse, and on entry focus-out or Enter. **Not on every keystroke** (red would flash while typing a path). `validate()` is cheap and UI-thread safe (`provider.py:120-130`).

### 5.3 The rekordbox card (answers engineer item 4)

Shown rows, in order:

1. **Header:** switch, `rekordbox`, status chip.
2. **`Database`** entry + `Browse`. Empty means automatic. When empty and a database was found, the entry shows the **detected path as its grey placeholder** (so it reads as "found, not typed"). When nothing was found, the placeholder is `Choose the file named master.db`. Hint: `Leave empty to use the database rekordbox created. Only choose a file if you moved it.`
3. **`Update automatically`** with `On` / `Off` tiles. Hint: `Checks about once a minute and updates quietly. Your setlist and filters stay as they are.`
4. **Issue lines** (red/amber per §5.2), the "Using your library from …" fallback, then the warning line.

**Status chip (rekordbox with auto-update on, `CHANGE_DETECTION` in the view's capabilities):**
- line 1: `Updates automatically · 1,248 tracks · 75 playlists`
- line 2: `Last updated 2 minutes ago` (from the snapshot `synced_at`, which advances on every successful check, `library_store.py:180-192`)

With rekordbox closed, `Last updated 3 days ago` stays true and reads fine next to "Updates automatically". With auto-update **off**, the chip falls back to the manual form: `Synced 3 days ago · 1,248 tracks · 75 playlists`, which makes staleness visible. The card is generic: the chip form is chosen by the capability, not the provider id.

**How errors are surfaced**

| Situation | Card | Elsewhere |
|---|---|---|
| rekordbox not found (field empty, no `master.db` at the default path) | amber `Database not found`, hint stays visible | Fresh install: the provider is not auto-enabled (`detect()` is false), so nothing. If the DJ turns it on by hand: no toast until they sync; the footer says `Skipped rekordbox: Database not found`. |
| DJ chose the wrong file | red `Choose the file named master.db` | Sync skips the provider (§4.2). |
| Database later disappears, snapshot exists | red `Database not found` + `Using your library from …` | No toast: `change_token()` returns `None` so the watcher never refreshes (`provider.py:132-138`), and the library keeps working. |
| Background refresh fails | red issue line with the message + the fallback line (app keeps the last error per provider, `app.py:67,322`) | One amber toast per distinct error (§5.5). |
| pyrekordbox missing/broken in the build | red `Support isn't available in this build` | Serato keeps working. |
| Snapshot warnings | amber line, first warning plus `(+N more)` and tooltip | None. |

**Warning copy (final, already produced by the provider, `provider.py:291-302`):** `{n} tracks have no file on this computer`, `{n} tracks have no usable file path`, `{n} playlist entries point to tracks that aren't in the collection`. Warnings are not persisted in the snapshot metadata (`library_store.py:180-192`), so a card shows them **after the first sync or refresh of this session**. That is acceptable for v1 (T3c.6 stores them in memory). If the DJ wants them on a cold start, persisting them in `<pid>.meta.json` is a small `library_store` follow-up.

**Energy source** (comment energy first, then the file tag) needs **no UI**. Surfacing it would be noise on a setup card.

### 5.4 The Serato card

Header, chip, one `Crates folder` row (label, entry pre-filled with the default, `Browse`), hint `Usually Music\_Serato_\Subcrates.` (platform string from the provider), issue lines. Serato declares no `CHANGE_DETECTION`, so its chip is always the manual form: `Synced 2 hours ago · 412 tracks · 9 crates`. Per-card sync is not offered (O5, default no): a Serato scan re-reads every file's tags, and the footer button syncs everything enabled.

### 5.5 Main-window feedback (answers engineer items 1 to 3)

**Item 1: quiet refresh. Behaviour is right. No "list updated" cue (default).**
- Deferring the re-render while the pointer is over the list or a preview is active (`suggestion_panel.py:427-441`) is correct for the booth: rows moving under the cursor cause misclicks in the core loop, and a re-render stops a preview. Keep the 400 ms retry.
- A cue is not needed. Changes are rare and the DJ caused them (an edit in rekordbox). The list updates when the hand leaves it, and any explicit action (track pick, Apply, setlist change) supersedes a pending render. A cue adds one more thing to read. If the user wants one (O14), the cheapest form is a 2-second tertiary-grey `Updated` text in the suggestion panel header, never a toast.
- **One coherence risk to fix (Medium).** `refresh_track` updates the Now Playing badges at once (`app.py:249-252`), but the list stays old while the pointer rests on it. If the DJ edits the **playing** track's key or energy in rekordbox, the badges show the new value while the suggestions are still scored against the old one. Recommended: apply the badge refresh in the same moment as the deferred list render (the engineer can run it from the quiet-render completion). Edge case, not a Phase 3c blocker.

**Item 2: failure and success copy (final).**

| Situation | Colour, duration | Text |
|---|---|---|
| Manual sync OK, one source | Success, 4 s | `Synced 1,248 tracks from 75 playlists` |
| Manual sync OK, both sources | Success, 4 s | `Synced 1,300 tracks from rekordbox and Serato DJ` |
| Manual sync, partial failure | **Warning**, 8 s | `Synced rekordbox. Serato DJ sync failed: Crates folder not found` |
| Manual sync, one source failed | Error, 4 s (existing) | `rekordbox sync failed: Database not found` (replaces `sync_outcome.py:75-82` wording only by the message cleanup) |
| Manual sync, all failed (2+ sources) | Error, 8 s, action `Open settings` | `Sync failed for rekordbox and Serato DJ` |
| **Background refresh failed** (default) | **Warning**, 8 s | `rekordbox auto-update failed: Database not found` |
| Startup load | Success, 4 s | `Loaded 1,248 tracks from 75 playlists` |

Notes:
- The words "update failed" in the engineer's placeholder become **"auto-update failed"**. It tells the DJ why a message appeared when they did nothing. The library is still usable, so it is **amber, not red** (O11 default; red is the alternative). One toast per provider per distinct error (existing dedup, `sync_outcome.py:57-64`), cleared on the next success.
- A single transient failure (for example a copy that collides with a rekordbox write) would toast once and self-heal a minute later. If that proves noisy, toast only on the **second consecutive** failure (O12, off by default to keep the existing tested behaviour).
- Provider display names stay vendor-cased: `rekordbox` (lowercase even at the start) and `Serato DJ`. The first brief wrote "Serato" in toasts; the correct name is `Serato DJ` everywhere.
- The count in "Synced N tracks" is `library.count` (what the DJ sees), the number after "from" is that provider's crate/playlist count for one source. For both sources the sentence names the providers and drops the second number.
- Keep toasts under about 75 characters; never include a path. All of the above are 62 characters or fewer.
- Thousands separators on counts: yes (O10 default).

**Item 3: silent first import. Yes, show a one-time success toast.**
`Imported 1,248 tracks from rekordbox`, Success, 4 s. Rule: a **quiet** refresh that finishes while the library was **empty** and leaves it non-empty. Without it, a first-time rekordbox user stares at an empty dashboard and the list simply appears. Later quiet refreshes stay toast-free. The empty-state placeholder must also clear at that moment (§5.8).

### 5.6 Where the noun appears in Phase 3c

The noun rule (O3, default): only crate-style providers (Serato) enabled, "Crates"; any provider whose noun is "playlist", or a mix, "Playlists". Without this a rekordbox-only DJ sees "Crates" on the pill, in the toast and in the tooltip, which is wrong vocabulary. Phase 3c carries only the **noun** (pill label, overlay empty text, cleared-filter message, tooltip heading, info-line label, toasts). Group headers, width, sort and the leaf-name pill stay in Phase 5.

### 5.7 Colour tokens

- **Warning `#ffc107`: adopt (answers item 5), with one caveat.** The same hex is the "usable" bucket of the suggestion score colours (`suggestion_panel.py:43`). That is an accepted overlap: the score colour only appears as a number/bar in the grid, while Warning is only ever a sentence in the top bar or the settings dialog, and it never sits next to the grid. Any amber or orange sits inside the score ramp (`#fd7e14` is the next bucket), so a different amber would not avoid the overlap. Define `WARNING_COLOR` once next to the other status colours (T3c.4).
- **Syncing uses Info cyan `#4AB8D4`, not orange.** `sync_panel.py:78` uses the literal `orange`, which would sit next to the Warning amber and read as the same thing. Cyan is the existing neutral-notice token (guide §3). (O16.)
- Status words always carry the meaning (every red/amber/green line is a sentence), per guide §7.2.
- No provider colour anywhere (guide §1: colour is data).

### 5.8 Empty library and first run

Three placeholder variants on the dashboard (`track_detail.py:81`), chosen by a pure function and re-evaluated after every library reload and every refresh failure:

| Condition (library empty) | Dashboard text | Startup toast |
|---|---|---|
| No source turned on | `Turn on a music source in Settings (⚙) to begin` | Info, 15 s, action `Open settings`: `No music source is turned on` |
| A source is on and **will import by itself** (updates automatically, no snapshot, no error yet) | `Reading your library…` | none (the "Imported" toast follows) |
| A source is on, nothing loaded, and no automatic import coming (Serato only, auto-update off, or a refresh failed) | `Sync your library in Settings (⚙) to begin` | Info, 15 s, action `Open settings`: `Your library isn't synced yet` |
| Library not empty | `Search for a track to begin` (unchanged) | none |

Reason for the middle row: on a fresh install with rekordbox detected, the first import starts after the poll and settle time (about 5 to 15 s). Showing "Sync your library in Settings" for those seconds, then having it vanish, is misleading. No auto-opened modal (O8). The crate pill overlay when nothing is loaded reads `No {nouns} loaded. Sync a source in Settings.` and keeps Select all / Clear disabled (existing behaviour, `filter_bar.py:326-338`).

A Serato-only upgrade with the converted snapshot sees none of this and no new toast.

### 5.9 Sequencing risk: two sources enabled before the merge exists

`merge()` ignores every snapshot after the first (`library_merge.py:27-35`), and `_reload_library` passes both. If Phase 3c ships before Phase 4, a DJ who turns Serato on sees nothing change. Options (default first):
1. **Land Phase 4 `T4.1` and `T4.2` (pure merge, `Track.sources`) before releasing 3c.** They need only Phase 2 and the release is gated on 3c anyway. Then the precedence note `When a track is in both, its details come from rekordbox.` is true and appears under the section heading while both are on.
2. If 3c must ship first: show the interim amber line under the section heading while two sources are on (remove it with Phase 4): `Showing both sources together isn't available yet. Only rekordbox tracks appear.` (name of the first enabled source).

### 5.10 Phase 5 items kept from the first brief (summary)

- **Crate overlay attribution:** grouped sections with `REKORDBOX` / `SERATO DJ` header rows (9 bold, uppercase, tertiary, as `track_detail.py:110`) when two or more providers have crates; no header for one provider; no provider colour. A provider with no crates gets no header.
- **Labels:** rekordbox label = folder path joined with ` / `; Serato keeps ` - ` (separate groups). Sort inside a group by `casefold`ed path (O9). Single-selection pill shows the **leaf** name.
- **Width:** crate overlay about 300 by 280 px (today 200x200, `filter_bar.py:315`), clamped to the left pane and the window bottom, 200 px fallback at the narrowest pane, `truncate` near 38 characters plus a tooltip.
- **Scale:** the user's library is **75 playlists in 23 folders** (blueprint R11), above the roughly 40 where a flat list stops being quick. **Recommendation now: build type-to-filter (tier 2) in Phase 5**, with `Select shown` / `Clear shown` relabelling while a search is active, rather than leaving it as a follow-up. The user can override and ship the flat list first.
- **Tooltips and info line:** one provider = `{Nouns}: A, B`; both = one line per provider. Info line shows labels only, no provider tag. `Track.sources` is never displayed.
- **No top-bar sources indicator** (O7); the 32 px bar is full.

---

## 6. States to handle (summary by surface)

| Surface | Loading | Empty | Error | Success |
|---|---|---|---|---|
| Settings dialog | Busy: controls disabled, `Syncing…` chip in cyan, footer button `Syncing…` | `Not synced yet`; amber prompt for an empty field; zero sources: footer message | Red/amber issue line without path; `Using your library from …` | Chip counts; green footer line after a sync |
| Toast bar | n/a | Info toast with `Open settings` (§5.8) | Red (manual, all failed), amber (partial, background) | Green counted toast; green `Imported` toast once |
| Dashboard | `Reading your library…` while an automatic import is pending | Three placeholders (§5.8) | Falls to the `Sync your library…` text if the import failed | `Search for a track to begin` |
| Crate overlay | none needed (in-memory) | `No {nouns} loaded. Sync a source in Settings.` | none (failed provider has no group) | grouped list (Phase 5) |
| Suggestion list on live refresh | Deferred while pointer is over it or a preview plays | n/a | n/a | Re-renders when idle, scroll kept |

---

## 7. Microcopy

Sentence case everywhere; UPPERCASE only for tiny overlay group headers. `{noun}` and `{nouns}` come from §5.6. Counts use thousands separators. Provider messages (`ProviderIssue.message`, `ProviderError`): short, initial capital, **no trailing period, no provider name, no path**. Anything in this table is the final string unless noted.

### Dialog
| Element | Text |
|---|---|
| Window title | `Settings — Sidecar v{version}` |
| Heading / sub-text | `Music sources` / `Turn on the DJ software you use. Sidecar reads its crates and playlists and never changes your libraries.` |
| Precedence note (both on, after Phase 4) | `When a track is in both, its details come from rekordbox.` |
| Interim line (both on, before Phase 4) | `Showing both sources together isn't available yet. Only rekordbox tracks appear.` |
| Off lines | `Off. Saved library kept.` / `Off` |
| Chip, not synced | `Not synced yet` |
| Chip, manual | `Synced {relative} · {n} tracks · {m} {nouns}` |
| Chip, automatic | line 1 `Updates automatically · {n} tracks · {m} {nouns}`, line 2 `Last updated {relative}` |
| Chip, busy | `Syncing…` |
| Fallback line | `Using your library from 3 Nov, 14:20.` |
| Relative time | `just now` (under 45 s), `1 minute ago` / `12 minutes ago`, `2 hours ago`, `3 days ago`, then `on 3 Nov` (`on 3 Nov 2025` in another year) |
| Footer buttons | `Close` (clean) / `Cancel` (edited), `Save`, `Sync enabled sources` (busy: `Syncing…`) |
| Footer labels | `Unsaved changes`; zero sources `Turn on at least one source to load tracks.`; skipped `Skipped rekordbox: Database not found`; after Save `Settings saved`; after sync = the manual toast text |

### rekordbox card
| Element | Text |
|---|---|
| Switch label | `rekordbox` |
| Row label / placeholder (nothing found) | `Database` / `Choose the file named master.db` |
| Row hint | `Leave empty to use the database rekordbox created. Only choose a file if you moved it.` |
| Browse title / filter | `Select your rekordbox database (master.db)` / `rekordbox database` (existing, `provider.py:89-91`) |
| Auto-update label / tiles / hint | `Update automatically` / `On`, `Off` / `Checks about once a minute and updates quietly. Your setlist and filters stay as they are.` |
| Errors | `Database not found` (was `rekordbox database not found`), `Choose the file named master.db` (existing, `paths.py:18`), `Support isn't available in this build` (was `rekordbox support isn't available in this build`) |

### Serato DJ card
`Crates folder` / placeholder `Choose your Serato crates folder` / hint `Usually Music\_Serato_\Subcrates.` (macOS `Music/_Serato_/Subcrates.`) / Browse title `Select your Serato crates folder` / errors `Crates folder not found`, warning `No crates found in this folder` (all existing, `serato/provider.py:32-33,53-63`).

### Toasts
See the table in §5.5, plus: `Imported {n} tracks from {name}` (Success, 4 s, once) and the two Info toasts in §5.8.

### Panels
| Element | Text |
|---|---|
| Pill label | `Crates` / `Playlists` (+ existing compact states: `Playlists: 3/9`, `Playlists: Peak`, `Playlists: none`) |
| Overlay empty | `No {nouns} loaded. Sync a source in Settings.` |
| Cleared-filter message | `No {nouns} selected — pick at least one {noun} to see suggestions.` |
| Tooltip heading, info-line label | `{Nouns}: A, B` |
| Dashboard placeholders | see §5.8 |
| Window title | `Sidecar — DJ Track Selector` |

---

## 8. Open questions (all have a default; the user can override any)

| # | Question | Default applied | Alternative |
|---|---|---|---|
| O1 | App name | **Answered: "Sidecar".** | n/a |
| O2 | Staged or live settings | Staged: `Close/Cancel`, `Save`, `Sync enabled sources`, "Unsaved changes" | Live apply with `Close` + `Sync` |
| O3 | Word for crates | Follows providers: Serato only "Crates", any rekordbox or a mix "Playlists" | Always "Playlists" / always "Crates" |
| O4 | Provider on/off widget | `CTkSwitch` | `CTkCheckBox` (as `filter_bar.py:344`) |
| O5 | Per-card sync button | None | Small "Sync" text button per card |
| O6 | Crate filter at scale | Grouped headers; **tier 2 type-to-filter in Phase 5** because the user has 75 playlists; ` / ` and ` - ` separators kept apart | Flat list first; unify separators |
| O7 | Attention dot by the gear | None | Amber dot when a refresh failed |
| O8 | Auto-open Settings on first run | No (toast with `Open settings`) | Auto-open |
| O9 | Sort case-insensitive | Yes (Phase 5) | Keep case-sensitive |
| O10 | Thousands separators | Yes | No |
| **O11** | Colour of a background-refresh failure | Warning amber | Error red |
| **O12** | Toast on first or second consecutive refresh failure | First (existing behaviour) | Second |
| **O13** | "Update automatically" control | On/Off tiles (plan as written) | A switch, matching the provider switch |
| **O14** | "List updated" cue after a deferred render | None | Brief `Updated` text in the list header |
| **O15** | Two sources before the merge exists | Land `T4.1`/`T4.2` before releasing 3c | Ship the interim amber line |
| **O16** | In-progress colour | Info cyan `#4AB8D4` | Keep orange (conflicts with Warning amber) |

---

## 9. Risks

- **Colour-blind and colour-as-data.** Every status pairs colour with words. Provider attribution is text only. The one shared hex is Warning amber and the score yellow (§5.7).
- **Minimum window 1000x650.** The dialog is independent. 640x580 is clamped to the screen; at 540x420 the body scrolls and the footer stays. Test at 125% and 150% Windows scaling: label + entry + Browse needs about 480 px. A long detected path in the entry is clipped by the entry; the hint says what it is.
- **Toast length at 1000 px.** Toast shares the 32 px bar with the gear. All copy is under 75 characters; with the 90 px action button the longest (`Sync failed for rekordbox and Serato DJ`, 39 characters) fits easily.
- **Extreme pane widths.** Phase 3c adds only the noun, so the pill grows from `Crates` to `Playlists` (3 characters); check the pill and the single-selection label at the narrowest pane. Phase 5 adds the overlay clamp.
- **Idle-pointer deferral.** A DJ whose mouse rests on the list sees a stale list until it moves or they act. Accepted (§5.5), plus the badge/list coherence risk.
- **Staleness is invisible with auto-update off.** The manual-form chip (`Synced 3 days ago`) is the only cue. If the user gets bitten, escalate to O7.
- **Zero sources** is easy to reach (switch all off, Save). The three empty states exist so it reads as deliberate.
- **`library.count` vs per-provider counts** differ once duplicates merge (Phase 4). The "from {m}" number is per provider, the leading number is the merged total, so copy for both-on drops the second number.
- **Warnings are session-only** (§5.3).
- **Dialog refresh while the DJ is editing.** When a sync result arrives, update only the chip, issue and warning lines. Never overwrite staged values or switches.
- **macOS** unverified (R13); hints are platform strings from the provider.
- **Keyboard:** Esc/Tab only. The core loop still has no keyboard story (guide §7.6); not a regression.

---

## 10. Conflicts with `docs/ui-design-guide.md` and the architect (guide not edited)

1. **Warning token** `#ffc107` is not in guide §3 (Success, Error, Info only) and overlaps the score colour (§5.7). Needs a §3 row.
2. **Guide §6 and §8** describe one error form (`Sync failed: …`, red). New copy is per provider, adds an amber tier and the "auto-update failed" form. Both sections need the update.
3. **In-progress colour:** the code's literal `orange` (`sync_panel.py:78`) is replaced by Info cyan (§5.7). Guide §6 does not name a colour, so no conflict, but record it.
4. **Hint colour:** hints use secondary `#999999`; guide §3 lists tertiary `#666666` for "badge labels, info line". Clarify that tertiary is not for instructions.
5. **Terminology:** guide §5 (Filter pill row) hard-codes "Crates"; the noun is now provider-declared.
6. **Modal dialog row (guide §5)** describes the fixed folder-picker dialog; record the resizable, card-based variant.
7. **Product name:** guide title and §1 say "Serato Sidecar".
8. **Architect T5.1** said any error issue disables `Sync enabled sources`; changed to "skip the failing provider" to match blueprint §6 rule 2 (§4.2).
9. **Architect T5.1 "Waiting…"** needs per-provider progress the coordinator does not report; dropped.
10. **Architect placement of `library_copy.py`** (`source/ui/`): moved to `source/services/` because `services/sync_outcome.py` must use the strings and services must not import ui.
11. **Provider contract:** one small additive method, `detected_values(settings)`, so the dialog can show the auto-detected path without provider branching (blueprint §3 updated).

## 11. Design-guide updates to apply later

- §3: Warning `#ffc107`; status-colour table gains "Syncing (Info)".
- §5: Modal dialog row (resizable, scrollable, cards); new rows "Provider card", "Status chip" and "Overlay group header" (Phase 5); Filter pill row noun; toast row notes the Warning tier.
- §6: per-provider sync states; library-empty variants; quiet refresh behaviour.
- §8: provider-message convention; noun rule; `auto-update failed` form; hint colour.
- Title, §1 and header wording ("Sidecar"); bump "Last updated".
