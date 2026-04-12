"""Waveform amplitude data generation from audio files.

Produces a list of normalised floats (0.0-1.0) representing the RMS
amplitude at evenly spaced points across the track.  Uses pygame to
decode audio into PCM samples, giving an accurate waveform that reflects
the actual music dynamics — quiet breakdowns, loud drops, and builds
are clearly visible.

Results are cached in an LRU-style dict so repeated plays don't
re-decode from disk.
"""

import logging
import math
import struct
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_MAX_CACHE = 50
_DEFAULT_NUM_BARS = 300


class WaveformGenerator:
    """Generates visual amplitude data from audio files."""

    NUM_BARS: int = _DEFAULT_NUM_BARS

    def __init__(self) -> None:
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()

    # ── Public API ──

    def get_waveform(
        self,
        file_path: str,
        num_bars: int = _DEFAULT_NUM_BARS,
        callback: Callable[[list[float]], None] | None = None,
    ) -> list[float] | None:
        """Return cached waveform data or generate it asynchronously.

        If cached, returns the data immediately (list of floats 0.0-1.0).
        If not cached, starts background generation and calls *callback*
        with the data when ready.  Returns ``None`` in that case.
        """
        with self._lock:
            if file_path in self._cache:
                self._cache.move_to_end(file_path)
                return list(self._cache[file_path])

        # Generate in the background
        thread = threading.Thread(
            target=self._generate_and_cache,
            args=(file_path, num_bars, callback),
            daemon=True,
            name="waveform-gen",
        )
        thread.start()
        return None

    def clear_cache(self) -> None:
        """Drop all cached waveform data."""
        with self._lock:
            self._cache.clear()

    # ── Background generation ──

    def _generate_and_cache(
        self,
        file_path: str,
        num_bars: int,
        callback: Callable[[list[float]], None] | None,
    ) -> None:
        data = self._generate_waveform(file_path, num_bars)
        with self._lock:
            self._cache[file_path] = data
            # Evict oldest entries if over limit
            while len(self._cache) > _MAX_CACHE:
                self._cache.popitem(last=False)
        if callback is not None:
            callback(data)

    # ── Core generation logic ──

    def _generate_waveform(self, file_path: str, num_bars: int) -> list[float]:
        """Decode the audio and compute RMS amplitude per chunk.

        Uses pygame.mixer.Sound to decode the file into raw 16-bit PCM,
        then computes the root-mean-square amplitude for each of *num_bars*
        evenly-spaced chunks.  This produces a waveform that accurately
        reflects the music dynamics — breakdowns, drops, and builds are
        clearly visible.

        Falls back to raw byte sampling if pygame is unavailable.
        """
        path = Path(file_path)
        try:
            return self._pcm_waveform(path, num_bars)
        except Exception as exc:
            logger.debug("PCM waveform failed for %s: %s — trying raw bytes", path.name, exc)

        # Fallback: raw byte sampling (less accurate but no dependencies)
        try:
            return self._raw_byte_waveform(path, num_bars)
        except Exception as exc:
            logger.warning("Waveform generation failed for %s: %s", path.name, exc)
            return [0.5] * num_bars

    # ── PCM waveform via pygame (accurate) ──

    @staticmethod
    def _pcm_waveform(path: Path, num_bars: int) -> list[float]:
        """Decode audio to PCM via pygame and compute amplitude per chunk.

        Produces a DJ-useful waveform where breakdowns, drops, and builds
        are clearly distinguishable even on heavily mastered/limited
        tracks.  The approach:

        1. Divide the decoded PCM into *num_bars* chunks
        2. Within each chunk, compute RMS on short ~10ms sub-windows
        3. Take the peak sub-window RMS for each bar (preserves transients)
        4. Convert to dB scale — this is the key step that expands the
           visual contrast between "almost as loud" and "slightly quieter"
           sections in modern brickwall-limited music
        5. Map dB values to 0.0-1.0 with a usable floor of -40 dB
        """
        try:
            import pygame.mixer  # noqa: WPS433
        except ImportError:
            raise RuntimeError("pygame not available")

        # Ensure mixer is initialised (may be called before AudioPlayer
        # starts, or on a background thread after mixer.quit())
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)

        snd = pygame.mixer.Sound(str(path))
        try:
            raw = snd.get_raw()
            if not raw or len(raw) < 4:
                return [0.5] * num_bars

            # pygame mixer: 16-bit signed stereo @ 44100 Hz → 4 bytes/frame
            bytes_per_frame = 4
            total_frames = len(raw) // bytes_per_frame
            if total_frames < num_bars:
                return [0.5] * num_bars

            frames_per_bar = total_frames // num_bars

            # Short sub-windows (~10ms = 441 frames) capture individual
            # kick hits and transients rather than averaging them out.
            sub_window_frames = min(441, frames_per_bar)
            step_bytes = sub_window_frames * bytes_per_frame
            amplitudes: list[float] = []

            for bar in range(num_bars):
                bar_start = bar * frames_per_bar * bytes_per_frame
                bar_end = bar_start + frames_per_bar * bytes_per_frame

                peak_rms = 0.0
                pos = bar_start
                while pos < bar_end:
                    window_end = min(pos + step_bytes, bar_end)
                    chunk = raw[pos:window_end]

                    sum_sq = 0.0
                    count = 0
                    for i in range(0, len(chunk) - 1, bytes_per_frame):
                        sample = struct.unpack_from("<h", chunk, i)[0]
                        sum_sq += sample * sample
                        count += 1

                    if count > 0:
                        rms = math.sqrt(sum_sq / count) / 32768.0
                        if rms > peak_rms:
                            peak_rms = rms

                    pos = window_end

                amplitudes.append(peak_rms)

        finally:
            del snd

        return _to_db_normalised(amplitudes)

    # ── Raw byte sampling fallback (MP3, FLAC, AIFF, etc.) ──

    @staticmethod
    def _raw_byte_waveform(path: Path, num_bars: int) -> list[float]:
        """Sample raw byte amplitudes at regular intervals.

        Skips known headers (ID3v2 for MP3) so the samples come from
        actual audio frame data rather than metadata.  This is a fallback
        when pygame is unavailable.
        """
        file_size = path.stat().st_size
        start_offset = _detect_audio_start(path)
        data_size = file_size - start_offset

        if data_size < num_bars:
            return [0.5] * num_bars

        chunk_size = max(data_size // num_bars, 1)
        sample_window = min(chunk_size, 1024)

        amplitudes: list[float] = []
        with open(path, "rb") as f:
            for bar in range(num_bars):
                offset = start_offset + bar * chunk_size
                f.seek(offset)
                raw = f.read(sample_window)
                if not raw:
                    amplitudes.append(0.0)
                    continue
                total = sum(abs(b - 128) for b in raw)
                amplitudes.append(total / (len(raw) * 128.0))

        return _normalise(amplitudes)


def _detect_audio_start(path: Path) -> int:
    """Return the byte offset where audio data likely begins.

    For MP3 files this skips the ID3v2 header.  For other formats it
    returns a small fixed offset to skip container headers.
    """
    try:
        with open(path, "rb") as f:
            magic = f.read(10)
            if len(magic) >= 10 and magic[:3] == b"ID3":
                size_bytes = magic[6:10]
                size = (
                    (size_bytes[0] & 0x7F) << 21
                    | (size_bytes[1] & 0x7F) << 14
                    | (size_bytes[2] & 0x7F) << 7
                    | (size_bytes[3] & 0x7F)
                )
                return 10 + size
    except OSError:
        pass
    return 128


def _to_db_normalised(values: list[float], floor_db: float = -40.0) -> list[float]:
    """Convert linear amplitudes to dB scale, then map to 0.0-1.0.

    This is the key transformation for getting a useful waveform from
    heavily mastered music.  A -3dB difference (barely perceptible as
    a volume change) becomes a large visual change on a dB-scaled
    waveform, making breakdowns, builds, and drops clearly visible
    even on brickwall-limited tracks.

    *floor_db* sets the silence threshold — anything below this is
    drawn at minimum height.  -40 dB works well for music (true
    silence and very quiet room tone disappear; any musical content
    is visible).
    """
    if not values:
        return values

    db_values: list[float] = []
    for v in values:
        if v <= 0:
            db_values.append(floor_db)
        else:
            db = 20.0 * math.log10(v)
            db_values.append(max(db, floor_db))

    # Map [floor_db .. 0dB] → [0.0 .. 1.0]
    db_range = abs(floor_db)
    return [max(0.0, (db - floor_db) / db_range) for db in db_values]


def _normalise(values: list[float]) -> list[float]:
    """Scale values so the maximum is 1.0.  Avoids division by zero."""
    if not values:
        return values
    peak = max(values)
    if peak <= 0:
        return [0.0] * len(values)
    return [v / peak for v in values]
