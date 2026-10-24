"""trader-exit: the stop, the target and the flat-by time, set before the entry."""

from __future__ import annotations

from gatekeeper.runner import RunResult, SkillRunner
from gatekeeper.skills._base import opt, parse, runner_or_default
from gatekeeper.skills.models import ExitPlan


def plan(
    *,
    stop: str | None = "or-mid",
    target: str | None = "2R",
    flat_by: str | None = None,
    entry: float | None = None,
    symbol: str | None = None,
    or_high: float | None = None,
    or_low: float | None = None,
    setup: str | None = None,
    from_path: str | None = None,
    write: bool = True,
    runner: SkillRunner | None = None,
) -> tuple[ExitPlan | None, RunResult]:
    """From trader/entry.json by default. A refusal is status `error` with the reason in `.message`."""
    args = ["plan"]
    opt(args, "--from", from_path)
    opt(args, "--symbol", symbol)
    opt(args, "--entry", entry)
    opt(args, "--or-high", or_high)
    opt(args, "--or-low", or_low)
    opt(args, "--setup", setup)
    opt(args, "--stop", stop)
    opt(args, "--target", target)
    opt(args, "--flat-by", flat_by)
    opt(args, "--write", write)
    res = runner_or_default(runner).run("exit", args, writes_state=write, timeout=120)
    return parse(ExitPlan, res), res


def show(*, runner: SkillRunner | None = None) -> tuple[ExitPlan | None, RunResult]:
    res = runner_or_default(runner).run("exit", ["show"], timeout=60)
    return parse(ExitPlan, res), res
