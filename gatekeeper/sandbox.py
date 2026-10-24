"""'What if' sizing and risk checks on a throwaway copy of trader/.

The live trader/ folder is only ever read (copied). The copy gets a hypothetical price in
its prices.json and / or a different share count in its orders.json, then size.py and
check.py run there (check.py with --no-write). The copy is deleted afterwards.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from gatekeeper.clock import as_ny
from gatekeeper.replay import ReplayContext
from gatekeeper.runner import LOCK_NAME, SkillRunner
from gatekeeper.settings import Settings
from gatekeeper.skills import budget, risk
from gatekeeper.skills.models import RiskReport, SizeResult


@dataclass
class WhatIf:
    price: float | None
    qty: int | None
    size: SizeResult | None
    risk: RiskReport | None
    size_message: str = ""
    risk_message: str = ""


def _with_price(sandbox: Path, symbol: str, price: float, now: datetime) -> None:
    path = sandbox / "prices.json"
    doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    stamp = as_ny(now).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc.setdefault("prices", {})[symbol] = price
    doc.setdefault("detail", {})[symbol] = {"time": stamp, "source": "what-if"}
    doc["as_of"] = stamp
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _with_qty(sandbox: Path, symbol: str, qty: int) -> bool:
    path = sandbox / "orders.json"
    if not path.exists():
        return False
    doc = json.loads(path.read_text(encoding="utf-8"))
    orders = doc.get("orders", doc) if isinstance(doc, dict) else doc
    changed = False
    for o in orders:
        if o.get("symbol") == symbol and "qty" in o:
            o["qty"] = str(qty)
            changed = True
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return changed


def what_if(
    trader_dir: Path,
    settings: Settings,
    now: datetime,
    symbol: str,
    *,
    price: float | None = None,
    qty: int | None = None,
    replay_fixtures: Path | None = None,
) -> WhatIf:
    """Size and check `symbol` as if the price were `price` and / or the order were `qty` shares."""
    with tempfile.TemporaryDirectory(prefix="gatekeeper-whatif-") as tmp:
        work = Path(tmp)
        shutil.copytree(trader_dir, work / "trader", ignore=shutil.ignore_patterns(LOCK_NAME))
        if price is not None:
            _with_price(work / "trader", symbol, price, now)
        if qty is not None:
            _with_qty(work / "trader", symbol, qty)
        if replay_fixtures is not None:  # replay: the skills get the replay clock
            runner = SkillRunner.from_settings(
                settings, replay=ReplayContext(as_ny(now).replace(tzinfo=None), work, replay_fixtures)
            )
        else:
            runner = SkillRunner(
                settings.skills_path,
                work,
                env={"SEC_USER_AGENT": settings.sec_user_agent} if settings.sec_user_agent else {},
            )
        size, sres = budget.size(write=False, runner=runner)
        report, rres = risk.check(no_write=True, runner=runner)
    return WhatIf(price, qty, size, report, "" if size else sres.message, "" if report else rres.message)
