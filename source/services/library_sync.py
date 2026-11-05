"""Background library sync across providers (ADR-015 D5).

Replaces ``crate_sync.py``. One daemon thread scans the requested providers
sequentially, persists each snapshot (``library_store``, one file per
provider), and reports a ``SyncReport`` through ``done_callback`` exactly once.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from source.providers.base import LibraryProvider, ProgressCallback, ProviderError
from source.services import library_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncRequest:
    provider: LibraryProvider
    settings: Mapping[str, str]


@dataclass(frozen=True)
class ProviderSyncResult:
    provider_id: str
    track_count: int = 0
    crate_count: int = 0  # len(snapshot.crates) - INCLUDES empty crates (toast parity)
    warnings: tuple[str, ...] = ()
    error: str | None = None
    changed: bool = True  # False when the new snapshot's content hash equals the stored one
    change_token: str | None = None  # the snapshot's change token (live refresh, D11)


@dataclass(frozen=True)
class SyncReport:
    results: tuple[ProviderSyncResult, ...]
    # Set by SyncCoordinator: another (merged) run will start right after this
    # one, so UI "syncing" state shouldn't be cleared yet.
    follow_up_pending: bool = False

    @property
    def ok(self) -> bool:
        return all(r.error is None for r in self.results)

    @property
    def total_tracks(self) -> int:
        return sum(r.track_count for r in self.results)

    @property
    def total_crates(self) -> int:
        return sum(r.crate_count for r in self.results)

    @property
    def first_error(self) -> str | None:
        return next((r.error for r in self.results if r.error is not None), None)

    @property
    def any_changed(self) -> bool:
        return any(r.changed for r in self.results if r.error is None)


def _error_text(e: BaseException) -> str:
    """User-facing error text; never empty, so a failure can't read as success."""
    return str(e) or type(e).__name__


def _sync_one(request: SyncRequest, progress: ProgressCallback | None) -> ProviderSyncResult:
    provider_id = "?"
    try:
        provider_id = request.provider.id
        snapshot = request.provider.scan(request.settings, progress)
        changed = library_store.save_snapshot(snapshot)
    except (ProviderError, OSError) as e:
        logger.warning("Sync failed for %s: %s", provider_id, e)
        return ProviderSyncResult(provider_id=provider_id, error=_error_text(e))
    except Exception as e:  # noqa: BLE001 - documented last resort at the thread boundary
        # A provider bug must not kill the sync thread silently or block other
        # providers (ADR-015 D5). Log the traceback and report the failure.
        logger.exception("Unexpected error syncing %s", provider_id)
        return ProviderSyncResult(provider_id=provider_id, error=_error_text(e))
    return ProviderSyncResult(
        provider_id=provider_id,
        track_count=len(snapshot.tracks),
        crate_count=len(snapshot.crates),
        warnings=tuple(snapshot.warnings),
        changed=changed,
        change_token=snapshot.change_token,
    )


def sync_providers(
    requests: Sequence[SyncRequest],
    progress_callback: ProgressCallback | None = None,
    done_callback: Callable[[SyncReport], None] | None = None,
) -> threading.Thread:
    """Scan and persist each requested provider on a background daemon thread.

    ``progress_callback`` and ``done_callback`` are called from the background
    thread; Tk callers must marshal them with ``after(0, ...)``. Providers are
    scanned in order; one provider's failure never stops the others.
    """

    def _run() -> None:
        results = tuple(_sync_one(req, progress_callback) for req in requests)
        if done_callback:
            done_callback(SyncReport(results=results))

    thread = threading.Thread(target=_run, daemon=True, name="library-sync")
    thread.start()
    return thread


# ── Single-flight coordination (ADR-015 D5, T3b.3) ──

SyncDoneCallback = Callable[[SyncReport, bool], None]  # (report, silent)
_Runner = Callable[..., threading.Thread]


