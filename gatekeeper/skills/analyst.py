"""trader-analyst: reported numbers from SEC EDGAR, quarter by quarter."""

from __future__ import annotations

from gatekeeper.runner import RunResult, SkillRunner
from gatekeeper.skills._base import opt, parse_list, runner_or_default
from gatekeeper.skills.models import EarningsFacts


def facts(
    tickers: list[str],
    *,
    quarters: int = 4,
    metrics_path: str | None = None,
    no_filings: bool = False,
    runner: SkillRunner | None = None,
) -> tuple[list[EarningsFacts] | None, RunResult]:
    """Needs SEC_USER_AGENT when live. Status `partial` when some tickers failed (named in stderr)."""
    args = [t.upper() for t in tickers]
    opt(args, "--quarters", quarters)
    opt(args, "--metrics", metrics_path)
    opt(args, "--no-filings", no_filings)
    res = runner_or_default(runner).run("analyst", args, writes_state=metrics_path is not None, timeout=300)
    return parse_list(EarningsFacts, res), res
