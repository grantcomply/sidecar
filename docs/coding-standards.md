# Coding Standards — Serato Sidecar

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
- **Use custom exceptions** for domain-specific error cases (future)

## Imports

- Group imports: stdlib → third-party → local
- Use absolute imports from project root (e.g., `from source.models.track import Track`)
- Avoid wildcard imports (`from module import *`)

## UI Code

- UI panels should receive callbacks, not call services directly
- Keep widget creation and event binding separate where practical
- Use `ctk.CTkFont()` for all font specifications
- Extract magic numbers (sizes, padding, colors) to named constants

## Configuration

- All tuneable values belong in `config.py`, not inline in code
- Colors, weights, thresholds, limits — all externalized
- Environment-specific values (paths) go in `.env`

## Shared Utilities

Avoid duplicating helper functions across UI panels. Common patterns to extract:

| Function | Currently duplicated in | Extract to |
|----------|----------------------|------------|
| `_truncate(text, max_len)` | `track_detail.py`, `suggestion_panel.py`, `session_panel.py`, `search_panel.py` | `ui/utils.py` |
| `CAMELOT_RE` regex | `camelot.py`, `comments_parser.py` | `services/camelot.py` (single source of truth) |

## Known Anti-Patterns to Fix

| Pattern | Location | Fix |
|---------|----------|-----|
| `os.path` usage | All files | Migrate to `pathlib.Path` |
| `print()` for diagnostics | `export_crates.py` | Use `logging` module |
| Bare `except Exception: pass` | `app.py:129,144,168` | Catch specific exceptions, log them |
| Hardcoded font `("Segoe UI", 10)` | `tooltip.py:32` | Use `ctk.CTkFont(size=10)` for cross-platform |

## Testing (to be established)

- Test files mirror source structure: `tests/services/test_camelot.py`
- Use pytest as the test runner
- Name test functions: `test_<what>_<condition>_<expected>`
- Services layer is the priority for test coverage
