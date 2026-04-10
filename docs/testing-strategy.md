# Testing Strategy — Serato Sidecar

> Maintained by the Architect agent. Defines what to test, how to test, and coverage goals.

## Current State

**No automated tests exist.** This document defines the testing strategy to be implemented incrementally.

## Test Framework

- **Runner:** pytest
- **Structure:** `tests/` directory mirroring `source/` structure
- **Fixtures:** pytest fixtures for common test data (sample tracks, libraries)

## Testing Pyramid

```
        ┌─────────┐
        │  E2E /  │  ← Few: full app smoke tests (future)
        │  Manual │
        ├─────────┤
        │ Integr- │  ← Some: crate export → CSV → library load
        │  ation  │
        ├─────────┤
        │  Unit   │  ← Many: services, models, parsers
        └─────────┘
```

## Priority Order (what to test first)

### Phase 1: Services (highest value, easiest to test)
These are pure functions with no UI dependency:

1. **`camelot.py`** — Harmonic compatibility logic
   - All 24 keys × compatible/incompatible combinations
   - Edge cases: wrapping (12A ↔ 1A), A/B flips
   - Score values for each compatibility type

2. **`comments_parser.py`** — Structured metadata parsing
   - Well-formed input: `"4A - 7 - Banger - Fat Bass Vocal"`
   - Missing parts: `"4A - 7"`, `"4A"`, `""`
   - Malformed energy: `"4A - high - Banger"`
   - Unknown categories, extra whitespace

3. **`suggestion_engine.py`** — Scoring algorithm
   - Score calculation for known inputs
   - Filtering: excluded paths, allowed crates, incompatible keys
   - Weight application
   - Edge cases: empty library, no compatible tracks

### Phase 2: Models
4. **`track.py`** — CSV row parsing, field extraction
   - Well-formed CSV rows
   - Missing fields, empty values
   - Camelot key extraction from comments vs CSV column

5. **`library.py`** — Search, deduplication, crate tracking
   - Search matching (case insensitive, partial match)
   - Deduplication by file path
   - Multi-crate membership

### Phase 3: Integration
6. **`export_crates.py`** — End-to-end crate parsing
   - Requires sample .crate file fixtures
   - CSV output format validation

### Phase 4: UI (future)
- Smoke tests for panel creation (widgets instantiate without error)
- Event callback wiring tests

## Test File Structure

```
tests/
├── conftest.py              # Shared fixtures
├── services/
│   ├── test_camelot.py
│   ├── test_comments_parser.py
│   └── test_suggestion_engine.py
├── models/
│   ├── test_track.py
│   └── test_library.py
└── fixtures/
    ├── sample_tracks.csv
    └── sample.crate          # (if we can include a small binary fixture)
```

## Test Naming Convention

```python
def test_<function>_<scenario>_<expected_result>():
    """Example: test_is_compatible_adjacent_key_same_letter_returns_true"""
```

## Running Tests

```bash
# All tests
python -m pytest

# Specific module
python -m pytest tests/services/test_camelot.py

# With coverage
python -m pytest --cov=source --cov-report=term-missing
```

## Coverage Goals

| Phase | Target |
|-------|--------|
| Phase 1 (Services) | 90%+ for services/ |
| Phase 2 (Models) | 80%+ for models/ |
| Phase 3+ | 70%+ overall |
