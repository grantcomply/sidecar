"""Tests for the date-range conversion helper (T3.0)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from source.services.dates import date_range_to_epoch

# A fixed "now" for deterministic preset windows: 2026-05-30 12:00:00 UTC.
NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)


def _epoch(y: int, m: int, d: int) -> float:
    return datetime(y, m, d, tzinfo=timezone.utc).timestamp()


def test_any_time_preset_no_filter():
    assert date_range_to_epoch("any time", now=NOW) == (None, None)


def test_unknown_preset_no_filter():
    assert date_range_to_epoch("last decade", now=NOW) == (None, None)


def test_no_args_no_filter():
    assert date_range_to_epoch(None, None, None) == (None, None)


def test_last_month_preset_30_days():
    date_from, date_to = date_range_to_epoch("last month", now=NOW)
    assert date_to is None
    assert date_from == pytest.approx(NOW.timestamp() - 30 * 86400)


def test_last_3_months_preset_90_days():
    date_from, date_to = date_range_to_epoch("last 3 months", now=NOW)
    assert date_to is None
    assert date_from == pytest.approx(NOW.timestamp() - 90 * 86400)


def test_last_6_months_preset_180_days():
    date_from, date_to = date_range_to_epoch("last 6 months", now=NOW)
    assert date_to is None
    assert date_from == pytest.approx(NOW.timestamp() - 180 * 86400)


def test_this_year_preset_starts_jan_1():
    date_from, date_to = date_range_to_epoch("this year", now=NOW)
    assert date_to is None
    assert date_from == pytest.approx(_epoch(2026, 1, 1))


def test_preset_is_case_insensitive():
    assert date_range_to_epoch("This Year", now=NOW) == date_range_to_epoch("this year", now=NOW)


def test_from_only_open_upper_bound():
    date_from, date_to = date_range_to_epoch(from_str="2026-03-01")
    assert date_from == pytest.approx(_epoch(2026, 3, 1))
    assert date_to is None


def test_from_and_to_bound_a_window():
    date_from, date_to = date_range_to_epoch(from_str="2026-01-01", to_str="2026-03-01")
    assert date_from == pytest.approx(_epoch(2026, 1, 1))
    assert date_to == pytest.approx(_epoch(2026, 3, 1))


def test_malformed_from_raises_value_error():
    with pytest.raises(ValueError):
        date_range_to_epoch(from_str="01/03/2026")


def test_malformed_to_raises_value_error():
    with pytest.raises(ValueError):
        date_range_to_epoch(from_str="2026-01-01", to_str="not-a-date")


def test_year_boundary_wrap_this_year_at_dec_31():
    dec_31 = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
    date_from, date_to = date_range_to_epoch("this year", now=dec_31)
    assert date_from == pytest.approx(_epoch(2026, 1, 1))
    assert date_to is None


def test_year_boundary_wrap_this_year_at_jan_1():
    jan_1 = datetime(2027, 1, 1, 0, 1, tzinfo=timezone.utc)
    date_from, date_to = date_range_to_epoch("this year", now=jan_1)
    assert date_from == pytest.approx(_epoch(2027, 1, 1))
    assert date_to is None
