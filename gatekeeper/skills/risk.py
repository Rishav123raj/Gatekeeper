"""trader-risk: PASS or BLOCK for each proposed order, against your limits."""

from __future__ import annotations

from gatekeeper.runner import RunResult, SkillRunner
from gatekeeper.skills._base import opt, parse, runner_or_default
from gatekeeper.skills.models import RiskReport


def check(
    *,
    no_write: bool = False,
    orders_path: str | None = None,
    runner: SkillRunner | None = None,
) -> tuple[RiskReport | None, RunResult]:
    """Checks trader/orders.json. Status `blocked` when any order is blocked.

    Without `no_write`, records the verdicts in trader/state/risk.json, which is what
    trader-broker reads to mark a ticket READY.
    """
    args: list[str] = []
    opt(args, "--orders", orders_path)
    opt(args, "--no-write", no_write)
    res = runner_or_default(runner).run("risk", args, writes_state=not no_write, timeout=120)
    return parse(RiskReport, res), res
