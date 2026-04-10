import threading

from source.services.crate_parser import parse_all_crates
from source.services.cache import save_cache


def sync_crates(subcrates_dir: str, progress_callback=None, done_callback=None):
    """Run crate sync on a background thread.

    Parses all .crate files, reads ID3 metadata, and writes the JSON cache.

    Args:
        subcrates_dir: Path to Serato Subcrates folder.
        progress_callback: Optional callable(message, current, total) called from bg thread.
        done_callback: Optional callable(total_tracks, num_crates, error) called when done.
    """

    def _run():
        try:
            tracks, crate_mtimes = parse_all_crates(
                subcrates_dir=subcrates_dir,
                progress_callback=progress_callback,
            )
            save_cache(tracks, crate_mtimes)
            total_tracks = len(tracks)
            num_crates = len(crate_mtimes)
            if done_callback:
                done_callback(total_tracks, num_crates, None)
        except Exception as e:
            if done_callback:
                done_callback(0, 0, str(e))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread
