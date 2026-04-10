from dataclasses import dataclass
from source.models.track import Track
from source.models.library import TrackLibrary
from source.services.camelot import compatibility_score, is_compatible
from source.config import (
    SUGGESTION_WEIGHTS,
    BPM_MAX_DIFF,
    ENERGY_SEVERE_PENALTY_THRESHOLD,
    MAX_SUGGESTIONS,
)


@dataclass
class ScoredTrack:
    track: Track
    total_score: float
    key_score: float
    energy_score: float
    bpm_score: float


def get_suggestions(current: Track, library: TrackLibrary,
                    exclude_paths: set = None,
                    allowed_crates: set = None,
                    allowed_genres: set = None) -> list[ScoredTrack]:
    """Score and rank all compatible tracks against the current track."""
    results = []
    w = SUGGESTION_WEIGHTS
    if exclude_paths is None:
        exclude_paths = set()

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

        # Hard filter: must be harmonically compatible
        if not current.camelot_key or not track.camelot_key:
            continue
        if not is_compatible(current.camelot_key, track.camelot_key):
            continue

        # Key score
        key_score = compatibility_score(current.camelot_key, track.camelot_key)

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
        ))

    results.sort(key=lambda s: s.total_score, reverse=True)
    return results[:MAX_SUGGESTIONS]
