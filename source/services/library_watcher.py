"""Live refresh: poll each provider's stat-only change token (ADR-015 D11).

One daemon thread wakes every ``poll_s`` seconds and asks each target provider
(enabled and declaring ``CHANGE_DETECTION``) for its change token. A refresh is
requested when the token differs from the one the last snapshot recorded, has
been stable for ``settle_s`` (rekordbox's write burst is over), and at least
``min_interval_s`` has passed since the last refresh request.

Refresh policy (Phase 3b review decision):
- **Adaptive backoff:** every 3 consecutive refreshes that changed nothing
  double the effective minimum interval, up to ``max_interval_s`` (rekordbox
  writes its WAL every ~30 s even when idle). Any real change or a manual
  sync resets it to ``min_interval_s``.
- **Refresh on focus:** when the app window regains focus, a provider whose
  token differs from its baseline is refreshed promptly (no settle wait),
  with a floor of ``focus_floor_s`` since the last refresh request.

Both decisions are pure (``should_refresh``, ``record_refresh_result``). No Tk
imports: the app marshals ``on_refresh_needed`` onto its main thread.
``stop()`` wakes the sleeping thread at once, so shutdown is never delayed.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from source.providers.base import LibraryProvider

logger = logging.getLogger(__name__)

Targets = list[tuple[LibraryProvider, Mapping[str, str]]]


@dataclass
class WatchState:
    synced_token: str | None  # token stored in the provider's last snapshot
    candidate: str | None = None  # last differing token seen
    candidate_since: float = 0.0
    last_refresh_at: float | None = None  # None = never requested in this process
    unchanged_streak: int = 0  # consecutive refreshes that changed nothing
    interval_s: float | None = None  # effective minimum interval; None = the base


BACKOFF_EVERY = 3  # unchanged refreshes per doubling of the interval


def record_refresh_result(
    state: WatchState, *, changed: bool, manual: bool, base_s: float, max_s: float,
) -> None:
    """Update the adaptive backoff after a successful sync (pure apart from ``state``)."""
    if changed or manual:
        state.unchanged_streak = 0
        state.interval_s = None
        return
    state.unchanged_streak += 1
    if state.unchanged_streak % BACKOFF_EVERY == 0:
        state.interval_s = min(max_s, (state.interval_s or base_s) * 2)


def should_refresh(
    state: WatchState,
    token: str | None,
    now: float,
    *,
    settle_s: float,
    min_interval_s: float,
    focus: bool = False,
    focus_floor_s: float = 30.0,
) -> bool:
    """Decide whether to request a refresh now (pure apart from updating ``state``).

    - ``None`` token, or the token the snapshot already has: no.
    - ``focus`` (window just regained focus): yes if at least ``focus_floor_s``
      has passed since the last request; no settle wait.
    - A token not seen before starts (or restarts) the settle window: no.
    - Still settling, or too soon after the last request (effective interval,
      which backoff may have raised above ``min_interval_s``): no.
    - Otherwise yes, and the request time is recorded.
    """
    if token is None or token == state.synced_token:
        state.candidate = None
        return False
    if focus and (state.last_refresh_at is None or now - state.last_refresh_at >= focus_floor_s):
        state.candidate = token
        state.last_refresh_at = now
        return True
    if token != state.candidate:
        state.candidate = token
        state.candidate_since = now
        return False
    if now - state.candidate_since < settle_s:
        return False
    interval = state.interval_s if state.interval_s is not None else min_interval_s
    if state.last_refresh_at is not None and now - state.last_refresh_at < interval:
        return False
    state.last_refresh_at = now
    return True


class LibraryWatcher:
    """Background poller that requests a quiet refresh when a provider's library changes."""

    def __init__(
        self,
        targets_fn: Callable[[], Targets],
        synced_token_fn: Callable[[str], str | None],
        on_refresh_needed: Callable[[str], None],
        *,
        poll_s: float,
        settle_s: float,
        min_interval_s: float,
        max_interval_s: float | None = None,
        focus_floor_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._targets_fn = targets_fn
        self._synced_token_fn = synced_token_fn
        self._on_refresh_needed = on_refresh_needed
        self._poll_s = poll_s
        self._settle_s = settle_s
        self._min_interval_s = min_interval_s
        self._max_interval_s = max_interval_s if max_interval_s is not None else min_interval_s
        self._focus_floor_s = focus_floor_s
        self._clock = clock
        self._states: dict[str, WatchState] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()  # set by stop() and request_focus_check()
        self._focus = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="library-watcher")
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        """Wake and stop the thread; returns within ``timeout`` (the thread is a daemon)."""
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def request_focus_check(self) -> None:
        """Ask for a prompt check with focus semantics (any thread; returns at once)."""
        self._focus.set()
        self._wake.set()

    def mark_refreshed(
        self,
        provider_id: str,
        token: str | None,
        *,
        changed: bool = True,
        manual: bool = False,
    ) -> None:
        """Record the token a sync stored and update the adaptive backoff."""
        with self._lock:
            state = self._states.get(provider_id)
            if state is None:
                state = self._states[provider_id] = WatchState(synced_token=token)
            state.synced_token = token
            state.candidate = None
            record_refresh_result(
                state, changed=changed, manual=manual,
                base_s=self._min_interval_s, max_s=self._max_interval_s,
            )

    def effective_interval(self, provider_id: str) -> float:
        """Current minimum interval for a provider (for logs and tests)."""
        with self._lock:
            state = self._states.get(provider_id)
            return state.interval_s if state and state.interval_s else self._min_interval_s

    def _run(self) -> None:
        # First tick straight away: a change made while Sidecar was closed is
        # picked up on startup (the snapshot's stored token is the baseline).
        while not self._stop.is_set():
            focus = self._focus.is_set()
            self._focus.clear()
            self.tick(focus=focus)
            self._wake.wait(self._poll_s)
            self._wake.clear()

    def tick(self, *, focus: bool = False) -> None:
        """One poll over all current targets (public for deterministic tests)."""
        try:
            targets = self._targets_fn()
        except Exception as e:  # noqa: BLE001 - the watcher thread must survive anything
            logger.warning("Live refresh: could not list providers (%s)", type(e).__name__)
            return
        current_ids = {provider.id for provider, _settings in targets}
        with self._lock:
            # Forget providers no longer watched (disabled, or auto-refresh off).
            for pid in [p for p in self._states if p not in current_ids]:
                del self._states[pid]
        for provider, settings in targets:
            if self._stop.is_set():
                return
            self._check(provider, settings, focus)

    def _check(self, provider: LibraryProvider, settings: Mapping[str, str], focus: bool) -> None:
        pid = provider.id
        try:
            token = provider.change_token(settings)
        except OSError as e:
            logger.debug("Live refresh: change token for %s failed (%s)", pid, type(e).__name__)
            return
        except Exception as e:  # noqa: BLE001 - one provider must not stop the watcher
            logger.warning("Live refresh: change token for %s failed (%s)", pid, type(e).__name__)
            return
        with self._lock:
            known = pid in self._states
        # Reading the stored snapshot token touches disk: keep it outside the lock.
        baseline = None if known else self._synced_token(pid)
        with self._lock:
            state = self._states.get(pid)
            if state is None:
                state = self._states[pid] = WatchState(synced_token=baseline)
            due = should_refresh(
                state, token, self._clock(),
                settle_s=self._settle_s, min_interval_s=self._min_interval_s,
                focus=focus, focus_floor_s=self._focus_floor_s,
            )
        if due:
            logger.info("Live refresh: %s library changed; requesting a refresh%s", pid,
                        " (window focus)" if focus else "")
            try:
                self._on_refresh_needed(pid)
            except Exception:  # noqa: BLE001 - callback errors are logged, the watcher continues
                logger.exception("Live refresh request for %s failed", pid)

    def _synced_token(self, pid: str) -> str | None:
        try:
            return self._synced_token_fn(pid)
        except Exception as e:  # noqa: BLE001 - treat as "no snapshot"
            logger.debug("Live refresh: no stored token for %s (%s)", pid, type(e).__name__)
            return None
