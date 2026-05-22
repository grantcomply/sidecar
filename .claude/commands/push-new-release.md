---
description: Bump the version, push the release tag, and watch the GitHub release build to completion
argument-hint: [version, e.g. 0.2.0 — optional]
allowed-tools: AskUserQuestion, Read, Edit, Write, Bash
---

# Push a new release

Cut a new Serato Sidecar release: confirm the version number, bump it, commit, tag,
push, then watch the GitHub Actions release workflow build the installers and publish
the release.

The canonical runbook this automates is `docs/deployment-guide.md` — read it if any
step is unclear. The release is **tag-driven**: pushing a `vX.Y.Z` tag triggers
`.github/workflows/release.yml`, which builds the Windows + macOS installers and
publishes the GitHub Release.

## Requested version

$ARGUMENTS

## How to run this

### Step 0 — pre-flight checks

Run these before touching anything. Stop and tell the user if any fail:

- `gh auth status` — must be authenticated, or the watch/verify steps can't run.
- `git rev-parse --abbrev-ref HEAD` — must be on `main`. Releases are cut from `main`.
- `git status --porcelain` — the working tree must be **clean**. Uncommitted changes
  either should or shouldn't be in the release, and this skill must not guess. If the
  tree is dirty, stop and ask the user to commit or stash first.
- Read the current version from `source/__version__.py` (`__version__ = "X.Y.Z"`).

### Step 1 — confirm the new version number

Compute the three candidates from the current version `X.Y.Z`:

- **patch** → `X.Y.(Z+1)` — bug fixes, small changes (the usual choice for this project)
- **minor** → `X.(Y+1).0` — notable new features
- **major** → `(X+1).0.0` — breaking changes

If `$ARGUMENTS` contains an explicit version, treat that as the proposed value.

**Use `AskUserQuestion` to confirm** — this is the confirmation gate the skill exists
for. Offer the patch bump first, labelled "(Recommended)", then minor, then major; each
option's label should show the actual resulting number (e.g. "0.1.5"). The user can
pick "Other" to type a custom version.

Validate the chosen version:

- Must be `X.Y.Z` — three dot-separated integers.
- Must be greater than the current version.
- The tag `vX.Y.Z` must not already exist — check `git tag --list "vX.Y.Z"` and
  `git ls-remote --tags origin "vX.Y.Z"`. If it exists, stop and point the user to the
  retry procedure in `docs/deployment-guide.md`.

### Step 2 — release notes

The release workflow reads `release-notes.md` from the repo root if present: its first
line becomes the auto-updater's toast summary, and the whole file becomes the GitHub
Release body. **This file persists between releases**, so it is likely stale from the
last release.

- Show the user the current first line of `release-notes.md` (if it exists).
- Offer to refresh it. If they accept, draft notes from the commits since the last
  release tag — find it with `git describe --tags --abbrev=0 --match "v*"`, then
  `git log <previous-tag>..HEAD --oneline`. Keep the **first line a single user-facing
  sentence** (it goes in the update toast); put details below it. Confirm the draft
  with the user before writing the file.
- If `release-notes.md` does not exist, the workflow falls back to a plain
  "Release vX.Y.Z" body — offer to write one rather than shipping that.

### Step 3 — bump, commit, tag

- Edit `source/__version__.py` to the new version.
- Stage `source/__version__.py` (and `release-notes.md` if changed) and commit:
  `Bump version to X.Y.Z — <short summary>`. End the commit message with the
  `Co-Authored-By` trailer per the repo's commit convention.
- Create the tag: `git tag vX.Y.Z`. The tag **must** match `__version__.py` exactly —
  the workflow has a hard check that fails the build on any mismatch.

### Step 4 — push

`git push origin main vX.Y.Z` — pushes the version-bump commit and the tag together.
The tag push triggers the release workflow. Do not ask for a second confirmation here;
the version confirmation in Step 1 was the gate.

### Step 5 — watch the build

- Give the workflow a few seconds to register, then find the run:
  `gh run list --workflow=release.yml --limit 5 --json databaseId,headBranch,status`
  and pick the run whose `headBranch` is `vX.Y.Z`.
- Watch it to completion: `gh run watch <run-id> --exit-status --interval 20`. This may
  take several minutes — keep watching; the skill is not done until the run finishes.
- The workflow runs three jobs: `build-windows`, `build-macos`, then `release`.
- **If it fails:** report which job and step failed. Do **not** auto-retry — point the
  user to the Troubleshooting and Retry sections of `docs/deployment-guide.md` (the
  most common failure is a PyInstaller hidden-import miss). A failed release that got
  far enough to create a partial GitHub Release must have that release deleted before
  the tag can be re-pushed.

### Step 6 — verify and confirm

- `gh release view vX.Y.Z --json name,tagName,url,assets` — confirm three assets are
  attached: `SeratoSidecar-Setup-X.Y.Z.exe`, `SeratoSidecar-X.Y.Z-mac.zip`, and
  `latest.json`.
- Report to the user: the release URL, the three assets, and that installed clients on
  the previous version will see the update toast on their next launch.

## Guardrails

- **The tag version must equal `source/__version__.py` exactly** — `v` prefix on the
  tag, no prefix in the file. A mismatch fails the workflow's version-check step.
- **Only push after the user has confirmed the version** in Step 1.
- **Never auto-retry a failed release.** Surface the failure and defer to the retry
  procedure in `docs/deployment-guide.md` — re-releasing the same version requires
  deleting the old tag (local + remote) and any partial GitHub Release first.
- This skill **does** commit, tag, and push — that is its purpose, and it is the one
  project command allowed to.
