from __future__ import annotations

from dataclasses import dataclass
from source.models.track import Track
from source.models.library import TrackLibrary
from source.services.camelot import classify, compatibility_score, shift_key, HarmonicTier
from source.services.suggestion_filters import SuggestionFilters
from source.config import (
    SUGGESTION_WEIGHTS,
    BPM_MAX_DIFF,
    ENERGY_SEVERE_PENALTY_THRESHOLD,
    MAX_SUGGESTIONS,
    KEY_OFFSET_RANGE,
)


@dataclass
class ScoredTrack:
    track: Track
    total_score: float
    key_score: float
    energy_score: float
    bpm_score: float
    harmonic_tier: HarmonicTier


def get_suggestions(current: Track, library: TrackLibrary,
                    exclude_paths: set[str] | None = None,
                    allowed_crates: set[str] | None = None,
                    allowed_genres: set[str] | None = None,
                    key_offset: int = 0,
                    date_from: float | None = None,
                    date_to: float | None = None,
                    filters: SuggestionFilters | None = None) -> list[ScoredTrack]:
    """Score and rank all compatible tracks against the current track.

    ``filters`` is the single typed filter snapshot (ADR-012). When provided it
    SUPERSEDES the individual ``allowed_crates`` / ``allowed_genres`` /
    ``key_offset`` / ``date_from`` / ``date_to`` keyword args — they are unpacked
    from it before any filtering runs. The individual kwargs remain as a fallback
    for callers and tests that don't pass a ``filters`` object.

    ``key_offset`` re-anchors the harmonic target up (+) or down (-) the Camelot
    wheel: candidates are scored against ``shift_key(current.camelot_key,
    key_offset)`` and exact same-key (PERFECT) candidates are excluded, steering
    the DJ off like-for-like matches. It is clamped to ``KEY_OFFSET_RANGE`` so an
    out-of-range value can't silently re-anchor to an unintended key.
    ``key_offset=0`` (the default) reproduces today's exact behaviour — the target
    is the current key and nothing is excluded. If the current track has
    no/invalid key, the offset path is skipped and the function falls back to
    offset-0 behaviour (blueprint R5).

    The shift is directional but the underlying ``compatibility_score`` stays
    symmetric — direction is applied as a pre-shift to the target key only, never
    inside the score (ADR-010; blueprint R4).

    ``date_from`` / ``date_to`` filter candidates by ``track.date_added`` (the
    file's creation time on this machine, read fresh each sync; see ADR-013).
    Both ``None`` (the default) means no date
    filter — today's behaviour. A track with ``date_added == 0.0`` (unknown) is
    excluded when ``date_from`` is set: it can't be proven to be in range
    (blueprint §4).
    """
    results = []
    w = SUGGESTION_WEIGHTS
    if exclude_paths is None:
        exclude_paths = set()

    # A SuggestionFilters snapshot supersedes the individual keyword args (ADR-012).
    if filters is not None:
        allowed_crates = filters.allowed_crates
        allowed_genres = filters.allowed_genres
        key_offset = filters.key_offset
        date_from = filters.date_from
        date_to = filters.date_to

    # Defensive clamp: a future caller passing a raw out-of-range value must not
    # silently re-anchor to an unintended key (blueprint §2).
    key_offset = max(KEY_OFFSET_RANGE[0], min(KEY_OFFSET_RANGE[1], key_offset))

    # Resolve the harmonic target once, outside the loop. A non-zero offset shifts
    # the target; an invalid/empty current key falls back to offset 0 (blueprint R5).
    target_key = current.camelot_key
    if key_offset and current.camelot_key:
        shifted = shift_key(current.camelot_key, key_offset)
        if shifted:
            target_key = shifted
    suppress_same_key = key_offset != 0 and target_key != current.camelot_key

    for track in library.tracks:
        # Skip self and session history
        if track.full_file_path == current.full_file_path:
            continue
        if track.full_file_path in exclude_paths:
            continue

        # Crate filter: track must belong to at least one allowed crate
        if allowed_crates is not None and not allowed_crates.intersection(track.crates):
            continue

        # Genre filter
        if allowed_genres is not None and track.genre not in allowed_genres:
            continue

        # Date-added range filter. A track with date_added == 0.0 (unknown) is
        # excluded when date_from is set — can't prove it's in range (blueprint §4).
        if date_from is not None and track.date_added < date_from:
            continue
        if date_to is not None and track.date_added > date_to:
            continue

        # Harmonic filter: offer any track with a usable harmonic relationship.
        # compatibility_score > 0 means some tier matched; 0.0 means unrelated. See ADR-010.
        if not current.camelot_key or not track.camelot_key:
            continue
        # Same-key suppression (offset != 0): drop PERFECT-vs-current candidates so
        # the DJ is steered off like-for-like matches. PERFECT == identical key
        # (score 1.0). Measured against the CURRENT key, not the shifted target.
        if suppress_same_key and compatibility_score(current.camelot_key, track.camelot_key) >= 1.0:
            continue
        key_score = compatibility_score(target_key, track.camelot_key)
        if key_score <= 0:
            continue
        harmonic_tier = classify(target_key, track.camelot_key)

        # Energy score
        if current.energy and track.energy:
            energy_diff = abs(current.energy - track.energy)
            energy_score = max(0.0, 1.0 - (energy_diff / 8.0))
            if energy_diff > ENERGY_SEVERE_PENALTY_THRESHOLD:
                energy_score *= 0.3
        else:
            energy_score = 0.5  # neutral if unknown

        # BPM score
        if current.bpm and track.bpm:
            bpm_diff = abs(current.bpm - track.bpm)
            bpm_score = max(0.0, 1.0 - (bpm_diff / BPM_MAX_DIFF))
        else:
            bpm_score = 0.5  # neutral if unknown

        total = (
            w["key"] * key_score
            + w["energy"] * energy_score
            + w["bpm"] * bpm_score
        )

        results.append(ScoredTrack(
            track=track,
            total_score=total,
            key_score=key_score,
            energy_score=energy_score,
            bpm_score=bpm_score,
            harmonic_tier=harmonic_tier,
        ))

    results.sort(key=lambda s: s.total_score, reverse=True)
    return results[:MAX_SUGGESTIONS]
