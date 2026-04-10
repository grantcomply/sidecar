# Serato Sidecar — Cross-Platform Deployment & Auto-Update

## Context

Serato Sidecar currently runs only via `python main.py` in a dev environment. The goal is to ship it to friends (DJs) on **both Windows and macOS** as a downloadable installer, hosted for free, with a way to push updates so users get notified when a new version is available.

**Target environment for execution:** a new dedicated **public GitHub repo** for Serato Sidecar (to be created — split out from the current `grantcomply/secretsauce` monorepo). A public repo gives:
- Unlimited free GitHub Actions minutes including macOS (private repos cap at ~200 macOS min/month)
- Anonymous downloads of release assets (no auth tokens baked into the auto-updater)
- Clean, simple URLs

The architect agent investigated the codebase. Three real blockers must be fixed before any build will work, plus a handful of additive pieces. The codebase is closer to packageable than the stale docs suggest — `source/config.py:9` already uses `Path.home()`, `source/services/crate_parser.py:17` already detects `sys.platform`, and `main.py` no longer has a `sys.path` hack.

## The three blockers

1. **`source/services/cache.py:21`** writes `track_cache.json` to `PROJECT_ROOT`. In a PyInstaller bundle, that resolves inside a temp `_MEIxxx` extraction dir that's read-only and wiped on exit. **The packaged app will break on first run.**
2. **`source/config.py:7`** does the same for `.env` (`ENV_FILE`). User settings can't survive between runs of the packaged app.
3. **No version string anywhere.** Required for the auto-updater to know what it currently is.

Everything else is additive.

## The plan

### Phase 1 — Make the code packageable (no shipping yet)

**1.1 Move user data to a platform-appropriate dir.** Add `platformdirs` to `requirements.txt` (tiny, pure-Python, well-maintained). Create a helper in `source/config.py` (or new `source/paths.py`):

```
Windows: %APPDATA%\SeratoSidecar         (e.g. C:\Users\grant\AppData\Roaming\SeratoSidecar)
macOS:   ~/Library/Application Support/SeratoSidecar
Linux:   ~/.config/serato-sidecar         (XDG fallback)
```

- **Modify `source/services/cache.py:19-21`** — `get_cache_path()` returns `user_data_dir() / "track_cache.json"` instead of `PROJECT_ROOT / ...`.
- **Modify `source/config.py:7`** — `ENV_FILE = user_data_dir() / "settings.env"` (rename is fine; nothing else reads the old name). `_load_env` / `_save_env` don't change.
- **Migration:** on first run, if a legacy `track_cache.json` exists in `PROJECT_ROOT`, move it to the new location. ~10 lines, one-time nicety.
- Create the dir with `mkdir(parents=True, exist_ok=True)` on first access.

**1.2 Add a single source of truth for the version.**
- New file: `source/__version__.py` containing `__version__ = "0.1.0"`.
- Re-export from `source/__init__.py`.
- The GHA workflow reads this file to derive the release tag.
- Show the version somewhere small in the UI (status bar or settings dialog header).

**1.3 Fix the lingering cross-platform issue.**
- `source/ui/tooltip.py` hardcodes `"Segoe UI"` (Windows-only). Change to `("TkDefaultFont", 10)` or platform-detect.

**Verify Phase 1 in dev:** run `python main.py`, confirm `track_cache.json` now appears at `%APPDATA%\SeratoSidecar` (not project root), confirm settings persist, confirm the legacy cache migration runs once.

### Phase 2 — Local PyInstaller build on Windows

**2.1 Create `serato-sidecar.spec`** at the project root. One-folder build (not one-file), platform-detecting, with a `BUNDLE` step on macOS to produce `SeratoSidecar.app`.

Key things the spec must get right:
- `datas=[('source/ui/SeratoSidecarLogo.png', 'source/ui')]` — assets won't be bundled otherwise.
- `collect_all('customtkinter')` — known PyInstaller+CTk pitfall. CTk loads theme JSONs dynamically and PyInstaller's static analyser misses them.
- `hiddenimports=['source', 'source.app', ...]` — explicit imports for the package.
- `console=False` — no terminal window on launch.
- Icons: `icon.ico` (Windows) and `icon.icns` (macOS). Generate both from the existing `SeratoSidecarLogo.png` once.
- macOS `BUNDLE` block sets `bundle_identifier='com.grant.seratosidecar'` and `CFBundleShortVersionString` from `source.__version__`.

