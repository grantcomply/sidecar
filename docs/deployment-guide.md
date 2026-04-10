# Deployment Guide — Serato Sidecar

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

1. **`build-windows`** runs on `windows-latest`: PyInstaller produces `dist/SeratoSidecar/`, Inno Setup wraps it into `SeratoSidecar-Setup-<version>.exe`, artifact uploaded.
2. **`build-macos`** runs on `macos-latest` in parallel: PyInstaller produces `dist/SeratoSidecar.app`, `ditto -c -k --keepParent` zips it to `SeratoSidecar-<version>-mac.zip`, artifact uploaded.
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

1. Check `%APPDATA%\SeratoSidecar\settings.env` (or `~/Library/Application Support/SeratoSidecar/settings.env` on macOS) for a stray `CHECK_FOR_UPDATES=false` left over from debugging.
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
