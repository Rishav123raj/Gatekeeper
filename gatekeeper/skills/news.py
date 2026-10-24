"""trader-news: headlines, 8-K filings and today's move per ticker."""

from __future__ import annotations

from gatekeeper.runner import RunResult, SkillRunner
from gatekeeper.skills._base import opt, parse, runner_or_default
from gatekeeper.skills.models import NewsResult


def check(
    tickers: list[str] | None = None,
    *,
    hours: float | None = None,
    forms: str | None = None,
    no_sec: bool = False,
    no_moves: bool = False,
    show_all: bool = False,
    dry_run: bool = False,
    runner: SkillRunner | None = None,
) -> tuple[NewsResult | None, RunResult]:
    """Status `empty` means nothing new since the last check (the state file remembers what was shown)."""
    args: list[str] = []
    if tickers:
        args += ["--tickers", *[t.upper() for t in tickers]]
    opt(args, "--hours", hours)
    opt(args, "--forms", forms)
    opt(args, "--no-sec", no_sec)
    opt(args, "--no-moves", no_moves)
    opt(args, "--all", show_all)
    opt(args, "--dry-run", dry_run)
    res = runner_or_default(runner).run("news", args, writes_state=not dry_run, timeout=300)
    return parse(NewsResult, res), res
