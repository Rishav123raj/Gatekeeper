"""trader-alerts: the NYSE clock, delayed quotes and price / time alerts.

`add`, `list` and `reset` have no JSON mode; their results are read back from
trader/alerts.json and trader/state/alerts.json.
"""

from __future__ import annotations

from datetime import datetime

from gatekeeper.runner import RunResult, SkillRunner
from gatekeeper.skills._base import opt, parse, read_json, runner_or_default
from gatekeeper.skills.models import AlertCheck, AlertRule, ClockStatus, QuoteResult

RULE_KINDS = ("above", "below", "stop", "target", "pct")


def clock(
    now: datetime | str | None = None, *, runner: SkillRunner | None = None
) -> tuple[ClockStatus | None, RunResult]:
    """Status `empty` when the market is closed at that moment (read `.reason`)."""
    args = ["clock"]
    if now is not None:
        opt(args, "--now", now if isinstance(now, str) else f"{now:%Y-%m-%d %H:%M}")
    res = runner_or_default(runner).run("alerts", args, timeout=30)
    return parse(ClockStatus, res), res


def quote(
    symbols: list[str] | None = None,
    *,
    holdings: bool = False,
    write: bool = True,
    source: str | None = None,
    runner: SkillRunner | None = None,
) -> tuple[QuoteResult | None, RunResult]:
    """Delayed quotes; with `write`, merged into trader/prices.json for sizing and the risk check."""
    args = ["quote", *[s.upper() for s in symbols or []]]
    opt(args, "--holdings", holdings)
    opt(args, "--write", write)
    opt(args, "--source", source)
    res = runner_or_default(runner).run("alerts", args, writes_state=write, timeout=120)
    return parse(QuoteResult, res), res


def check(
    *, no_write: bool = False, runner: SkillRunner | None = None
) -> tuple[AlertCheck | None, RunResult]:
    """Rings each rule that hit, once. Status `empty` when nothing rang."""
    args = ["check"]
    opt(args, "--no-write", no_write)
    res = runner_or_default(runner).run("alerts", args, writes_state=not no_write, timeout=120)
    return parse(AlertCheck, res), res


def list_rules(runner: SkillRunner | None = None) -> list[AlertRule]:
    runner = runner_or_default(runner)
    rules = (read_json(runner.trader_dir / "alerts.json", {}) or {}).get("rules", [])
    rung = (read_json(runner.trader_dir / "state" / "alerts.json", {}) or {}).get("rung", {})
    return [AlertRule.model_validate({**r, "rang": rung.get(r.get("id"))}) for r in rules]


def _add(args: list[str], runner: SkillRunner | None) -> tuple[list[AlertRule], RunResult]:
    runner = runner_or_default(runner)
    res = runner.run("alerts", ["add", *args], json_out=False, writes_state=True, timeout=30)
    return list_rules(runner), res


def add_from_plan(*, runner: SkillRunner | None = None) -> tuple[list[AlertRule], RunResult]:
    """The stop, the target and "flat by close" from trader/plan.json, for the plan's day."""
    return _add(["--from-plan"], runner)


def add_rule(
    kind: str,
    value: float | str | None = None,
    *,
    symbol: str | None = None,
    label: str | None = None,
    before_close: bool = False,
    date: str | None = None,
    direction: str | None = None,
    rearm: bool = False,
    note: str | None = None,
    rule_id: str | None = None,
    runner: SkillRunner | None = None,
) -> tuple[list[AlertRule], RunResult]:
    """kind: above | below | stop | target | pct (value = a price or percent), at (value = "HH:MM"),
    or opening_bell (no value)."""
    if kind in RULE_KINDS:
        args = [f"--{kind}", str(value)]
    elif kind == "at":
        args = ["--at", str(value)]
    elif kind == "opening_bell":
        args = ["--opening-bell"]
    else:
        raise ValueError(f"unknown alert kind {kind!r}")
    opt(args, "--symbol", symbol.upper() if symbol else None)
    opt(args, "--label", label)
    opt(args, "--before-close", before_close)
    opt(args, "--date", date)
    opt(args, "--direction", direction)
    opt(args, "--rearm", rearm)
    opt(args, "--note", note)
    opt(args, "--id", rule_id)
    return _add(args, runner)


def reset(rule_id: str, *, runner: SkillRunner | None = None) -> RunResult:
    return runner_or_default(runner).run("alerts", ["reset", rule_id], json_out=False, writes_state=True,
                                         timeout=30)
