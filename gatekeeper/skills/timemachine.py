"""trader-timemachine: 10,000 replays of the rest of the day, plus the real history."""

from __future__ import annotations

from gatekeeper.runner import RunResult, SkillRunner
from gatekeeper.skills._base import opt, parse, read_json, runner_or_default
from gatekeeper.skills.models import TimeMachineResult

DEFAULT_OUT = "trader/timemachine.json"
TM_TIMEOUT = 600


def _finish(res: RunResult, runner: SkillRunner, written: str | None) -> TimeMachineResult | None:
    # The printed JSON leaves out mc.sample_paths; the written file has them.
    full = read_json(runner.cwd / written) if written and res.ok else None
    return parse(TimeMachineResult, res, full if isinstance(full, dict) and "mc" in full else None)


def _sim_args(args: list[str], until, replays, seed, window) -> list[str]:
    opt(args, "--until", until)
    opt(args, "--replays", replays)
    opt(args, "--seed", seed)
    opt(args, "--window", window)
    return args


def run(
    *,
    until: str | None = None,
    replays: int = 10_000,
    seed: int = 19,
    window: int | None = None,
    plan_path: str | None = None,
    write: bool = True,
    runner: SkillRunner | None = None,
) -> tuple[TimeMachineResult | None, RunResult]:
    """Replay trader/plan.json (or `plan_path`). With `write`, saves trader/timemachine.json."""
    runner = runner_or_default(runner)
    args = _sim_args(["run"], until, replays, seed, window)
    opt(args, "--plan", plan_path)
    out = DEFAULT_OUT if write else None
    opt(args, "--write", out)
    res = runner.run("timemachine", args, writes_state=write, timeout=TM_TIMEOUT)
    return _finish(res, runner, out), res


def run_plan(
    symbol: str,
    date: str,
    entry: float,
    stop: float,
    target: float,
    entry_time: str,
    *,
    setup: str = "orb",
    stop_rule: str = "auto",
    until: str | None = None,
    replays: int = 10_000,
    seed: int = 19,
    window: int | None = None,
    out: str | None = None,
    runner: SkillRunner | None = None,
) -> tuple[TimeMachineResult | None, RunResult]:
    """A plan given as values, for comparing variants: never reads or writes trader/plan.json.

    `out` saves the full result (with sample paths) to that path under the working folder.
    """
    runner = runner_or_default(runner)
    args = [
        "run",
        "--symbol",
        symbol.upper(),
        "--date",
        date,
        "--entry",
        str(entry),
        "--stop",
        str(stop),
        "--target",
        str(target),
        "--entry-time",
        entry_time,
        "--setup",
        setup,
        "--stop-rule",
        stop_rule,
        "--plan",
        "nonexistent-plan.json",
    ]
    _sim_args(args, until, replays, seed, window)
    opt(args, "--write", out)
    res = runner.run("timemachine", args, writes_state=out is not None, timeout=TM_TIMEOUT)
    return _finish(res, runner, out), res
