# Coding Standards — Sidecar

> Maintained by the Architect agent. All code changes should follow these standards.

## Python Version & Style

- **Target:** Python 3.10+ (use modern syntax: `match`, `X | Y` unions, `list[str]` not `List[str]`)
- **Style:** PEP 8 with the following project-specific conventions
- **Line length:** 100 characters max
- **Formatter:** Not yet enforced — to be added

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Modules | `snake_case` | `suggestion_engine.py` |
| Classes | `PascalCase` | `TrackLibrary` |
| Functions/methods | `snake_case` | `get_suggestions()` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_SUGGESTIONS` |
| Private members | `_leading_underscore` | `_current_track` |
| Type variables | `PascalCase` + `T` suffix | `TrackT` |

## Type Hints

- **Required** on all public function signatures (parameters and return type)
- **Optional** on private helper functions where types are obvious
- Use `from __future__ import annotations` for forward references
- Prefer `X | None` over `Optional[X]`

## File & Path Handling

- **Always use `pathlib.Path`** for file system operations
- **Never hardcode path separators** (`\` or `/`)
- **Always specify `encoding="utf-8"`** when opening files
- **Use `Path.home()`** instead of hardcoded home directories

## Error Handling

- **Never** use bare `except:` or `except Exception: pass`
- **Catch specific exceptions** and handle them meaningfully
- **Log errors** before re-raising or handling
- **Domain exceptions:** providers raise `ProviderError` (user-presentable text) and `DeckLoadNotSupported`. Per-track problems become snapshot warnings, not exceptions.
- **Thread and adapter boundaries** may catch `Exception` once, with a `# noqa: BLE001 - <reason>` comment, and must log it (traceback, or type name only where the key could leak). Examples: `library_sync._sync_one`, the `LibraryWatcher` tick, the `db_reader` boundary.

## Imports

- Group imports: stdlib → third-party → local
- Use absolute imports from project root (e.g., `from source.models.track import Track`)
- Avoid wildcard imports (`from module import *`)

## DJ library providers (ADR-015) — review blockers

These rules protect the provider boundary, the user's DJ-software files and the rekordbox database key. Breaking one is a **review blocker**, not a style note.

1. **DJ-software-specific code lives only in `source/providers/`.** Nothing outside `source/providers/` imports a concrete provider (`providers.serato.*`, `providers.rekordbox.*`) except `providers/registry.py`. Everyone else goes through `registry.get_provider` / `all_providers` and the `LibraryProvider` protocol. *Single accepted exception:* `services/diagnostics.py` → `providers.rekordbox.paths` (ADR-015). Don't add another without an ADR note.
2. **No provider-id branching outside providers.** UI and services never write `if provider.id == "rekordbox"`. Per-provider behaviour comes from `SettingSpec`s, `capabilities()`, `crate_noun`, `display_name` and `detected_values()`. If you need a branch, extend the contract instead.
3. **Only `providers/rekordbox/db_reader.py` imports `pyrekordbox` or SQLAlchemy**, and only lazily (inside `_ensure_pyrekordbox`). `validate()` must use `importlib.util.find_spec`, never an import.
4. **Never lower the `pyrekordbox` / `sqlalchemy` logger levels** (`services/log_safety.py` holds them at ERROR / WARNING), and never log or re-raise **exception text** from the rekordbox adapter: pyrekordbox logs the DB key at DEBUG, and SQLAlchemy/SQLCipher messages can embed it. At that boundary log `type(e).__name__` only, and raise a fixed-text `ProviderError` outside the `except` block. Never pass, store, print or commit a key, in code, tests (use `SYNTHETIC_KEY`), docs or plans.
5. **Never open files in a DJ app's folder with SQLite, and never write there.** Read a private copy (`providers/rekordbox/db_copy.private_copy`). Never copy `master.db-shm`. Never call a pyrekordbox write API (`commit`, `add`, `delete`, `flush`), even on the copy. Serato files are opened read-only.
6. **Providers are stateless.** Settings are passed into every call. Memo caches that change only speed are allowed. Providers don't use UI, `config` accessors or `library_store`.
7. **Provider ids and `env_key`s are persisted: never rename them.** `PROVIDERS_ENABLED` is written in registry order.
8. **Provider messages:** `ProviderIssue.message` / `ProviderError` text is a short phrase with an initial capital, no trailing period, no provider name and no path, and fits the 75-character partial-failure toast. User-visible strings outside providers live in `services/library_copy.py`.
9. **Threading:** `scan()` and `load_to_deck()` run off the Tk thread. `validate()`, `detected_values()` and `change_token()` are stat-only and safe anywhere. Sync and watcher callbacks reach Tk only through `after(0, ...)`.
10. **Privacy:** no real titles, artists, paths or comments from anyone's library in code, tests, fixtures, logs above DEBUG, diagnostics reports or docs. Diagnostics report counts only and show the home folder as `~`.
11. **No automating the DJ apps.** Sidecar never synthesises input events (keystrokes, mouse, drag), never focuses or automates another application, and never sends a DJ app anything (MIDI, IPC, files) to cause a deck load. Handing over a track is passive: the clipboard, and the DJ pastes (ADR-016). `DECK_LOAD` stays reserved; reopening it needs a new ADR.

## UI Code

- UI panels should receive callbacks, not call services directly
- Keep widget creation and event binding separate where practical
- Use `ctk.CTkFont()` for all font specifications
- Extract magic numbers (sizes, padding, colors) to named constants
- Clipboard writes go through `ui/clipboard.copy_to_clipboard`; never call `update()` after a clipboard write (it runs queued input events mid-handler; use `update_idletasks()` if a flush is ever needed). Never log the copied text (providers rule 10)
- A button inside a clickable row (the suggestion rows select on `<Button-1>`) uses `command=` only and never binds `<Button-1>` itself, so its click can't reach the row's handler (the play and copy buttons, ADR-016)
- Widgets that start `after` timers cancel them in `destroy()` and guard the callback with `winfo_exists()`, because a re-render destroys rows (`CopyButton`)

## Configuration

- All tuneable values belong in `config.py`, not inline in code
- Colors, weights, thresholds, limits — all externalized
- User settings (paths, provider switches) go in `settings.env` in the user data dir, keyed `<PROVIDER>_<SETTING>` for provider settings and declared by a `SettingSpec`
- DJ-software default paths belong in the provider, not in `config.py`

## Shared Utilities

Avoid duplicating helper functions across UI panels. Common patterns to extract:

| Function | Currently duplicated in | Extract to |
|----------|----------------------|------------|
| `_truncate(text, max_len)` | `track_detail.py`, `suggestion_panel.py`, `session_panel.py` | `ui/utils.py` (`truncate`, `truncate_start` exist) |
| Camelot parsing | `camelot.py` | `services/camelot.parse_camelot` (single source of truth; `comment_format.py` uses it) |
| File identity | — | `models/path_identity.path_key` only; never compare raw path strings across providers |

## Known Anti-Patterns to Fix

| Pattern | Location | Fix |
|---------|----------|-----|
| `os.path` usage | Older modules | Migrate to `pathlib.Path` in new or touched code (`path_key` and `resolve_track_path` keep `os.path` on purpose) |
| Bare `except Exception: pass` | Check `app.py` on next touch | Catch specific exceptions, log them |

## Testing

- Test files mirror source structure: `tests/services/test_camelot.py`, `tests/providers/rekordbox/test_paths.py`
- Use pytest as the test runner
- Name test functions: `test_<what>_<condition>_<expected>`
- Synthetic data only; never read real DJ-software files; never a real key. See `docs/testing-strategy.md`