**Why one-folder, not one-file:** one-file extracts to temp on every launch (1–3s startup hit) and triggers Windows Defender false positives more often. One-folder is faster, less suspicious, and easier to wrap in a real installer.

**2.2 Wrap the Windows build in Inno Setup** (free, open source, runs on `windows-latest` runner without licence issues). Produces `SeratoSidecar-Setup-0.1.0.exe`. New file: `build/installer.iss`.

**2.3 macOS distribution.** Zip the `.app` bundle (`SeratoSidecar-0.1.0-mac.zip`) using `ditto -c -k --keepParent` (preserves bundle attributes; plain `zip` mangles them). A `.dmg` via `create-dmg` is nicer-looking but adds a dependency; skip until v1.0.

**Verify Phase 2:** build locally on Windows (`pyinstaller serato-sidecar.spec`), run `dist/SeratoSidecar/SeratoSidecar.exe`, confirm:
- App launches with no console window.
- Cache writes to `%APPDATA%\SeratoSidecar\track_cache.json` (NOT next to the exe).
- Settings persist between launches.
- Crate sync works against the real Serato folder.
- The CTk theme loads (most common breakage point — if it doesn't, `collect_all('customtkinter')` was missed).

### Phase 3 — GitHub Actions release workflow

**3.1 Create `.github/workflows/release.yml`** at the **repo root**.

Trigger: `on: push: tags: ['v*']` — simple tag prefix is fine in a dedicated repo.

Jobs (matrix):

- **`build-windows`** (`runs-on: windows-latest`)
  1. `actions/checkout@v4`
  2. `actions/setup-python@v5` with Python 3.11
  3. `pip install -r requirements.txt pyinstaller`
  4. `pyinstaller serato-sidecar.spec`
  5. Run Inno Setup compiler on `build/installer.iss` to produce `SeratoSidecar-Setup-${VERSION}.exe`
  6. `actions/upload-artifact@v4`

- **`build-macos`** (`runs-on: macos-latest`)
  1. Same checkout/Python/install steps
  2. `pyinstaller serato-sidecar.spec` → produces `dist/SeratoSidecar.app`
  3. `ditto -c -k --keepParent dist/SeratoSidecar.app SeratoSidecar-${VERSION}-mac.zip`
  4. Upload artifact

- **`release`** (`runs-on: ubuntu-latest`, `needs: [build-windows, build-macos]`)
  1. Download both artifacts
  2. Generate `latest.json` (see Phase 4)
  3. `gh release create v${VERSION} --title "Serato Sidecar v${VERSION}" --notes-file release-notes.md SeratoSidecar-Setup-${VERSION}.exe SeratoSidecar-${VERSION}-mac.zip latest.json`
  4. Move the floating `latest` tag to point at this commit (so the updater has a stable URL — see Phase 4)

**Public repo bonus:** unlimited free GHA minutes including macOS. No need to optimise build times or cache pip across runs (though pip caching is still a nice quality-of-life win — 2–3 min saved per build).

**Verify Phase 3:** push a tag `v0.1.0`, watch GHA, expect 2–3 typo failures on the first run. First successful Mac build is the inflection point — the app is now genuinely cross-platform.

### Phase 4 — The auto-updater

**4.1 The manifest.** A `latest.json` file generated by the release job and uploaded as a release asset. Use a **floating tag** (`latest`) that the workflow re-points on every release, so the URL stays stable across versions:

```
https://github.com/<owner>/<repo>/releases/download/latest/latest.json
```

(Replace `<owner>/<repo>` with the new public repo path once created.)

Format:
```json
{
  "version": "0.2.0",
  "released": "2026-04-15T10:00:00Z",
  "notes": "Added Camelot wheel colour legend. Fixed crate sync on macOS.",
  "assets": {
    "windows": "https://github.com/<owner>/<repo>/releases/download/v0.2.0/SeratoSidecar-Setup-0.2.0.exe",
    "macos":   "https://github.com/<owner>/<repo>/releases/download/v0.2.0/SeratoSidecar-0.2.0-mac.zip"
  }
}
```

Public-repo release assets are anonymously downloadable — no auth needed. The updater can fetch this URL with a plain `urllib` GET.

**4.2 The client.** New file: `source/services/updater.py`.

```python
# Sketch — not final code
def check_for_update(current_version: str) -> UpdateInfo | None:
    try:
        with urllib.request.urlopen(MANIFEST_URL, timeout=5) as resp:
            manifest = json.loads(resp.read())
    except Exception:
        return None  # Offline is not an error
    if Version(manifest["version"]) > Version(current_version):
        return UpdateInfo(
            version=manifest["version"],
            notes=manifest["notes"],
            url=manifest["assets"][PLATFORM_KEY],
        )
    return None
```

- Stdlib only (`urllib.request`, `json`) plus `packaging.version.Version` (add `packaging` to `requirements.txt`).
- Called from `source/app.py` after `_try_load_existing()`, in a `threading.Thread(daemon=True)` — same pattern as `services/crate_sync.py` already uses.
- Result marshalled back to UI thread via `self.after(0, ...)`.
- On update found: reuse the existing toast system (`self._show_toast`) with a clickable "Download" button that opens `webbrowser.open(update.url)` — the browser then downloads the installer, user runs it manually. **No silent auto-install.** Right UX for a hobby app shipping to friends.
- User setting to disable: `.env` key `CHECK_FOR_UPDATES=false`. Useful for offline gigs.

**Why roll-your-own and not tufup/PyUpdater:**

| | Roll-your-own | tufup | PyUpdater |
|---|---|---|---|
| Lines of code | ~80 | Framework dependency | Framework dependency |
| Maintenance status | N/A | Active | Stagnant since 2022 |
| Silent in-place updates | No (user clicks Download) | Yes (delta patches) | Yes |
| Right call for hobby project? | **Yes** | Overkill | No |

If the user base ever grows past "friends I see at parties", **tufup** is the upgrade path — actively maintained, modern TUF-based, drop-in. Don't reach for it on day one.

### Phase 5 — Polish & docs

- **`README.md`** — add a "First Run" section with the Gatekeeper / SmartScreen workarounds (see "Code signing" below).
- **`docs/cross-platform-guide.md`** — rewrite the "Packaging & Distribution (future)" section (lines 76–88) to reflect what was actually built. Update the "Current Issues (must fix)" section — `config.py` and `crate_parser.py` are resolved, only `tooltip.py` remained.
- **`docs/architecture-decisions.md`** — new ADR: "Distribution and update strategy". Captures the five decisions (GitHub Releases on dedicated public repo, PyInstaller one-folder + Inno Setup / zipped .app, roll-your-own updater with `latest.json`, unsigned binaries, platformdirs for user data).
- **`docs/architecture-overview.md`** — mark items #1 (import scheme) and #2 (hardcoded paths) as resolved. Add `services/updater.py` to the component diagram.
- **New: `docs/deployment-guide.md`** — one-page release runbook: bump `__version__.py`, commit, `git tag v0.x.0`, `git push --tags`, watch GHA, done. Include a troubleshooting section for the inevitable "PyInstaller missed a hidden import" issue.

## Code signing: don't

Apple Developer Program is **$99/year** and Windows OV/EV certs are **$200–600/year**. For a hobby app shipped to friends, that's not justifiable. Ship unsigned binaries on both platforms and document the one-time workaround:

> **macOS users:** First launch will say "SeratoSidecar cannot be opened because Apple cannot check it for malicious software." Right-click the app icon → **Open** → **Open** in the dialog. Once per install.
>
> **Windows users:** SmartScreen may show "Windows protected your PC". Click **More info** → **Run anyway**. Once per install (the warning fades as more users run it).

Don't try to obscure that the binary is unsigned — be upfront in the README. It builds trust.

## Critical files

**Modified:**
- `source/config.py` — add `user_data_dir()` helper, move `ENV_FILE` to user data dir
- `source/services/cache.py:19-21` — `get_cache_path()` uses user data dir
- `source/__init__.py` — re-export `__version__`
- `source/app.py` — version display in UI, kick off updater check on startup
- `source/ui/tooltip.py` — stop hardcoding `"Segoe UI"`
- `requirements.txt` — add `platformdirs`, `packaging`
- `README.md` — first-run instructions for Gatekeeper / SmartScreen
- `docs/cross-platform-guide.md`, `docs/architecture-overview.md` — sync stale items

**New:**
- `source/__version__.py` — single source of truth for version string
- `source/services/updater.py` — manifest fetch + version compare + UI hook
- `serato-sidecar.spec` — PyInstaller spec, platform-detecting
- `build/installer.iss` — Inno Setup script for Windows installer
- `icon.ico`, `icon.icns` — app icons (one-time generation from existing logo)
- `.github/workflows/release.yml` — at the repo root, matrix build + release
- New ADR entry in `docs/architecture-decisions.md`
- `docs/deployment-guide.md` — release runbook

## Reused existing utilities

- **`source/services/crate_sync.py`** — its background-thread + `self.after(0, ...)` pattern is exactly what the updater client should mirror. Don't invent a new threading approach.
- **`source/app.py` `_show_toast`** — reuse for the "update available" notification. Don't add a modal.
- **`source/config.py` `_load_env` / `_save_env`** — works as-is once `ENV_FILE` points at the new location. The `CHECK_FOR_UPDATES` setting plugs into the existing key/value scheme.

## Verification

### After Phase 1 (in dev)
- `python main.py` runs, no errors.
- `track_cache.json` appears at `%APPDATA%\SeratoSidecar\track_cache.json`, NOT in the project root.
- Settings (Serato folder path) persist between launches, stored in `%APPDATA%\SeratoSidecar\settings.env`.
- If a legacy `track_cache.json` existed in project root, it migrates once and the original is removed.
- Version string visible somewhere in the UI.

### After Phase 2 (local Windows build)
- `pyinstaller serato-sidecar.spec` succeeds.
- `dist/SeratoSidecar/SeratoSidecar.exe` launches with no console window.
- The CTk theme loads correctly (most common breakage point).
- Cache + settings still go to `%APPDATA%`, not next to the exe.
- Crate sync works against the real Serato folder.
- Inno Setup produces `SeratoSidecar-Setup-0.1.0.exe`; running it installs to Program Files; the installed shortcut launches the app.

### After Phase 3 (CI)
- Tag push `git tag v0.1.0 && git push --tags` triggers the workflow.
- Both `build-windows` and `build-macos` jobs succeed (budget 2–3 first-time failures).
- Release appears at `https://github.com/<owner>/<repo>/releases/tag/v0.1.0` with both installers attached.
- Download the Mac `.zip` on a real Mac, extract, right-click→Open the `.app`, confirm it launches. **First time the app is genuinely cross-platform.**

### After Phase 4 (auto-updater)
- Ship `0.1.0` as the baseline.
- Bump `source/__version__.py` to `0.1.1`, push tag `v0.1.1`, wait for the workflow.
- Re-launch the installed `0.1.0` build on Windows; within ~5s of startup, expect a toast: "Version 0.1.1 is available. [Download]".
- Click Download → browser opens to the new release page → user downloads + installs → restarts → no toast.
- Disable check via `CHECK_FOR_UPDATES=false` in `settings.env` → no toast on next launch.
- Test offline: airplane mode → app launches normally, no errors, no toast (silent failure is correct).

### After Phase 5
- README first-run section is clear enough that a non-technical friend can follow it without you on the phone.
- `docs/architecture-decisions.md` has a new ADR entry.
- `docs/deployment-guide.md` exists and tells you exactly how to ship a new version in <5 commands.

## Sequencing

Tackle in order — each phase produces a verifiable milestone:

1. **Phase 1** (paths + version) — entirely in dev, no shipping. Foundation.
2. **Phase 2** (local PyInstaller on Windows) — proves the packaging story without involving CI.
3. **Phase 3** (GHA matrix) — Windows job first (debug against your local build), then add the macOS entry.
4. **Phase 4** (auto-updater) — ship 0.1.0, then ship 0.1.1 with a trivial change to verify the update notification fires end-to-end.
5. **Phase 5** (polish + docs) — last, before announcing to friends.

## One-time prerequisites (before Phase 3)

- Create the new public GitHub repo (e.g. `grantcomply/serato-sidecar`).
- Move/copy the project files into it (excluding monorepo-specific paths).
- Push to the new repo as the new origin.
- Phases 1 and 2 can be completed in either repo location — the file changes are identical. Phase 3+ assumes the new repo is the working location.
