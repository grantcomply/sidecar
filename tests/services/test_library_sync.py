"""Tests for ``source.services.library_sync`` with a fake provider."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping
from typing import Any

import pytest

from source.providers.base import (
    CrateInfo,
    DeckLoadNotSupported,
    LibraryProvider,
    ProviderCapability,
    ProviderError,
    ProviderIssue,
    ProviderSnapshot,
    SettingSpec,
    TrackRecord,
)
from source.services import library_store, library_sync


class FakeProvider:
    """Satisfies the ``LibraryProvider`` protocol without inheritance."""

    id = "fake"
    display_name = "Fake"
    crate_noun = "crate"

    def __init__(self, result: ProviderSnapshot | Exception, provider_id: str = "fake") -> None:
        self.id = provider_id
        self._result = result
        self.scan_calls = 0

    def setting_specs(self) -> tuple[SettingSpec, ...]:
        return ()

    def default_settings(self) -> dict[str, str]:
        return {}

    def detect(self) -> bool:
        return False

    def detected_values(self, settings: Mapping[str, str]) -> dict[str, str]:
        return {}

    def capabilities(self, settings: Mapping[str, str]) -> frozenset[ProviderCapability]:
        return frozenset()

    def validate(self, settings: Mapping[str, str]) -> list[ProviderIssue]:
        return []

    def scan(self, settings, progress=None) -> ProviderSnapshot:
        self.scan_calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    def change_token(self, settings: Mapping[str, str]) -> str | None:
        return None

    def load_to_deck(self, settings: Mapping[str, str], track_path: str, deck: int) -> None:
        raise DeckLoadNotSupported("Not supported")


def _snapshot() -> ProviderSnapshot:
    crates = {
        "fake:a": CrateInfo("fake:a", "fake", "Crate A", ("Crate A",)),
        "fake:b": CrateInfo("fake:b", "fake", "Crate B", ("Crate B",)),
        "fake:empty": CrateInfo("fake:empty", "fake", "Empty", ("Empty",)),
    }
    tracks: dict[str, TrackRecord] = {
        "/m/1.mp3": {"file_name": "1.mp3", "crates": ["fake:a", "fake:b"]},
        "/m/2.mp3": {"file_name": "2.mp3", "crates": ["fake:b"]},
    }
    return ProviderSnapshot(
        provider_id="fake",
        tracks=tracks,
        crates=crates,
        fingerprint={"a": 1.0, "b": 2.0, "empty": 3.0},
        warnings=["one warning"],
    )


class _SaveRecorder:
    def __init__(self) -> None:
        self.snapshots: list[ProviderSnapshot] = []
        self.changed = True

    def __call__(self, snapshot: ProviderSnapshot) -> bool:
        self.snapshots.append(snapshot)
        return self.changed


@pytest.fixture
def saved(monkeypatch) -> _SaveRecorder:
    recorder = _SaveRecorder()
    monkeypatch.setattr(library_store, "save_snapshot", recorder)
    return recorder


def _run(provider: LibraryProvider) -> list[library_sync.SyncReport]:
    reports: list[library_sync.SyncReport] = []
    thread = library_sync.sync_providers(
        [library_sync.SyncRequest(provider, {})], done_callback=reports.append,
    )
    thread.join(timeout=5)
    assert not thread.is_alive()
    return reports


def test_fake_provider_satisfies_protocol():
    assert isinstance(FakeProvider(_snapshot()), LibraryProvider)


def test_sync_success_reports_counts_and_saves_snapshot(saved):
    reports = _run(FakeProvider(_snapshot()))

    assert len(reports) == 1
    report = reports[0]
    assert report.ok
    assert report.first_error is None
    assert report.total_tracks == 2
    assert report.total_crates == 3  # includes the empty crate
    assert report.results[0].warnings == ("one warning",)
    assert report.any_changed

    assert len(saved.snapshots) == 1
    assert saved.snapshots[0].tracks["/m/1.mp3"].get("crates") == ["fake:a", "fake:b"]


def test_sync_unchanged_snapshot_reports_not_changed(saved):
    saved.changed = False

    report = _run(FakeProvider(_snapshot()))[0]

    assert report.ok
    assert report.results[0].changed is False
    assert not report.any_changed


def test_sync_provider_error_reports_error_and_skips_save(saved):
    reports = _run(FakeProvider(ProviderError("Crates folder not found")))

    assert len(reports) == 1
    assert not reports[0].ok
    assert reports[0].first_error == "Crates folder not found"
    assert reports[0].total_tracks == 0
    assert saved.snapshots == []


def test_sync_oserror_reports_str_of_error(saved):
    err = FileNotFoundError(2, "No such file or directory", "X:/nope")

    reports = _run(FakeProvider(err))

    assert reports[0].first_error == str(err)
    assert saved.snapshots == []


def test_sync_unexpected_error_reported_and_logged(saved, caplog):
    with caplog.at_level(logging.ERROR, logger="source.services.library_sync"):
        reports = _run(FakeProvider(RuntimeError("boom")))

    assert len(reports) == 1
    assert reports[0].first_error == "boom"
    assert saved.snapshots == []
    assert any(r.exc_info and "fake" in r.getMessage() for r in caplog.records)


def test_sync_exception_with_empty_message_reports_type_name(saved):
    # T2.10 follow-up: an empty message must never read as success.
    reports = _run(FakeProvider(RuntimeError()))

    assert reports[0].first_error == "RuntimeError"
    assert not reports[0].ok
    assert saved.snapshots == []


def test_sync_save_failure_reported(monkeypatch):
    def _fail(_snapshot):
        raise PermissionError("denied")

    monkeypatch.setattr(library_store, "save_snapshot", _fail)

    reports = _run(FakeProvider(_snapshot()))

    assert reports[0].first_error == "denied"


def test_sync_done_callback_called_exactly_once(saved):
    calls = []
    provider = FakeProvider(_snapshot())
    thread = library_sync.sync_providers(
        [library_sync.SyncRequest(provider, {})], done_callback=calls.append,
    )
    thread.join(timeout=5)

    assert len(calls) == 1
    assert provider.scan_calls == 1


def test_sync_without_done_callback_runs(saved):
    library_sync.sync_providers([library_sync.SyncRequest(FakeProvider(_snapshot()), {})]).join(5)
    assert len(saved.snapshots) == 1


def test_sync_no_requests_reports_empty_ok(saved):
    reports: list[library_sync.SyncReport] = []
    library_sync.sync_providers([], done_callback=reports.append).join(5)

    assert reports == [library_sync.SyncReport(results=())]
    assert reports[0].ok


def test_sync_runs_requests_in_order_and_isolates_failures(saved):
    failing = FakeProvider(ProviderError("Broken"), provider_id="first")
    working = FakeProvider(_snapshot(), provider_id="second")
    reports: list[library_sync.SyncReport] = []

    library_sync.sync_providers(
        [library_sync.SyncRequest(failing, {}), library_sync.SyncRequest(working, {})],
        done_callback=reports.append,
    ).join(5)

    results = reports[0].results
    assert [r.provider_id for r in results] == ["first", "second"]
    assert results[0].error == "Broken"
    assert results[1].error is None and results[1].track_count == 2
    assert reports[0].first_error == "Broken"
    assert len(saved.snapshots) == 1


class _BrokenIdProvider(FakeProvider):
    """A buggy provider whose ``id`` attribute itself raises."""

    def __getattribute__(self, name: str):
        if name == "id":
            raise RuntimeError("no id")
        return super().__getattribute__(name)


def test_sync_done_callback_fires_even_if_provider_id_raises(saved):
    reports = _run(_BrokenIdProvider(_snapshot()))

    assert len(reports) == 1
    assert reports[0].results[0].provider_id == "?"
    assert reports[0].first_error == "no id"


# ── SyncCoordinator (T3b.3) ──


class _ManualRunner:
    """Records runs; the test finishes each one by calling ``finish()``."""

    def __init__(self) -> None:
        self.runs: list[tuple[list[str], Any]] = []
        self.active = 0
        self.max_active = 0

    def __call__(self, requests, done_callback=None, progress_callback=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.runs.append(([r.provider.id for r in requests], done_callback))
        return threading.Thread(target=lambda: None)

    def finish(self, index: int = -1) -> None:
        ids, done = self.runs[index]
        self.active -= 1
        done(library_sync.SyncReport(tuple(
            library_sync.ProviderSyncResult(provider_id=pid) for pid in ids
        )))


def _req(pid: str) -> library_sync.SyncRequest:
    return library_sync.SyncRequest(FakeProvider(_snapshot(), provider_id=pid), {"v": pid})


def test_coordinator_runs_immediately_when_idle():
    runner, calls = _ManualRunner(), []
    coord = library_sync.SyncCoordinator(runner)

    assert coord.request([_req("rekordbox")], silent=True,
                         done_callback=lambda r, s: calls.append(s)) is True
    assert coord.is_running
    runner.finish()
    assert calls == [True]
    assert not coord.is_running


def test_coordinator_coalesces_three_requests_into_one_follow_up():
    runner, calls = _ManualRunner(), []
    coord = library_sync.SyncCoordinator(runner)
    cb = lambda r, s: calls.append(([x.provider_id for x in r.results], s))  # noqa: E731

    coord.request([_req("rekordbox")], silent=True, done_callback=cb)
    assert coord.request([_req("rekordbox")], silent=True, done_callback=cb) is False
    assert coord.request([_req("serato")], silent=True, done_callback=cb) is False
    assert coord.request([_req("rekordbox")], silent=True, done_callback=cb) is False
    assert len(runner.runs) == 1  # nothing ran alongside

    runner.finish(0)
    assert len(runner.runs) == 2
    assert sorted(runner.runs[1][0]) == ["rekordbox", "serato"]  # merged, not dropped
    runner.finish(1)
    assert calls == [(["rekordbox"], True), (["rekordbox", "serato"], True)]  # cb once per run
    assert runner.max_active == 1
    assert not coord.is_running


def test_coordinator_manual_request_upgrades_silent_follow_up():
    runner, calls = _ManualRunner(), []
    coord = library_sync.SyncCoordinator(runner)
    silent_cb = lambda r, s: calls.append(("silent_cb", s))  # noqa: E731
    manual_cb = lambda r, s: calls.append(("manual_cb", s))  # noqa: E731

    coord.request([_req("serato")], silent=False, done_callback=manual_cb)
    coord.request([_req("rekordbox")], silent=True, done_callback=silent_cb)
    coord.request([_req("rekordbox")], silent=False, done_callback=manual_cb)
    runner.finish(0)
    runner.finish(1)

    assert calls == [("manual_cb", False), ("silent_cb", False), ("manual_cb", False)]


def test_coordinator_latest_settings_win_when_merging():
    runner = _ManualRunner()
    seen: list[dict] = []

    def recording_runner(requests, done_callback=None, progress_callback=None):
        seen.append({r.provider.id: dict(r.settings) for r in requests})
        return runner(requests, done_callback=done_callback)

    coord = library_sync.SyncCoordinator(recording_runner)
    coord.request([_req("serato")], silent=False, done_callback=lambda r, s: None)
    old = library_sync.SyncRequest(FakeProvider(_snapshot(), "rekordbox"), {"v": "old"})
    new = library_sync.SyncRequest(FakeProvider(_snapshot(), "rekordbox"), {"v": "new"})
    coord.request([old], silent=True, done_callback=lambda r, s: None)
    coord.request([new], silent=True, done_callback=lambda r, s: None)
    runner.finish(0)

    assert seen[1] == {"rekordbox": {"v": "new"}}


def test_coordinator_callback_error_does_not_block_follow_up():
    runner = _ManualRunner()
    coord = library_sync.SyncCoordinator(runner)

    def boom(_r, _s):
        raise RuntimeError("ui gone")

    coord.request([_req("a")], silent=True, done_callback=boom)
    coord.request([_req("b")], silent=True, done_callback=lambda r, s: None)
    runner.finish(0)
    assert len(runner.runs) == 2


def test_coordinator_start_failure_resets_and_raises():
    def failing_runner(*_a, **_k):
        raise RuntimeError("can't start new thread")

    coord = library_sync.SyncCoordinator(failing_runner)
    with pytest.raises(RuntimeError):
        coord.request([_req("a")], silent=False, done_callback=lambda r, s: None)
    assert not coord.is_running


def test_coordinator_follow_up_start_failure_reports_error_to_callbacks():
    runner, calls = _ManualRunner(), []
    starts = {"n": 0}

    def flaky(requests, done_callback=None, progress_callback=None):
        starts["n"] += 1
        if starts["n"] == 2:
            raise RuntimeError("can't start new thread")
        return runner(requests, done_callback=done_callback)

    coord = library_sync.SyncCoordinator(flaky)
    coord.request([_req("a")], silent=True, done_callback=lambda r, s: None)
    coord.request([_req("b")], silent=True, done_callback=lambda r, s: calls.append(r.first_error))
    runner.finish(0)

    assert calls == ["Couldn't start the sync"]
    assert not coord.is_running


def test_coordinator_real_threads_never_overlap(saved):
    """Deterministic: the first scan blocks until every request has been made."""
    release = threading.Event()
    first_scan_started = threading.Event()
    active, peak, lock = [0], [0], threading.Lock()

    class Gated(FakeProvider):
        def scan(self, settings, progress=None):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            first_scan_started.set()
            release.wait(5)
            with lock:
                active[0] -= 1
            return super().scan(settings, progress)

    results: list[tuple[bool, bool]] = []
    all_done = threading.Event()

    def cb(report, silent):
        results.append((silent, report.follow_up_pending))
        if len(results) == 2:
            all_done.set()

    coord = library_sync.SyncCoordinator()
    coord.request([library_sync.SyncRequest(Gated(_snapshot(), "a"), {})], silent=True,
                  done_callback=cb)
    assert first_scan_started.wait(5)
    for _ in range(5):  # all arrive while the first run is blocked
        assert coord.request([library_sync.SyncRequest(Gated(_snapshot(), "a"), {})],
                             silent=False, done_callback=cb) is False
    release.set()

    assert all_done.wait(5)
    assert coord.wait_idle(5)
    assert peak[0] == 1
    # First run (silent) knew a follow-up was pending; the merged one is manual.
    assert results == [(True, True), (False, False)]


def test_wait_idle_times_out_while_running_then_succeeds():
    runner = _ManualRunner()
    coord = library_sync.SyncCoordinator(runner)
    assert coord.wait_idle(0.01) is True
    coord.request([_req("a")], silent=True, done_callback=lambda r, s: None)
    assert coord.wait_idle(0.05) is False
    runner.finish()
    assert coord.wait_idle(0.05) is True


def test_coordinator_start_failure_of_any_type_resets():
    def failing_runner(*_a, **_k):
        raise ValueError("unexpected")

    coord = library_sync.SyncCoordinator(failing_runner)
    with pytest.raises(ValueError):
        coord.request([_req("a")], silent=False, done_callback=lambda r, s: None)
    assert not coord.is_running and coord.wait_idle(0.01)


def test_sync_result_carries_snapshot_change_token(saved):
    snap = _snapshot()
    snap.change_token = "master.db:1:2|master.db-wal:-"
    report = _run(FakeProvider(snap))[0]
    assert report.results[0].change_token == "master.db:1:2|master.db-wal:-"


def test_coordinator_has_pending_reflects_queue():
    runner = _ManualRunner()
    coord = library_sync.SyncCoordinator(runner)
    coord.request([_req("a")], silent=True, done_callback=lambda r, s: None)
    assert coord.has_pending is False
    coord.request([_req("b")], silent=False, done_callback=lambda r, s: None)
    assert coord.has_pending is True
    runner.finish(0)          # follow-up starts
    assert coord.has_pending is False and coord.is_running
    runner.finish(1)
    assert not coord.is_running


def test_coordinator_manual_in_progress_ignores_quiet_runs():
    runner = _ManualRunner()
    coord = library_sync.SyncCoordinator(runner)
    assert coord.manual_in_progress is False
    coord.request([_req("rekordbox")], silent=True, done_callback=lambda r, s: None)
    assert coord.is_running and coord.manual_in_progress is False   # quiet refresh only
    coord.request([_req("serato")], silent=False, done_callback=lambda r, s: None)
    assert coord.manual_in_progress is True                          # manual merged in
    runner.finish(0)
    assert coord.manual_in_progress is True                          # manual follow-up runs
    runner.finish(1)
    assert coord.manual_in_progress is False
