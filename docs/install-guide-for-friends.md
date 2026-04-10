# Serato Sidecar — Install Guide

## What this is

Serato Sidecar reads your Serato crates and helps you pick the next track during a set. It scores tracks by harmonic key (Camelot wheel), energy level, and BPM so you can see at a glance what mixes well with what's playing now.

## Download

Go to the releases page: **https://github.com/grantcomply/sidecar/releases/latest**

In the **Assets** list:

- **Windows:** grab the `.exe` file (something like `SeratoSidecar-Setup-0.1.1.exe`)
- **Mac:** grab the `.zip` file (something like `SeratoSidecar-0.1.1-mac.zip`)

The version number in the filename will go up over time. Don't worry about picking the "right" one — just grab whichever `.exe` (Windows) or `.zip` (Mac) is in the Assets list.

## Installing on Windows

1. Run the `.exe` you just downloaded.
2. **Important:** Windows will show a blue box that says **"Windows protected your PC"**. This is expected — the app isn't signed with a paid certificate. Click **More info**, then click **Run anyway**. You only have to do this once.
3. Click through the installer. The defaults are fine.
4. Launch it from the Start Menu — look for **Serato Sidecar**.

## Installing on Mac

1. Open the `.zip` you downloaded. It'll extract to `SeratoSidecar.app`.
2. Drag the `.app` into your **Applications** folder. (Not strictly required, but keeps things tidy.)
3. **Important:** The first time you double-click it, Mac will say **"SeratoSidecar cannot be opened because Apple cannot check it for malicious software"**. This is expected — the app isn't signed with a paid Apple Developer account. **Right-click** (or Ctrl-click) the app icon, choose **Open**, then click **Open** again in the dialog that pops up. You only have to do this once.

## First launch — setting up

1. Click the **gear icon** (top-right area) to open Settings.
2. Point it at your Serato `_Serato_\Subcrates` folder:
   - **Windows:** usually `C:\Users\YourName\Music\_Serato_\Subcrates`
   - **Mac:** usually `~/Music/_Serato_/Subcrates`
3. Click **Sync**. It'll read your crates and build a library. First sync takes a few seconds for a small library, longer for a big one. That's normal.

## How to use it

1. Start a track in Serato as normal.
2. In Sidecar, search for that track (or pick it from a crate) to tell Sidecar what's playing now.
3. Sidecar shows suggestions ranked by how well they mix with the current track — harmonic key compatibility, energy flow, and BPM proximity.
4. Pick your next track, rinse and repeat for the whole set.

## Updates

When a new version is out, you'll see a blue notification near the top of the app within a few seconds of launching. Click **Download**. Your browser will open the new installer — run it the same way you did the first time. No need to uninstall the old version first.

Your settings and crate library are kept across updates — you won't have to set things up again.

## Something not working?

Just message Grant directly. This is a hobby project, not a commercial app — there's no support portal and no bug tracker for non-devs. If something breaks, a quick text or DM is the right move.
