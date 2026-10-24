"""New York / IST time and the trading-session phase.

All market logic runs in New York time; India has no daylight saving, so the IST gap
is 9:30 while the US is on EDT and 10:30 while it is on EST.

NYSE holidays and 1:00 p.m. early closes come from the skills' own calendar
(`alerts.py clock`), fetched once per date by `market_day`. Without it (the call
failed, or a year the calendar doesn't know), only weekends are closed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from gatekeeper.skills.models import ClockStatus

NY = ZoneInfo("America/New_York")
IST = ZoneInfo("Asia/Kolkata")

OPEN = time(9, 30)
CLOSE = time(16, 0)

Phase = Literal["closed", "premarket", "opening_range", "entry_window", "late", "after_close"]

PHASE_LABELS: dict[str, str] = {
    "closed": "CLOSED",
    "premarket": "PRE-MARKET",
    "opening_range": "OPENING RANGE",
    "entry_window": "ENTRY WINDOW",
    "late": "NO NEW ENTRIES",
    "after_close": "AFTER CLOSE",
}


@dataclass(frozen=True)
class SessionTimes:
    """The entry window and flat-by time, in New York time (from `trader/config.json`)."""

    no_entries_before: time = time(9, 45)
    no_entries_after: time = time(15, 30)
    flat_by: time = time(15, 55)


def _parse_hhmm(value: object, default: time) -> time:
    if not isinstance(value, str):
        return default
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except ValueError:
        return default


def load_session_times(trader_dir: Path) -> SessionTimes:
    """Session times from the skills' config, falling back to the skills' defaults."""
    d = SessionTimes()
    try:
        cfg = json.loads((trader_dir / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d
    return SessionTimes(
        no_entries_before=_parse_hhmm(cfg.get("no_entries_before"), d.no_entries_before),
        no_entries_after=_parse_hhmm(cfg.get("no_entries_after"), d.no_entries_after),
        flat_by=_parse_hhmm(cfg.get("flat_by"), d.flat_by),
    )


def as_ny(dt: datetime) -> datetime:
    """A naive datetime is taken to be New York time, as the skills' `--now` does."""
    return dt.replace(tzinfo=NY) if dt.tzinfo is None else dt.astimezone(NY)


def now_ny(replay_now: datetime | None = None) -> datetime:
    return as_ny(replay_now) if replay_now is not None else datetime.now(NY)


def to_ist(dt: datetime) -> datetime:
    return as_ny(dt).astimezone(IST)


def fmt_dual(dt: datetime) -> str:
    """'NY 10:15 · IST 19:45'"""
    return f"NY {as_ny(dt):%H:%M} · IST {to_ist(dt):%H:%M}"


def _minus(t: time, delta: timedelta) -> time:
    return (datetime.combine(date.min, t) - delta).time() if delta else t


def session_phase(dt: datetime, times: SessionTimes | None = None, day: ClockStatus | None = None) -> Phase:
    """The phase of the session at `dt`. `day` is that date's `alerts.py clock` status.

    On an early close the close and the entry cutoff move up together, as the skills do
    (a 1:00 p.m. close moves a 15:30 cutoff to 12:30).
    """
    times = times or SessionTimes()
    ny = as_ny(dt)
    if ny.weekday() >= 5 or (day is not None and day.calendar_known and not day.trading_day):
        return "closed"
    close = _parse_hhmm(day.closes, CLOSE) if day is not None else CLOSE
    shift = datetime.combine(date.min, CLOSE) - datetime.combine(date.min, close)
    t = ny.time()
    if t < OPEN:
        return "premarket"
    if t < times.no_entries_before:
        return "opening_range"
    if t < _minus(times.no_entries_after, shift):
        return "entry_window"
    if t < close:
        return "late"
    return "after_close"


def market_day(d: date, runner=None) -> ClockStatus | None:
    """That date's NYSE status (holiday, early close) from the skills' calendar, or None.

    With no runner it uses the live runner and caches per date (the calendar is static);
    a failed lookup is not cached, so it is tried again next time.
    """
    from gatekeeper.skills import alerts

    iso = d.isoformat()
    if runner is None and iso in _DAY_CACHE:
        return _DAY_CACHE[iso]
    status, _ = alerts.clock(f"{iso} 12:00", runner=runner)
    if runner is None and status is not None:
        _DAY_CACHE[iso] = status
    return status


_DAY_CACHE: dict[str, ClockStatus] = {}
