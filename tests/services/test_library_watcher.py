"""Tests for the live-refresh watcher (ADR-015 D11). No real rekordbox files."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from source.services.library_watcher import LibraryWatcher, WatchState, should_refresh

SETTLE, MIN_INTERVAL = 5.0, 60.0


def _decide(state: WatchState, token: str | None, now: float) -> bool:
    return should_refresh(state, token, now, settle_s=SETTLE, min_interval_s=MIN_INTERVAL)


# ── should_refresh (pure) ──


def test_same_token_never_refreshes():
    state = WatchState(synced_token="a")
    assert not any(_decide(state, "a", t) for t in (0, 10, 100))


def test_none_token_never_refreshes():
    state = WatchState(synced_token="a")
    assert not any(_decide(state, None, t) for t in (0, 10, 100))


def test_new_token_waits_for_settle_window():
    state = WatchState(synced_token="a")
    assert not _decide(state, "b", 0)    # first sighting starts the window
    assert not _decide(state, "b", 4.9)  # still settling
    assert _decide(state, "b", 5.0)      # stable for settle_s


def test_still_changing_token_restarts_settle_window():
    state = WatchState(synced_token="a")
    _decide(state, "b", 0)
    assert not _decide(state, "c", 4)    # changed again: window restarts at 4
    assert not _decide(state, "c", 8.9)
    assert _decide(state, "c", 9)


def test_min_interval_between_refreshes():
    state = WatchState(synced_token="a")
    _decide(state, "b", 0)
    assert _decide(state, "b", 5)        # refresh #1 requested at 5
    # The refresh hasn't been marked yet (or failed): still "b" vs "a".
    assert not _decide(state, "b", 30)
    assert not _decide(state, "b", 64.9)
    assert _decide(state, "b", 65)       # 60 s after the last request


def test_after_mark_refreshed_same_token_is_quiet():
    watcher = LibraryWatcher(lambda: [], lambda _p: "a", lambda _p: None,
                             poll_s=1, settle_s=SETTLE, min_interval_s=MIN_INTERVAL)
    watcher.mark_refreshed("rekordbox", "b")
    state = watcher._states["rekordbox"]  # noqa: SLF001 - inspecting the pure state
    assert not any(_decide(state, "b", t) for t in (0, 10, 100))


def test_reverting_to_synced_token_clears_candidate():
    state = WatchState(synced_token="a")
    _decide(state, "b", 0)
    assert not _decide(state, "a", 3)
    assert state.candidate is None


# ── LibraryWatcher (ticks driven by hand, injected clock) ──


class _FakeProvider:
    def __init__(self, pid: str = "fake", tokens: list | None = None) -> None:
        self.id = pid
        self.tokens = list(tokens or [])
        self.calls = 0

    def change_token(self, _settings):
        self.calls += 1
        value = self.tokens[0] if len(self.tokens) == 1 else self.tokens.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _watcher(provider: Any, requested, *, synced="a", clock=None, targets=None):
    return LibraryWatcher(
        targets if targets is not None else (lambda: [(provider, {})]),  # fakes: duck-typed
        lambda _pid: synced,
        requested.append,
        poll_s=10, settle_s=SETTLE, min_interval_s=MIN_INTERVAL,
        clock=clock or _Clock(),
    )


def test_tick_requests_refresh_once_per_change_and_respects_mark():
    clock, requested = _Clock(), []
    provider = _FakeProvider(tokens=["b"])
    watcher = _watcher(provider, requested, clock=clock)

    for t in (0, 10, 20, 30):
        clock.now = t
        watcher.tick()
    assert requested == ["fake"]          # 10 s: settled → one request; then min interval
    watcher.mark_refreshed("fake", "b")
    for t in (100, 200):
        clock.now = t
        watcher.tick()
    assert requested == ["fake"]


def test_change_while_closed_is_picked_up_from_stored_token():
    clock, requested = _Clock(), []
    watcher = _watcher(_FakeProvider(tokens=["new"]), requested, synced="old", clock=clock)
    watcher.tick()
    clock.now = 10
    watcher.tick()
    assert requested == ["fake"]


def test_token_errors_do_not_stop_the_watcher():
    clock, requested = _Clock(), []
    provider = _FakeProvider(tokens=[OSError("gone"), RuntimeError("bug"), "b", "b"])
    watcher = _watcher(provider, requested, clock=clock)
    for t in (0, 10, 20, 30):
        clock.now = t
        watcher.tick()
    assert requested == ["fake"]


def test_provider_removed_from_targets_is_forgotten():
    provider, requested = _FakeProvider(tokens=["b"]), []
    current: list = [(provider, {})]
    watcher = _watcher(provider, requested, targets=lambda: list(current))
    watcher.tick()
    assert "fake" in watcher._states  # noqa: SLF001
    current.clear()                    # disabled, or auto-refresh turned off
    watcher.tick()
    assert watcher._states == {}       # noqa: SLF001
    assert provider.calls == 1


def test_targets_and_callback_errors_are_contained():
    def broken_targets():
        raise RuntimeError("settings unreadable")

    watcher = LibraryWatcher(broken_targets, lambda _p: None, lambda _p: None,
                             poll_s=1, settle_s=0, min_interval_s=0)
    watcher.tick()  # must not raise

    def boom(_pid):
        raise RuntimeError("ui gone")

    clock = _Clock()
    fake: Any = _FakeProvider(tokens=["b"])
    w2 = LibraryWatcher(lambda: [(fake, {})], lambda _p: "a", boom,
                        poll_s=1, settle_s=0, min_interval_s=0, clock=clock)
    w2.tick()
    w2.tick()  # requests → callback raises → logged, not propagated


# ── Thread smoke test ──


def test_thread_detects_one_flip_and_stops_promptly():
    requested: list[str] = []
    event = threading.Event()
    tokens = ["a"] * 3 + ["b"] * 1000

    class Flipping:
        id = "fake"

        def change_token(self, _settings):
            return tokens.pop(0) if len(tokens) > 1 else tokens[0]

    def on_needed(pid: str) -> None:
        requested.append(pid)
        event.set()

    flipping: Any = Flipping()
    watcher = LibraryWatcher(lambda: [(flipping, {})], lambda _p: "a", on_needed,
                             poll_s=0.01, settle_s=0.03, min_interval_s=60)
    watcher.start()
    assert event.wait(5)
    time.sleep(0.2)  # more ticks: still only one request (min interval)

    started = time.perf_counter()
    watcher.stop(timeout=1.0)
    assert time.perf_counter() - started < 1.0
    assert requested == ["fake"]
    assert watcher._thread is not None and not watcher._thread.is_alive()  # noqa: SLF001


def test_stop_wakes_a_long_sleep_immediately():
    watcher = LibraryWatcher(lambda: [], lambda _p: None, lambda _p: None,
                             poll_s=3600, settle_s=5, min_interval_s=60)
    watcher.start()
    time.sleep(0.05)
    started = time.perf_counter()
    watcher.stop(timeout=2.0)
    assert time.perf_counter() - started < 0.5


@pytest.mark.parametrize("token", [None])
def test_provider_without_change_detection_token_none_never_requests(token):
    clock, requested = _Clock(), []
    watcher = _watcher(_FakeProvider(tokens=[token]), requested, clock=clock)
    for t in (0, 10, 100, 1000):
        clock.now = t
        watcher.tick()
    assert requested == []


# ── Adaptive backoff and refresh on focus (Phase 3b review policy) ──

from source.services.library_watcher import record_refresh_result  # noqa: E402

BASE, MAX = 60.0, 300.0


def _record(state, changed=False, manual=False):
    record_refresh_result(state, changed=changed, manual=manual, base_s=BASE, max_s=MAX)


def test_backoff_doubles_every_three_unchanged_up_to_max():
    state = WatchState(synced_token="a")
    intervals = []
    for _ in range(12):
        _record(state)
        intervals.append(state.interval_s)
    assert intervals == [None, None, 120, 120, 120, 240, 240, 240, 300, 300, 300, 300]


def test_backoff_resets_on_change_or_manual():
    state = WatchState(synced_token="a")
    for _ in range(6):
        _record(state)
    assert state.interval_s == 240
    _record(state, changed=True)
    assert (state.interval_s, state.unchanged_streak) == (None, 0)
    for _ in range(3):
        _record(state)
    _record(state, manual=True)
    assert state.interval_s is None


def test_should_refresh_uses_backed_off_interval():
    state = WatchState(synced_token="a", interval_s=120)
    _decide(state, "b", 0)
    assert _decide(state, "b", 5)          # first request at 5
    _decide(state, "c", 70)                 # new token, settles by 75
    assert not _decide(state, "c", 76)     # 71 s since last: below 120
    assert _decide(state, "c", 125)        # 120 s since last


def test_focus_refreshes_promptly_with_floor_and_no_settle():
    state = WatchState(synced_token="a")
    assert should_refresh(state, "b", 0, settle_s=SETTLE, min_interval_s=MIN_INTERVAL,
                          focus=True, focus_floor_s=10)        # no settle wait
    state.synced_token = "b"
    assert not should_refresh(state, "c", 5, settle_s=SETTLE, min_interval_s=MIN_INTERVAL,
                              focus=True, focus_floor_s=10)    # inside the 10 s floor
    assert should_refresh(state, "c", 10, settle_s=SETTLE, min_interval_s=MIN_INTERVAL,
                          focus=True, focus_floor_s=10)        # floor passed (min interval not needed)


def test_focus_with_unchanged_token_does_nothing():
    state = WatchState(synced_token="a")
    assert not should_refresh(state, "a", 100, settle_s=SETTLE, min_interval_s=MIN_INTERVAL,
                              focus=True, focus_floor_s=10)


def test_watcher_mark_refreshed_applies_backoff_and_reset():
    clock, requested = _Clock(), []
    watcher = LibraryWatcher(lambda: [], lambda _p: "a", requested.append, poll_s=10,
                             settle_s=SETTLE, min_interval_s=BASE, max_interval_s=MAX, clock=clock)
    for _ in range(3):
        watcher.mark_refreshed("rekordbox", "t", changed=False)
    assert watcher.effective_interval("rekordbox") == 120
    watcher.mark_refreshed("rekordbox", "t", changed=False, manual=True)
    assert watcher.effective_interval("rekordbox") == BASE


def test_watcher_focus_tick_requests_promptly():
    clock, requested = _Clock(), []
    provider: Any = _FakeProvider(tokens=["b"])
    watcher = LibraryWatcher(lambda: [(provider, {})], lambda _p: "a", requested.append,
                             poll_s=10, settle_s=SETTLE, min_interval_s=BASE,
                             focus_floor_s=10, clock=clock)
    watcher.tick(focus=True)
    assert requested == ["fake"]


def test_request_focus_check_wakes_the_thread():
    requested: list[str] = []
    got = threading.Event()
    provider: Any = _FakeProvider(tokens=["b"])

    def on_needed(pid):
        requested.append(pid)
        got.set()

    watcher = LibraryWatcher(lambda: [(provider, {})], lambda _p: "a", on_needed,
                             poll_s=3600, settle_s=3600, min_interval_s=3600, focus_floor_s=0)
    watcher.start()
    time.sleep(0.05)               # first (non-focus) tick: settle blocks it
    assert requested == []
    watcher.request_focus_check()  # wakes the hour-long sleep
    assert got.wait(2)
    watcher.stop(timeout=1)