class SyncCoordinator:
    """At most one sync runs at a time; requests during a run are merged, not dropped.

    A request that arrives while a sync runs is coalesced into ONE pending
    follow-up: provider requests are merged by provider id (the latest
    settings win), the follow-up is silent only if every merged request was
    silent (a manual request upgrades it), and each distinct ``done_callback``
    is called once with ``(report, silent)``. When a run finishes its
    callbacks fire, then the pending follow-up (if any) starts.

    Callbacks are called on the sync thread; Tk callers must marshal them.
    Thread-safe.
    """

    def __init__(self, runner: _Runner | None = None) -> None:
        self._runner = runner
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._running = False
        self._current_silent = True  # mode of the run in progress
        self._pending: dict[str, SyncRequest] = {}
        self._pending_silent: bool | None = None
        self._pending_callbacks: dict[SyncDoneCallback, None] = {}

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def manual_in_progress(self) -> bool:
        """A manual (non-silent) sync is running, or merged into the pending follow-up.

        Quiet live refreshes don't count: the settings dialog shows "Syncing…"
        only for work the DJ asked for.
        """
        with self._lock:
            if not self._running:
                return False
            pending_manual = bool(self._pending) and self._pending_silent is False
            return not self._current_silent or pending_manual

    @property
    def has_pending(self) -> bool:
        """True if a merged follow-up run is queued behind the current one."""
        with self._lock:
            return bool(self._pending)

    def wait_idle(self, timeout: float) -> bool:
        """Block until no sync is running or pending (or ``timeout``). True if idle."""
        with self._idle:
            return self._idle.wait_for(lambda: not self._running, timeout)

    def _set_idle(self) -> None:
        """Mark idle; caller holds the lock."""
        self._running = False
        self._idle.notify_all()

    def request(
        self,
        requests: Sequence[SyncRequest],
        *,
        silent: bool,
        done_callback: SyncDoneCallback,
    ) -> bool:
        """Start a sync now (returns True) or merge it into the pending follow-up (False).

        Re-raises whatever prevented the sync thread from starting (e.g. ``RuntimeError``).
        """
        with self._lock:
            if self._running:
                for req in requests:
                    self._pending[req.provider.id] = req
                self._pending_silent = silent if self._pending_silent is None else (
                    self._pending_silent and silent
                )
                self._pending_callbacks[done_callback] = None
                return False
            self._running = True
            self._current_silent = silent
        try:
            self._start(list(requests), silent, [done_callback])
        except Exception:
            with self._lock:
                self._set_idle()
            raise
        return True

    def _start(
        self, requests: list[SyncRequest], silent: bool, callbacks: list[SyncDoneCallback],
    ) -> None:
        def on_done(report: SyncReport) -> None:
            with self._lock:
                follow_up = bool(self._pending)
            if follow_up:
                report = dataclasses.replace(report, follow_up_pending=True)
            for callback in callbacks:
                try:
                    callback(report, silent)
                except Exception:  # noqa: BLE001 - one callback must not block the follow-up
                    logger.exception("Sync done callback failed")
            self._finish()

        runner = self._runner or sync_providers
        runner(requests, done_callback=on_done)

    def _finish(self) -> None:
        with self._lock:
            if not self._pending:
                self._set_idle()
                return
            requests = list(self._pending.values())
            silent = bool(self._pending_silent)
            self._current_silent = silent
            callbacks = list(self._pending_callbacks)
            self._pending, self._pending_silent, self._pending_callbacks = {}, None, {}
        try:
            self._start(requests, silent, callbacks)
        except Exception as e:  # noqa: BLE001 - nobody else can report it; see below
            logger.error("Could not start the follow-up sync (%s)", type(e).__name__)
            with self._lock:
                self._set_idle()
            report = SyncReport(tuple(
                ProviderSyncResult(provider_id=r.provider.id, error="Couldn't start the sync")
                for r in requests
            ))
            for callback in callbacks:
                try:
                    callback(report, silent)
                except Exception:  # noqa: BLE001
                    logger.exception("Sync done callback failed")
