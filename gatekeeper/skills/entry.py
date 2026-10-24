"""trader-entry: has the setup confirmed on a closed bar?"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from gatekeeper.runner import RunResult, SkillRunner
from gatekeeper.skills._base import opt, parse, parse_list, runner_or_default
from gatekeeper.skills.models import EntryStatus


class WatchlistRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: str
    result: EntryStatus | None = None
    error: str | None = None


def _common(args: list[str], setup, level, interval, min_volume_x, or_minutes) -> list[str]:
    opt(args, "--setup", setup)
    opt(args, "--level", level)
    opt(args, "--interval", interval)
    opt(args, "--min-volume-x", min_volume_x)
    opt(args, "--or-minutes", or_minutes)
    return args


def check(
    symbol: str,
    *,
    setup: str = "orb",
    level: float | None = None,
    interval: str = "5m",
    min_volume_x: float | None = None,
    or_minutes: int = 15,
    write: bool = False,
    runner: SkillRunner | None = None,
) -> tuple[EntryStatus | None, RunResult]:
    """Status `empty` means not triggered (waiting, expired, not open yet): read `.status`."""
    args = _common(["check", symbol.upper()], setup, level, interval, min_volume_x, or_minutes)
    opt(args, "--write", write)
    res = runner_or_default(runner).run("entry", args, writes_state=write, timeout=120)
    return parse(EntryStatus, res), res


def watchlist(
    *,
    setup: str = "orb",
    interval: str = "5m",
    min_volume_x: float | None = None,
    runner: SkillRunner | None = None,
) -> tuple[list[WatchlistRow] | None, RunResult]:
    """Every hit in trader/watchlist.json; a row has `result` or `error`."""
    args = _common(["watchlist"], setup, None, interval, min_volume_x, None)
    res = runner_or_default(runner).run("entry", args, timeout=600)
    return parse_list(WatchlistRow, res), res
