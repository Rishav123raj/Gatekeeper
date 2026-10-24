"""trader-budget: how many shares fit the max loss, as one bracket order."""

from __future__ import annotations

from gatekeeper.runner import RunResult, SkillRunner
from gatekeeper.skills._base import opt, parse, runner_or_default
from gatekeeper.skills.models import SizeResult


def size(
    *,
    limit: float | str | None = None,
    budget: float | None = None,
    plan_path: str | None = None,
    write: bool = True,
    runner: SkillRunner | None = None,
) -> tuple[SizeResult | None, RunResult]:
    """Sizes trader/plan.json. `limit="plan"` is a limit order at the plan's entry.

    A refusal (zero shares, reward:risk too low, stale plan...) is status `blocked`, with
    the reason in `.sizing.refusal`; nothing is written then.
    """
    args: list[str] = []
    opt(args, "--limit", limit)
    opt(args, "--budget", budget)
    opt(args, "--plan", plan_path)
    opt(args, "--write", write)
    res = runner_or_default(runner).run("budget", args, writes_state=write, timeout=120)
    return parse(SizeResult, res), res
