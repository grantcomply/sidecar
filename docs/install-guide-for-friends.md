# Sidecar — Install Guide

## What this is

Sidecar reads your DJ library from **rekordbox**, **Serato DJ**, or both, and helps you pick the next track during a set. It scores tracks by harmonic key (Camelot wheel), energy level and BPM, so you can see at a glance what mixes well with what's playing now. It only reads your library; it never changes anything in rekordbox or Serato.

(Sidecar used to be called "Serato Sidecar". If you have the old version installed, just install the new one over it: your settings and library come with you.)

## Download

Go to the releases page: **https://github.com/grantcomply/sidecar/releases/latest**

In the **Assets** list:

- **Windows:** grab the `.exe` file (something like `DJSidecar-Setup-<version>.exe`)
- **Mac:** grab the `.zip` file (something like `DJSidecar-<version>-mac.zip`)

The version number in the filename will go up over time. Don't worry about picking the "right" one — just grab whichever `.exe` (Windows) or `.zip` (Mac) is in the Assets list.

## Installing on Windows

1. Run the `.exe` you just downloaded.
2. **Important:** Windows will show a blue box that says **"Windows protected your PC"**. This is expected — the app isn't signed with a paid certificate. Click **More info**, then click **Run anyway**. You only have to do this once.
3. Click through the installer. The defaults are fine.
4. Launch it from the Start Menu — look for **Sidecar**.

## Installing on Mac

1. Open the `.zip` you downloaded. It'll extract to `DJSidecar.app`.
2. Drag the `.app` into your **Applications** folder. (Not strictly required, but keeps things tidy.)
3. **Important:** The first time you double-click it, Mac will say **"DJSidecar cannot be opened because Apple cannot check it for malicious software"**. This is expected — the app isn't signed with a paid Apple Developer account. **Right-click** (or Ctrl-click) the app icon, choose **Open**, then click **Open** again in the dialog that pops up. You only have to do this once.

(Mac support hasn't been tested on a real Mac yet, especially with rekordbox. If it misbehaves, tell Grant.)

## First launch — choosing your music sources

1. Click the **gear icon** (top right) to open **Settings**. You'll see one card per music source: **rekordbox** and **Serato DJ**.
2. Turn on the source(s) you use with the switch on each card. One or both is fine.
   - **rekordbox:** usually nothing to set up. Sidecar finds rekordbox's library by itself and shows where it found it. Leave **Update automatically** on.
   - **Serato DJ:** check that **Crates folder** points at your `_Serato_` `Subcrates` folder:
     - **Windows:** usually `C:\Users\YourName\Music\_Serato_\Subcrates`
     - **Mac:** usually `~/Music/_Serato_/Subcrates`
3. Click **Sync enabled sources**. Sidecar reads your library. rekordbox takes a second or so; Serato takes a few seconds for a small library, longer for a big one. That's normal.

If you use both, a track that's in both libraries shows up once, with rekordbox's details.

## Staying up to date with rekordbox

With **Update automatically** on, you don't need to sync again after changing things in rekordbox (new playlists, edited comments, and so on). Sidecar notices within about a minute, or as soon as you click back into the Sidecar window, and updates quietly. Your current track, setlist and filters stay put.

For Serato, open Settings and click **Sync enabled sources** after you've changed your crates.

## How to use it

1. Start a track in rekordbox or Serato as normal.
2. In Sidecar, search for that track to tell Sidecar what's playing now.
3. Sidecar shows suggestions ranked by how well they mix with the current track: harmonic key compatibility, energy flow and BPM proximity. Use the **Playlists** (or **Crates**) filter to narrow them down.
4. Pick your next track, rinse and repeat for the whole set.

## Updates

When a new version is out, you'll see a blue notification near the top of the app within a few seconds of launching. Click **Download**. Your browser will open the new installer — run it the same way you did the first time. No need to uninstall the old version first.

Your settings and library are kept across updates — you won't have to set things up again.

**rekordbox heads-up:** after you update **rekordbox**, Sidecar may occasionally be unable to read it until Sidecar gets an update too. If that happens, Settings shows a message on the rekordbox card, and Sidecar keeps using your library as it was before. Nothing is lost. Tell Grant, and install the next Sidecar update when it's out.

## Something not working?

Just message Grant directly. This is a hobby project, not a commercial app — there's no support portal and no bug tracker for non-devs. If something breaks, a quick text or DM is the right move.
