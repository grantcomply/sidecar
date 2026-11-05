"""Tests for the tag-energy memo."""

from __future__ import annotations

import os
import threading

from source.providers.rekordbox.energy_cache import TagEnergyCache


def _file(tmp_path, name="synthetic.mp3", data=b"x"):
    f = tmp_path / name
    f.write_bytes(data)
    return str(f)


def test_second_call_hits_cache(tmp_path):
    cache, calls = TagEnergyCache(), []
    path = _file(tmp_path)

    def reader(p):
        calls.append(p)
        return 6

    assert cache.get(path, reader) == 6
    assert cache.get(path, reader) == 6
    assert len(calls) == 1
    assert (cache.reads, cache.hits) == (1, 1)


def test_mtime_change_rereads(tmp_path):
    cache, values = TagEnergyCache(), iter([3, 7])
    path = _file(tmp_path)
    cache.get(path, lambda _p: next(values))
    os.utime(path, ns=(5_000_000_000, 5_000_000_000))

    assert cache.get(path, lambda _p: next(values)) == 7


def test_stat_error_returns_zero_and_is_not_cached(tmp_path):
    cache, calls = TagEnergyCache(), []

    assert cache.get(str(tmp_path / "missing.mp3"), lambda p: calls.append(p) or 5) == 0
    assert calls == []
    assert cache.reads == 0


def test_clear_forgets_values(tmp_path):
    cache, calls = TagEnergyCache(), []
    path = _file(tmp_path)
    cache.get(path, lambda p: calls.append(p) or 4)
    cache.clear()
    cache.get(path, lambda p: calls.append(p) or 4)
    assert len(calls) == 2


def test_concurrent_get_is_safe(tmp_path):
    cache = TagEnergyCache()
    paths = [_file(tmp_path, f"t{i}.mp3", bytes([i])) for i in range(20)]
    errors: list[BaseException] = []

    def worker():
        try:
            for p in paths * 5:
                assert cache.get(p, lambda _p: 5) == 5
        except BaseException as e:  # noqa: BLE001 - surface any thread failure
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert errors == []
    assert cache.reads + cache.hits == 8 * 5 * 20
