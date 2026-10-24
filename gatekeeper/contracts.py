"""The skills' JSON contracts: what each tool prints on the recorded replay day.

`generate()` runs the documented TSLA chain (and the other tools) in a fresh replay
workspace and returns each tool's raw JSON, normalised so runs compare equal
(timings dropped, the workspace path replaced). `scripts/snapshot_contracts.py`
saves it to tests/contracts/; the contract tests parse those files into the models
and re-run the chain to check the structure has not drifted.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from gatekeeper.replay import ReplayContext, prepare_workspace
from gatekeeper.runner import RunResult, SkillRunner
from gatekeeper.skills import models as m

T_0900 = datetime(2026, 10, 19, 9, 0)
T_1012 = datetime(2026, 10, 19, 10, 12)
T_1015 = datetime(2026, 10, 19, 10, 15)
T_1556 = datetime(2026, 10, 19, 15, 56)

# contract name -> (model, the JSON is a list of that model)
MODELS: dict[str, tuple[type[BaseModel], bool]] = {
    "alerts_clock": (m.ClockStatus, False),
    "scanner_universe": (m.UniverseResult, False),
    "scanner_daily": (m.ScanResult, False),
    "scanner_orb_1015": (m.ScanResult, False),
    "news_tsla": (m.NewsResult, False),
    "entry_tsla_1012": (m.EntryStatus, False),
    "entry_tsla_1015": (m.EntryStatus, False),
    "exit_plan_or_mid_1r": (m.ExitPlan, False),
    "timemachine_run": (m.TimeMachineResult, False),
    "budget_size": (m.SizeResult, False),
    "risk_check_pass": (m.RiskReport, False),
    "risk_check_block_9": (m.RiskReport, False),
    "broker_show": (m.Ticket, True),
    "alerts_quote": (m.QuoteResult, False),
    "alerts_check_1556": (m.AlertCheck, False),
    "analyst_aapl": (m.EarningsFacts, True),
    "pelosi_index": (m.PtrFiling, True),
    "pelosi_new": (m.PtrNew, False),
}

VOLATILE = {"seconds", "checked_at"}


def normalise(data: Any, workspace: Path) -> Any:
    ws = [str(workspace), str(workspace).replace("\\", "/"), str(workspace).replace("\\", "\\\\")]

    def walk(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items() if k not in VOLATILE}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str):
            for w in ws:
                v = v.replace(w, "<workspace>")
        return v

    return walk(data)


def _runner(ctx: ReplayContext, now: datetime) -> SkillRunner:
    return SkillRunner.from_settings(replay=ctx.at(now))


def generate(workspace: Path, skills_dir: Path) -> dict[str, Any]:
    ctx = prepare_workspace(T_1015, workspace, skills_dir)
    r = _runner(ctx, T_1015)
    out: dict[str, Any] = {}

    def take(name: str, res: RunResult, *, ok_only: bool = True) -> None:
        if res.data is None or (ok_only and res.status == "error"):
            raise RuntimeError(f"{name}: {res.tool} gave no JSON ({res.status}: {res.message})")
        out[name] = normalise(res.data, workspace)

    from gatekeeper.skills import (
        alerts,
        analyst,
        broker,
        budget,
        entry,
        exit,
        news,
        pelosi,
        risk,
        scanner,
        timemachine,
    )

    take("alerts_clock", alerts.clock(runner=r)[1])
    take("scanner_universe", scanner.universe(runner=r)[1])
    take("scanner_daily", scanner.daily(runner=_runner(ctx, T_0900), write=False)[1])
    take("scanner_orb_1015", scanner.orb(runner=r)[1])
    take("news_tsla", news.check(["TSLA"], runner=r)[1])
    take("entry_tsla_1012", entry.check("TSLA", runner=_runner(ctx, T_1012))[1])
    take("entry_tsla_1015", entry.check("TSLA", write=True, runner=r)[1])
    take("exit_plan_or_mid_1r", exit.plan(stop="or-mid", target="1R", runner=r)[1])
    take("timemachine_run", timemachine.run(runner=r)[1])
    take("budget_size", budget.size(runner=r)[1])
    take("risk_check_pass", risk.check(runner=r)[1])
    take("broker_show", broker.show(runner=r)[1])

    orders = json.loads((ctx.workspace / "trader" / "orders.json").read_text(encoding="utf-8"))
    orders["orders"][0]["qty"] = "9"
    (ctx.workspace / "trader" / "orders-9.json").write_text(json.dumps(orders), encoding="utf-8")
    take("risk_check_block_9", risk.check(no_write=True, orders_path="trader/orders-9.json", runner=r)[1])

    take("alerts_quote", alerts.quote(["TSLA"], write=False, runner=r)[1])
    alerts.add_from_plan(runner=r)
    take("alerts_check_1556", alerts.check(no_write=True, runner=_runner(ctx, T_1556))[1])
    take("analyst_aapl", analyst.facts(["AAPL"], runner=r)[1])
    take("pelosi_index", pelosi.index("pelosi", runner=r)[1])
    take("pelosi_new", pelosi.new("pelosi", dry_run=True, runner=r)[1])
    return out


def shape(v: Any) -> Any:
    """The structure of a JSON value: keys and types, with lists reduced to their first item."""
    if isinstance(v, dict):
        return {k: shape(x) for k, x in v.items()}
    if isinstance(v, list):
        return [shape(v[0])] if v else []
    if isinstance(v, bool) or v is None:
        return type(v).__name__
    if isinstance(v, int | float):
        return "number"
    return type(v).__name__
