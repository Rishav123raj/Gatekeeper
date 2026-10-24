"""The Trade Lab's logic, kept out of the page so it can be tested.

- `preview`: the stop, target, risk and reward:risk a plan would get, computed locally for the
  page's live preview only. The plan itself always comes from `exit.py`, which has the final say
  (and refuses bad plans with a reason).
- `compare`: several stop / target variants, each planned by `exit.py` without writing
  `trader/plan.json`, then replayed by the Time Machine as explicit values with the same seed.
- `file_hash`: notices when `trader/plan.json` changed outside the dashboard (Claude chat).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path

from gatekeeper.runner import SkillRunner
from gatekeeper.skills import exit, timemachine
from gatekeeper.skills.models import ExitPlan, TimeMachineResult

STOP_RULES = ("or-mid", "or-low", "pct", "atr", "price")
TARGET_RULES = ("1R", "1.5R", "2R", "3R", "price")
# exit.py's stop_rule -> the Time Machine's --stop-rule (its history re-runs the same rule)
TM_STOP_RULE = {"or_mid": "or_mid", "or_low": "or_low", "pct": "pct"}

CENT = Decimal("0.01")


def stop_arg(rule: str, value: float | None = None) -> str:
    """exit.py's --stop: or-mid, or-low, pct:X, atr:K or price:X."""
    if rule in ("or-mid", "or-low"):
        return rule
    if rule in ("pct", "atr", "price"):
        if value is None:
            raise ValueError(f"the {rule} stop needs a value")
        return f"{rule}:{value:g}"
    raise ValueError(f"unknown stop rule {rule!r}")


def target_arg(rule: str, value: float | None = None) -> str:
    """exit.py's --target: 1R, 1.5R, 2R, 3R or price:X."""
    if rule == "price":
        if value is None:
            raise ValueError("a price target needs a value")
        return f"price:{value:g}"
    if rule in TARGET_RULES:
        return rule
    raise ValueError(f"unknown target rule {rule!r}")


@dataclass
class Preview:
    stop: float | None
    target: float | None
    risk: float | None
    reward_risk: float | None
    note: str = ""


def _down(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_FLOOR)


def _half_up(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def preview(
    entry: float,
    or_high: float | None,
    or_low: float | None,
    stop_rule: str,
    stop_value: float | None = None,
    target_rule: str = "2R",
    target_value: float | None = None,
) -> Preview:
    """Roughly what exit.py will plan (stop rounded down to the cent, target half up). Preview only."""
    e = Decimal(str(entry))
    stop: Decimal | None = None
    if stop_rule == "or-mid" and or_high is not None and or_low is not None:
        stop = _down((Decimal(str(or_high)) + Decimal(str(or_low))) / 2)
    elif stop_rule == "or-low" and or_low is not None:
        stop = _down(Decimal(str(or_low)))
    elif stop_rule == "pct" and stop_value:
        stop = _down(e * (1 - Decimal(str(stop_value)) / 100))
    elif stop_rule == "price" and stop_value:
        stop = _down(Decimal(str(stop_value)))
    if stop is None:
        note = "the ATR stop is computed by exit.py from the session's bars" if stop_rule == "atr" else ""
        return Preview(None, None, None, None, note or "not enough data for a preview")
    risk = e - stop
    if risk <= 0:
        return Preview(float(stop), None, float(risk), None, "the stop is at or above the entry")
    if target_rule == "price":
        if not target_value:
            return Preview(float(stop), None, float(risk), None, "enter a target price")
        target = _half_up(Decimal(str(target_value)))
    else:
        target = _half_up(e + Decimal(target_rule.rstrip("R")) * risk)
    rr = (target - e) / risk
    return Preview(float(stop), float(target), float(risk), round(float(rr), 2))


@dataclass
class Variant:
    stop_rule: str
    target_rule: str
    stop_value: float | None = None
    target_value: float | None = None

    @property
    def label(self) -> str:
        s = stop_arg(self.stop_rule, self.stop_value)
        t = target_arg(self.target_rule, self.target_value)
        return f"{s} / {t}"


@dataclass
class VariantResult:
    variant: Variant
    plan: ExitPlan | None
    tm: TimeMachineResult | None
    error: str = ""

    def row(self) -> dict:
        p, tm = self.plan, self.tm
        row = {"Plan": self.variant.label}
        if p is None or tm is None:
            return {**row, "Result": self.error or "no result"}
        h = tm.history
        return {
            **row,
            "Stop": p.stop,
            "Target": p.target,
            "Risk / share": p.risk_per_share,
            "R:R": p.reward_risk,
            "Target first %": round(100 * tm.mc.p_target, 1),
            "Stop first %": round(100 * tm.mc.p_stop, 1),
            "Neither %": round(100 * tm.mc.p_neither, 1),
            "Avg R": tm.mc.avg_R,
            "History": f"{h.triggered} fired: {h.target} target / {h.stop} stop" if h else "",
            "Result": tm.verdict,
        }


def compare(
    variants: list[Variant],
    runner: SkillRunner,
    *,
    until: str | None = None,
    seed: int = 19,
    replays: int = 10_000,
    entry: float | None = None,
) -> list[VariantResult]:
    """Each variant planned (no trader/plan.json written) and replayed with the same seed."""
    out = []
    for v in variants:
        try:
            stop, target = stop_arg(v.stop_rule, v.stop_value), target_arg(v.target_rule, v.target_value)
        except ValueError as e:
            out.append(VariantResult(v, None, None, str(e)))
            continue
        plan, res = exit.plan(stop=stop, target=target, entry=entry, write=False, runner=runner)
        if plan is None:
            out.append(VariantResult(v, None, None, res.message or res.status))
            continue
        tm, res = timemachine.run_plan(
            plan.symbol,
            plan.date,
            plan.entry,
            plan.stop,
            plan.target,
            plan.entry_time or "",
            setup=plan.setup or "orb",
            stop_rule=TM_STOP_RULE.get(plan.stop_rule or "", "auto"),
            until=until,
            seed=seed,
            replays=replays,
            runner=runner,
        )
        out.append(VariantResult(v, plan, tm, "" if tm else (res.message or res.status)))
    return out


def file_hash(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
