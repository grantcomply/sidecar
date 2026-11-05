# Deployment Guide — Sidecar

> One-page release runbook. For the architectural *why* behind the pipeline, see ADR-008 in `architecture-decisions.md` and the "Packaging & Distribution" section of `cross-platform-guide.md`.

## Prerequisites

None at runtime. Just a working clone of `grantcomply/sidecar` with push access to `main` and permission to create tags. The GitHub Actions workflow does all the building — you don't need PyInstaller, Inno Setup, or a Mac locally.

## Steps to ship a new version

```bash
# 1. Bump version
# Edit source/__version__.py, change "0.1.1" to "0.1.2"

# 2. Commit
git add source/__version__.py
git commit -m "Bump version to 0.1.2"

# 3. Tag and push
git tag v0.1.2
git push origin main v0.1.2

# 4. Watch the workflow
# https://github.com/grantcomply/sidecar/actions
```

**Important:** the tag version must match `source/__version__.py` exactly. The `v` prefix on the tag is stripped before comparison, so `v0.1.2` matches `__version__ = "0.1.2"`. The release workflow has a sanity check that fails loudly on any mismatch (including subtle typos) — this is intentional, because a mismatched version breaks the auto-updater silently.

## What happens after the tag push

1. **`build-windows`** runs on `windows-latest`: dependencies install wheel-only for the native packages (`--only-binary=sqlcipher3-wheels,psutil`), PyInstaller produces `dist/DJSidecar/DJSidecar.exe`, the frozen exe runs `--self-check-rekordbox` (the build fails if pyrekordbox or SQLCipher can't load), Inno Setup wraps it into `DJSidecar-Setup-<version>.exe`, and the artifact is uploaded.
2. **`build-macos`** runs on `macos-latest` in parallel: the same wheel-only install, PyInstaller produces `dist/DJSidecar.app`, the frozen self-check runs, `ditto -c -k --keepParent` zips it to `DJSidecar-<version>-mac.zip`, and the artifact is uploaded.
3. **`release`** runs on `ubuntu-latest` once both builds succeed: downloads both artifacts, generates `latest.json`, creates the GitHub release with three assets attached, and re-points the floating `latest` tag at this commit so the manifest URL stays stable.

Installed clients see the new toast within ~5 seconds of their next launch (the updater check runs on a background daemon thread after startup).

## Verifying the release

Once the workflow reports green:

1. Browse to `https://github.com/grantcomply/sidecar/releases/tag/v0.1.2` and confirm three assets are attached: the `.exe`, the `.zip`, and `latest.json`.
2. Fetch the manifest and confirm it reports the new version:
   ```bash
   curl -sL https://github.com/grantcomply/sidecar/releases/download/latest/latest.json
   ```
3. Re-launch an older installed version (e.g. `0.1.1`) and confirm the update toast appears within a few seconds. Click Download and confirm it opens the new installer in your browser.
4. **First release after the rename to Sidecar** (and whenever the installer changes): install over an existing `0.1.6` install. Check that it upgrades in place (same Inno `AppId`), there are no duplicate Start-menu or desktop shortcuts, `SeratoSidecar.exe` is gone, settings and the library are preserved (copied from `%APPDATA%\SeratoSidecar\` to `%APPDATA%\DJSidecar\`, also when the old folder holds only `track_cache.json`; the old folder is left as is, and no `.copy-forward-pending` marker remains in the new one), the library loads without a re-sync, and the updater still finds the next version.
5. If rekordbox support changed: run the installed `DJSidecar.exe --check-rekordbox-library` on a machine with rekordbox (see the runbook below).

**Identities that must never change in a release:** the Inno `AppId` (`build/installer.iss`), the manifest URL `…/releases/download/latest/latest.json` (`source/services/updater.py`), the macOS `bundle_identifier`, and the provider ids `serato` / `rekordbox` (persisted in user settings).

## rekordbox upgrade runbook

Sidecar reads rekordbox's encrypted `master.db` through `pyrekordbox`, which ships the decryption key. A rekordbox update that changes the encryption or the schema can break reading until pyrekordbox releases a fix. Users keep their **last good snapshot** in the meantime: the rekordbox card shows the error plus "Using your library from {date}."

**After every rekordbox upgrade on the dev machine** (and whenever a user reports "Couldn't read the database"):

1. **Check.** Run the library diagnostic, from source or with the installed exe:
   ```bash
   python main.py --check-rekordbox-library
   # or, installed: "<install dir>\DJSidecar.exe" --check-rekordbox-library
   # (an install upgraded from 0.1.x keeps its old folder, e.g. "C:\Program Files\SeratoSidecar")
   ```
   It reads a private copy of the database (nothing is saved) and writes a **counts-only** report to `<user data dir>/diagnostics/rekordbox-check-<timestamp>.txt`. The report has package versions, the DB location (home shown as `~`), file sizes and times, track/playlist counts, key and energy coverage, warnings and `RESULT: OK|FAILED`. It contains no titles, artists, track paths or key. The frozen exe is windowed, so read the report file. Exit code 0 = OK.
2. **Compare** with the previous report. `RESULT: OK` and similar counts → nothing to do.
3. **If it fails** (`Couldn't read the database`, `Not available in this build`, or counts collapse to 0):
   1. Check pyrekordbox's releases for support for the new rekordbox version.
   2. Bump and re-pin in `requirements.txt`: `pyrekordbox`, and if needed `sqlcipher3-wheels` / `SQLAlchemy` (exact `==` pins). Install with `pip install --only-binary=sqlcipher3-wheels,psutil -r requirements.txt` to make sure wheels exist for Python 3.11.
   3. If pyrekordbox renamed or moved anything, the only module to change is `source/providers/rekordbox/db_reader.py`. Run `python -m pytest`.
   4. **Re-check the logger guard.** Confirm the new pyrekordbox still logs only through the `pyrekordbox` logger tree, and that `tests/services/test_log_safety.py` (including the real-pyrekordbox test) passes. **Never lower the logger levels to debug a failure.** Debug with type names and the counts report.
   5. Re-run `--check-rekordbox-library` and confirm `RESULT: OK`.
   6. Run `python main.py --self-check-rekordbox` locally, then release as usual. CI runs the same self-check on the frozen builds.
4. **Never** paste a report that contains anything other than counts, or anything resembling a key, into an issue, a commit, a plan or a doc.

If pyrekordbox can't read the new rekordbox at all, Sidecar keeps working with the last good snapshot and with Serato. The fallback design (an XML-export source mode inside `source/providers/rekordbox/`) is noted in ADR-015.

## Troubleshooting

Ordered by real-world frequency. For any of these, see the "Retry procedure" at the end.

### 1. Version mismatch (tag version doesn't match `__version__.py`)

**Symptom:** the release workflow's version-check step fails immediately.

**Fix:** correct `source/__version__.py`, delete the bad tag locally and remotely, re-commit, re-tag, re-push:

```bash
git tag -d v0.1.2
git push origin :refs/tags/v0.1.2
# edit source/__version__.py, commit
git tag v0.1.2
git push origin main v0.1.2
```

This actually hit the real v0.1.1 release — it's the most common trip-up. Budget for it.

### 2. PyInstaller missed a hidden import

**Symptom:** the build job succeeds but the packaged `.exe` crashes on launch (or silently fails to open a window). Common offenders are packages that use dynamic imports (`customtkinter` themes, `PIL.ImageTk`, anything loaded via `importlib`).

**Fix:** add the missing module to `hiddenimports` in `serato-sidecar.spec`. For a whole package with dynamic loading, use `collect_all('<package>')` instead. Re-run the retry procedure.

**rekordbox variant:** the "Frozen rekordbox self-check" step fails (`rekordbox self-check FAILED: <ErrorType> (importing …)`). The spec isn't collecting `pyrekordbox`, `sqlcipher3` (native) or `sqlalchemy.dialects.sqlite`. The output names the failing step and an exception type, never a message. If `pip install` itself fails on `--only-binary`, a pinned native package has no wheel for that runner's Python 3.11: pick a pin that has one (see the matrix in `cross-platform-guide.md`).

### 3. Inno Setup step fails

**Symptom:** Windows build job fails inside the Inno Setup action.

**Fix:** check that `MyAppVersion` is being injected correctly via the action's `options:` field in `.github/workflows/release.yml`. Usually a typo in the version-derivation step or a missing quote around a path with spaces.

### 4. `release` job fails on artifact flatten

**Symptom:** the `release` job can't find files where it expects them after `download-artifact@v4`.

**Fix:** confirm the subdirectories match the workflow's expectations — `./artifacts/windows-installer/` and `./artifacts/macos-app/`. If unclear, add a debug step:

```yaml
- name: Debug artifact layout
  run: ls -R ./artifacts/
```

### 5. Updater toast doesn't appear on an installed client

**Symptom:** workflow succeeded, assets are present, but re-launching an older client shows no update toast.

**Fix, in order of likelihood:**

1. Check `%APPDATA%\DJSidecar\settings.env` (or `~/Library/Application Support/DJSidecar/settings.env` on macOS; `SeratoSidecar` for versions up to 0.1.6) for a stray `CHECK_FOR_UPDATES=false` left over from debugging.
2. Check the app logs for `source.services.updater` messages — network errors, JSON parse errors, etc.
3. Verify the floating `latest` tag was re-pointed correctly: browse `https://github.com/grantcomply/sidecar/releases/tag/latest` and inspect the attached `latest.json`. If it still shows the old version, the re-point step failed and needs to be re-run.

## Retry procedure

If anything above requires a re-release with the same version number:

```bash
git tag -d v0.1.2
git push origin :refs/tags/v0.1.2
# fix the issue, commit to main
git tag v0.1.2
git push origin main v0.1.2
```

**Important:** if the `release` job ran far enough to create a partial GitHub release (even with missing assets), you'll need to delete that release manually in the GitHub UI before re-pushing the tag. Otherwise `gh release create` will fail with a "release already exists" error.
