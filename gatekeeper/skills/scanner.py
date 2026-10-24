"""trader-scanner: the stock universe, the pre-market scan and the opening-range scan."""

from __future__ import annotations

from gatekeeper.runner import RunResult, SkillRunner
from gatekeeper.skills._base import opt, parse, runner_or_default
from gatekeeper.skills.models import ScanResult, UniverseResult

SCAN_TIMEOUT = 900  # a whole-universe scan takes 2.5 to 4 minutes on the free endpoints


def universe(
    *, write: bool = True, runner: SkillRunner | None = None
) -> tuple[UniverseResult | None, RunResult]:
    args = ["universe"]
    opt(args, "--no-write", not write)
    res = runner_or_default(runner).run("scanner", args, writes_state=write, timeout=300)
    return parse(UniverseResult, res), res


def _scan_args(mode: str, symbols, watchlist, limit, min_price, min_volume, write) -> list[str]:
    args = [mode, "--quiet"]
    if symbols:
        args += ["--symbols", ",".join(s.upper() for s in symbols)]
    opt(args, "--watchlist", watchlist)
    opt(args, "--limit", limit)
    opt(args, "--min-price", min_price)
    opt(args, "--min-volume", min_volume)
    opt(args, "--no-write", not write)
    return args


def daily(
    symbols: list[str] | None = None,
    *,
    watchlist: str | None = None,
    limit: int | None = None,
    min_price: float | None = None,
    min_volume: int | None = None,
    write: bool = True,
    runner: SkillRunner | None = None,
) -> tuple[ScanResult | None, RunResult]:
    args = _scan_args("daily", symbols, watchlist, limit, min_price, min_volume, write)
    res = runner_or_default(runner).run("scanner", args, writes_state=write, timeout=SCAN_TIMEOUT)
    return parse(ScanResult, res), res


def orb(
    symbols: list[str] | None = None,
    *,
    at: str | None = None,
    watchlist: str | None = None,
    max_confirm: int | None = 200,
    or_minutes: int | None = None,
    min_price: float | None = None,
    min_volume: int | None = None,
    write: bool = True,
    runner: SkillRunner | None = None,
) -> tuple[ScanResult | None, RunResult]:
    args = _scan_args("orb", symbols, watchlist, None, min_price, min_volume, write)
    opt(args, "--at", at)
    opt(args, "--max-confirm", max_confirm)
    opt(args, "--or-minutes", or_minutes)
    res = runner_or_default(runner).run("scanner", args, writes_state=write, timeout=SCAN_TIMEOUT)
    return parse(ScanResult, res), res
