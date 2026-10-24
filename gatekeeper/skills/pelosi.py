"""trader-pelosi: Congress members' public trade disclosures (House PTRs)."""

from __future__ import annotations

from gatekeeper.runner import RunResult, SkillRunner
from gatekeeper.skills._base import opt, parse, parse_list, runner_or_default
from gatekeeper.skills.models import PtrFiling, PtrNew


def _members(args: list[str], member: str | list[str] | None) -> list[str]:
    for m in [member] if isinstance(member, str) else member or []:
        args += ["--member", m]
    return args


def index(
    member: str | list[str] | None = None,
    *,
    since: str | None = None,
    year: int | None = None,
    filing_type: str | None = None,
    limit: int | None = None,
    runner: SkillRunner | None = None,
) -> tuple[list[PtrFiling] | None, RunResult]:
    """Filings in the House Clerk's yearly index (PTRs by default). Status `empty` when none match."""
    args = _members(["index"], member)
    opt(args, "--since", since)
    opt(args, "--year", year)
    opt(args, "--type", filing_type)
    opt(args, "--limit", limit)
    res = runner_or_default(runner).run("pelosi", args, timeout=180)
    return parse_list(PtrFiling, res), res


def new(
    member: str | list[str] | None = None,
    *,
    read: bool = False,
    dry_run: bool = False,
    tickers: list[str] | None = None,
    year: int | None = None,
    runner: SkillRunner | None = None,
) -> tuple[PtrNew | None, RunResult]:
    """PTRs not seen at the last check (remembered in trader/state/pelosi.json). `read` needs pdftotext."""
    args = _members(["new"], member)
    opt(args, "--read", read)
    opt(args, "--dry-run", dry_run)
    opt(args, "--year", year)
    if tickers:
        args += ["--tickers", *[t.upper() for t in tickers]]
    res = runner_or_default(runner).run("pelosi", args, writes_state=not dry_run, timeout=600)
    return parse(PtrNew, res), res
