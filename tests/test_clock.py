from datetime import UTC, datetime, time

import pytest

from gatekeeper.clock import (
    NY,
    SessionTimes,
    fmt_dual,
    load_session_times,
    now_ny,
    session_phase,
    to_ist,
)


@pytest.mark.parametrize(
    ("ny", "ist"),
    [
        (datetime(2026, 10, 19, 10, 15), "19:45"),  # US on EDT: +9:30
        (datetime(2026, 11, 2, 10, 15), "20:45"),  # after the Nov 1 change, EST: +10:30
        (datetime(2027, 3, 15, 10, 15), "19:45"),  # after the Mar 14 change, EDT again
    ],
)
def test_ny_to_ist_across_daylight_saving(ny, ist):
    assert f"{to_ist(ny):%H:%M}" == ist


def test_fmt_dual():
    assert fmt_dual(datetime(2026, 10, 19, 10, 15)) == "NY 10:15 · IST 19:45"


def test_aware_datetime_is_converted_not_relabelled():
    utc = datetime(2026, 10, 19, 14, 15, tzinfo=UTC)  # 10:15 NY
    assert f"{to_ist(utc):%H:%M}" == "19:45"
    assert session_phase(utc) == "entry_window"


def test_now_ny_replay():
    assert now_ny(datetime(2026, 10, 19, 10, 15)) == datetime(2026, 10, 19, 10, 15, tzinfo=NY)


def test_now_ny_live_is_aware():
    assert now_ny().tzinfo is NY


@pytest.mark.parametrize(
    ("hhmm", "phase"),
    [
        ("08:00", "premarket"),
        ("09:30", "opening_range"),
        ("09:44", "opening_range"),
        ("09:45", "entry_window"),
        ("15:29", "entry_window"),
        ("15:30", "late"),
        ("15:59", "late"),
        ("16:00", "after_close"),
    ],
)
def test_session_phase_on_a_weekday(hhmm, phase):
    h, m = map(int, hhmm.split(":"))
    assert session_phase(datetime(2026, 10, 19, h, m)) == phase  # Monday


def test_saturday_is_closed():
    assert session_phase(datetime(2026, 10, 24, 10, 15)) == "closed"


def test_session_phase_uses_config_times():
    times = SessionTimes(no_entries_before=time(9, 45), no_entries_after=time(11, 0), flat_by=time(12, 0))
    assert session_phase(datetime(2026, 10, 19, 11, 30), times) == "late"


def test_load_session_times(tmp_path):
    (tmp_path / "config.json").write_text(
        '{"no_entries_before": "10:00", "no_entries_after": "11:00", "flat_by": "bad"}', encoding="utf-8"
    )
    times = load_session_times(tmp_path)
    assert times.no_entries_before == time(10, 0)
    assert times.no_entries_after == time(11, 0)
    assert times.flat_by == time(15, 55)  # unparseable value falls back to the default


def test_load_session_times_without_config(tmp_path):
    assert load_session_times(tmp_path) == SessionTimes()
