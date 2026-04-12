"""Audio playback controller wrapping pygame.mixer.music.

Provides play/pause/stop/seek with position tracking. Only initialises
the pygame mixer subsystem — no display window is created.  If pygame
fails to initialise (missing codec libraries, CI environment, etc.) the
player degrades gracefully: every public method becomes a safe no-op and
the ``available`` property returns False so the UI can hide play buttons.
"""

import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Lazy-import pygame so the rest of the app still loads if the package
# is missing or broken.
_pygame_mixer = None
_pygame_error: type[Exception] | None = None


def _ensure_pygame():
    """Import pygame.mixer on first use.  Returns True on success."""
    global _pygame_mixer, _pygame_error
    if _pygame_mixer is not None:
        return True
    try:
        import pygame.mixer  # noqa: WPS433 — intentional lazy import
        import pygame         # for pygame.error
        _pygame_mixer = pygame.mixer
        _pygame_error = pygame.error
        return True
    except ImportError:
        logger.warning("pygame is not installed — audio preview disabled")
        return False


class AudioPlayer:
    """Singleton-style audio playback controller.

    Create one instance in ``app.py`` and share the reference with any
    UI component that needs playback control.
    """

    def __init__(self) -> None:
        self._available = False
        self._current_file: str | None = None
        self._playing = False
        self._paused = False
        self._seek_offset: float = 0.0
        self._duration: float = 0.0
        self._on_track_end: Callable[[], None] | None = None

        if not _ensure_pygame():
            return

        try:
            assert _pygame_mixer is not None
            _pygame_mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
            self._available = True
            logger.info("pygame.mixer initialised successfully")
        except Exception as exc:
            logger.warning("pygame.mixer.init() failed — audio preview disabled: %s", exc)

    # ── Properties ──

    @property
    def available(self) -> bool:
        """True when the mixer initialised and playback is possible."""
        return self._available

    @property
    def is_playing(self) -> bool:
        """True when audio is actively playing (not paused)."""
        if not self._available:
            return False
        return self._playing and not self._paused

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def current_file(self) -> str | None:
        return self._current_file

    # ── Playback control ──

    def play(self, file_path: str) -> bool:
        """Load and play an audio file.  Stops any current playback first.

        Returns True on success, False if the file cannot be loaded.
        """
        if not self._available:
            return False

        assert _pygame_mixer is not None
        assert _pygame_error is not None

        # Stop whatever is playing now
        self.stop()

        path = Path(file_path)
        if not path.is_file():
            logger.warning("File not found: %s", file_path)
            return False

        try:
            _pygame_mixer.music.load(str(path))
            _pygame_mixer.music.play()
        except (_pygame_error, OSError) as exc:
            logger.warning("Cannot play %s: %s", path.name, exc)
            return False

        self._current_file = file_path
        self._playing = True
        self._paused = False
        self._seek_offset = 0.0
        self._duration = self._read_duration(file_path)

        return True

    def pause(self) -> None:
        """Pause current playback.  No-op if not playing."""
        if not self._available or not self._playing or self._paused:
            return
        assert _pygame_mixer is not None
        _pygame_mixer.music.pause()
        self._paused = True

    def resume(self) -> None:
        """Resume paused playback.  No-op if not paused."""
        if not self._available or not self._paused:
            return
        assert _pygame_mixer is not None
        _pygame_mixer.music.unpause()
        self._paused = False

    def stop(self) -> None:
        """Stop playback and unload the current file."""
        if not self._available:
            return
        assert _pygame_mixer is not None
        try:
            _pygame_mixer.music.stop()
            _pygame_mixer.music.unload()
        except Exception:
            pass  # already stopped / nothing loaded
        self._playing = False
        self._paused = False
        self._current_file = None
        self._seek_offset = 0.0

    def seek(self, seconds: float) -> None:
        """Jump to the given position in the current track."""
        if not self._available or not self._playing:
            return
        assert _pygame_mixer is not None
        assert _pygame_error is not None
        try:
            _pygame_mixer.music.play(start=seconds)
            if self._paused:
                _pygame_mixer.music.pause()
            self._seek_offset = seconds
        except (_pygame_error, OSError) as exc:
            logger.warning("Seek failed: %s", exc)

    def get_position(self) -> float:
        """Return current playback position in seconds.  Returns 0.0 if not playing."""
        if not self._available or not self._playing:
            return 0.0
        assert _pygame_mixer is not None
        # get_pos() returns ms since play() was called (resets on seek via play(start=))
        ms = _pygame_mixer.music.get_pos()
        if ms < 0:
            return 0.0
        return self._seek_offset + ms / 1000.0

    def get_duration(self) -> float:
        """Return duration of the loaded track in seconds.  Returns 0.0 if nothing loaded."""
        return self._duration

    def check_track_ended(self) -> bool:
        """Poll whether the current track has finished naturally.

        Call this from a tkinter ``after()`` timer.  Returns True if the
        track ended and the callback was (or should be) invoked.
        """
        if not self._available or not self._playing:
            return False
        assert _pygame_mixer is not None
        if not _pygame_mixer.music.get_busy() and not self._paused:
            self._playing = False
            self._current_file = None
            if self._on_track_end:
                self._on_track_end()
            return True
        return False

    # ── Callbacks ──

    def set_on_track_end(self, callback: Callable[[], None] | None) -> None:
        """Register a callback invoked when the current track finishes naturally."""
        self._on_track_end = callback

    # ── Lifecycle ──

    def shutdown(self) -> None:
        """Clean up pygame mixer.  Call on app exit."""
        if not self._available:
            return
        assert _pygame_mixer is not None
        try:
            _pygame_mixer.music.stop()
            _pygame_mixer.quit()
        except Exception:
            pass
        self._available = False
        logger.info("AudioPlayer shut down")

    # ── Internal helpers ──

    @staticmethod
    def _read_duration(file_path: str) -> float:
        """Read track duration via mutagen (already a project dependency)."""
        try:
            import mutagen  # noqa: WPS433
            info = mutagen.File(file_path)  # type: ignore[attr-defined]
            if info is not None and info.info is not None:
                return info.info.length
        except Exception as exc:
            logger.debug("Could not read duration for %s: %s", file_path, exc)
        return 0.0
