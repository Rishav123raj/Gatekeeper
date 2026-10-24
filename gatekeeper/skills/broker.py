"""trader-broker's ticket tool: tickets, your recorded yes, fills and the flatten ticket.

`ticket.py` never talks to a broker, and nothing here does either. Only `show` has a
JSON mode; the other commands are run for their effect and their files read back.
"""

from __future__ import annotations

from gatekeeper.clock import now_ny
from gatekeeper.runner import RunResult, SkillRunner
from gatekeeper.skills._base import opt, parse_list, read_json, runner_or_default
from gatekeeper.skills.models import BrokerRecord, Order, Portfolio, Ticket


def show(
    *, index: int | None = None, runner: SkillRunner | None = None
) -> tuple[list[Ticket] | None, RunResult]:
    """Status `empty` means no ticket is READY (none passed trader-risk today)."""
    args = ["show"]
    opt(args, "--index", index)
    res = runner_or_default(runner).run("broker", args, timeout=60)
    return parse_list(Ticket, res), res


def records(runner: SkillRunner | None = None, *, day: str | None = None) -> list[BrokerRecord]:
    """Decisions in trader/state/broker.json, optionally only those of one trading day."""
    runner = runner_or_default(runner)
    doc = read_json(runner.trader_dir / "state" / "broker.json", {}) or {}
    rows = [BrokerRecord.model_validate(r) for r in doc.get("orders", [])]
    return [r for r in rows if r.day == day] if day else rows


def portfolio(runner: SkillRunner | None = None) -> Portfolio | None:
    doc = read_json(runner_or_default(runner).trader_dir / "portfolio.json")
    return Portfolio.model_validate(doc) if isinstance(doc, dict) else None


def log(*, all_days: bool = False, runner: SkillRunner | None = None) -> tuple[list[BrokerRecord], RunResult]:
    """Today's decisions (status `empty` when there are none)."""
    runner = runner_or_default(runner)
    args = ["log"]
    opt(args, "--all", all_days)
    res = runner.run("broker", args, json_out=False, timeout=60)
    today = f"{now_ny(runner.replay.now if runner.replay else None):%Y-%m-%d}"
    return records(runner, day=None if all_days else today), res


def approve(index: int, reply: str, *, runner: SkillRunner | None = None) -> RunResult:
    """Records the user's reply word for word. Status `blocked` ("Not recorded") unless it is a real yes."""
    return runner_or_default(runner).run(
        "broker",
        ["approve", "--index", str(index), "--reply", reply],
        json_out=False,
        writes_state=True,
        timeout=60,
    )


def decline(index: int, reply: str | None = None, *, runner: SkillRunner | None = None) -> RunResult:
    args = ["decline", "--index", str(index)]
    opt(args, "--reply", reply)
    return runner_or_default(runner).run("broker", args, json_out=False, writes_state=True, timeout=60)


def result(
    index: int,
    status: str,
    *,
    broker_id: str | None = None,
    note: str | None = None,
    filled_qty: float | None = None,
    filled_price: float | None = None,
    runner: SkillRunner | None = None,
) -> RunResult:
    """What happened after the Allow once / Deny card: placed, denied or failed."""
    if status not in ("placed", "denied", "failed"):
        raise ValueError("status must be placed, denied or failed")
    args = ["result", "--index", str(index), "--status", status]
    opt(args, "--broker-id", broker_id)
    opt(args, "--note", note)
    opt(args, "--filled-qty", filled_qty)
    opt(args, "--filled-price", filled_price)
    return runner_or_default(runner).run("broker", args, json_out=False, writes_state=True, timeout=60)


def fill(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    *,
    date: str | None = None,
    runner: SkillRunner | None = None,
) -> RunResult:
    args = ["fill", "--symbol", symbol.upper(), "--side", side, "--qty", str(qty), "--price", str(price)]
    opt(args, "--date", date)
    return runner_or_default(runner).run("broker", args, json_out=False, writes_state=True, timeout=60)


def flatten(
    symbol: str, qty: float | None = None, *, runner: SkillRunner | None = None
) -> tuple[list[Order] | None, RunResult]:
    """Writes a market sell for the position to trader/orders.json (run trader-risk on it next)."""
    runner = runner_or_default(runner)
    args = ["flatten", "--symbol", symbol.upper()]
    opt(args, "--qty", qty)
    res = runner.run("broker", args, json_out=False, writes_state=True, timeout=60)
    if not res.ok or res.exit_code != 0:
        return None, res
    doc = read_json(runner.trader_dir / "orders.json", {}) or {}
    return parse_list(Order, res, doc.get("orders", [])), res
