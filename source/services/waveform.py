"""Waveform amplitude data generation from audio files.

Produces a list of normalised floats (0.0-1.0) representing the visual
amplitude at evenly spaced points across the file.  Uses raw byte
sampling — no numpy or pydub dependency.  Results are cached in an
LRU-style dict so repeated plays don't re-read from disk.
"""

import logging
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
        """Read the file and produce amplitude samples.

        For WAV files the actual PCM samples are read.  For all other
        formats raw byte values are sampled — the result is approximate
        but visually adequate for a preview waveform.
        """
        path = Path(file_path)
        try:
            suffix = path.suffix.lower()
            if suffix == ".wav":
                return self._wav_waveform(path, num_bars)
            return self._raw_byte_waveform(path, num_bars)
        except Exception as exc:
            logger.warning("Waveform generation failed for %s: %s", path.name, exc)
            # Fallback: flat midline waveform
            return [0.5] * num_bars

    # ── WAV: read actual PCM samples ──

    @staticmethod
    def _wav_waveform(path: Path, num_bars: int) -> list[float]:
        """Extract amplitude from a WAV file by reading PCM sample values."""
        with open(path, "rb") as f:
            header = f.read(44)
            if len(header) < 44:
                return [0.5] * num_bars

            # Read basic WAV header fields
            # bytes 22-23: num channels, 34-35: bits per sample
            num_channels = struct.unpack_from("<H", header, 22)[0]
            bits_per_sample = struct.unpack_from("<H", header, 34)[0]
            bytes_per_sample = bits_per_sample // 8

            # Read all data after header
            f.seek(0, 2)
            file_size = f.tell()
            data_size = file_size - 44
            if data_size <= 0:
                return [0.5] * num_bars

            frame_size = bytes_per_sample * num_channels
            total_frames = data_size // frame_size
            if total_frames < num_bars:
                return [0.5] * num_bars

            frames_per_bar = total_frames // num_bars
            amplitudes: list[float] = []

            # Determine struct format for one sample
            if bytes_per_sample == 2:
                fmt = "<h"  # signed 16-bit
                max_val = 32768.0
            elif bytes_per_sample == 3:
                fmt = None  # handled specially
                max_val = 8388608.0
            else:
                # 8-bit or exotic — fall back to raw byte sampling
                return WaveformGenerator._raw_byte_waveform(path, num_bars)

            for bar in range(num_bars):
                offset = 44 + bar * frames_per_bar * frame_size
                # Read a small chunk and average
                chunk_frames = min(frames_per_bar, 512)
                f.seek(offset)
                raw = f.read(chunk_frames * frame_size)
                if not raw:
                    amplitudes.append(0.0)
                    continue

                total = 0.0
                count = 0
                pos = 0
                while pos + bytes_per_sample <= len(raw):
                    if fmt is not None:
                        val = struct.unpack_from(fmt, raw, pos)[0]
                    else:
                        # 24-bit: unpack 3 bytes as signed
                        b = raw[pos:pos + 3]
                        val = int.from_bytes(b, "little", signed=True)
                    total += abs(val)
                    count += 1
                    pos += frame_size  # skip to next frame (skip extra channels)

                amplitudes.append(total / (count * max_val) if count else 0.0)

        return _normalise(amplitudes)

    # ── Raw byte sampling (MP3, FLAC, AIFF, etc.) ──

    @staticmethod
    def _raw_byte_waveform(path: Path, num_bars: int) -> list[float]:
        """Sample raw byte amplitudes at regular intervals.

        Skips known headers (ID3v2 for MP3) so the samples come from
        actual audio frame data rather than metadata.
        """
        file_size = path.stat().st_size
        start_offset = _detect_audio_start(path)
        data_size = file_size - start_offset

        if data_size < num_bars:
            return [0.5] * num_bars

        chunk_size = max(data_size // num_bars, 1)
        # Read a small window at each sample point for averaging
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
                # Average absolute deviation from 128 (unsigned byte midpoint)
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
                # ID3v2 header: bytes 6-9 are synchsafe size
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
    # Generic: skip first 128 bytes (conservative for FLAC, AIFF headers)
    return 128


def _normalise(values: list[float]) -> list[float]:
    """Scale values so the maximum is 1.0.  Avoids division by zero."""
    if not values:
        return values
    peak = max(values)
    if peak <= 0:
        return [0.0] * len(values)
    return [v / peak for v in values]
