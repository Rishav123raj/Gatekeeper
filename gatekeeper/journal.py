"""The journal: what each plan actually did, and whether following Gatekeeper helped.

`simulate_outcome` plays a plan forward on the day's real 5-minute bars with the Time
Machine's rules (stop checked first, a bar touching both counts as the stop, otherwise out
at the flat-by time), so a skipped trade still gets an honest result. The rest is
arithmetic in R: 1R is the plan's risk a share.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time

import pandas as pd

from gatekeeper.skills.models import ExitPlan

MIN_TRADES = 40  # below this, calibration and the readiness card say "not enough trades yet"
ENTRY_BUCKETS = [
    (time(9, 45), time(10, 30), "09:45–10:30"),
    (time(10, 30), time(12, 0), "10:30–12:00"),
    (time(12, 0), time(14, 0), "12:00–14:00"),
    (time(14, 0), time(16, 0), "14:00–close"),
]
VERDICT_ORDER = [
    "strong_target",
    "lean_target",
    "coin_flip",
    "break_even",
    "lean_stop",
    "strong_stop",
    "none",
]


@dataclass
class Outcome:
    r: float | None
    exit_reason: str  # target | stop | flat | data_end | no_data
    exit_price: float | None = None
    exit_time: str | None = None  # "HH:MM" New York, the bar's start


def _entry_time(plan: ExitPlan) -> time:
    raw = (plan.entry_time or "").strip()
    for fmt in ("%I:%M %p", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            pass
    raise ValueError(f"the plan has no usable entry time ({plan.entry_time!r})")


def simulate_outcome(plan: ExitPlan, bars: pd.DataFrame, flat_by: time | None = None) -> Outcome:
    """The plan played forward from its entry on `bars` (ts in New York, open/high/low/close)."""
    risk = plan.risk_per_share
    if not risk or risk <= 0:
        return Outcome(None, "no_data")
    start = _entry_time(plan)  # the trigger bar closed at this time; the trade starts with the next bar
    flat = flat_by or (datetime.strptime(plan.flat_by, "%H:%M").time() if plan.flat_by else time(15, 55))
    on_grid = bars[[t.minute % 5 == 0 and t.second == 0 for t in bars["ts"]]] if len(bars) else bars
    after = on_grid[[start <= t.time() < flat for t in on_grid["ts"]]] if len(on_grid) else on_grid
    if after.empty:
        return Outcome(None, "no_data")
    target_r = (plan.target - plan.entry) / risk
    for _, b in after.iterrows():
        at = f"{b['ts']:%H:%M}"
        if b["low"] <= plan.stop:  # checked first; a bar touching both counts as the stop
            return Outcome(-1.0, "stop", plan.stop, at)
        if b["high"] >= plan.target:
            return Outcome(round(target_r, 3), "target", plan.target, at)
    last = after.iloc[-1]
    end_of_bar = (datetime.combine(date.min, last["ts"].time()) + pd.Timedelta(minutes=5)).time()
    reason = "flat" if end_of_bar >= flat else "data_end"  # the bars stopped before the flat-by time
    px = float(last["close"])
    return Outcome(round((px - plan.entry) / risk, 3), reason, round(px, 2), f"{last['ts']:%H:%M}")


def real_r(plan: ExitPlan, entry_fill: float, exit_fill: float) -> tuple[float, str]:
    """R from recorded fills, and which exit it looks like."""
    r = round((exit_fill - entry_fill) / plan.risk_per_share, 3)
    if exit_fill <= plan.stop + 0.01:
        return r, "stop"
    if exit_fill >= plan.target - 0.01:
        return r, "target"
    return r, "flat"


# --- statistics ------------------------------------------------------------------------------


@dataclass
class Trade:
    """One journal row, flattened for the statistics."""

    day: str
    symbol: str
    r: float | None
    simulated: bool
    taken: bool
    followed_rules: bool | None = None
    verdict: str | None = None  # the Time Machine's verdict category for the plan
    setup: str | None = None
    entry_time: str | None = None


def _done(trades: list[Trade]) -> list[Trade]:
    return [t for t in trades if t.r is not None]


def stats(trades: list[Trade]) -> dict:
    """Win rate, average win / loss, expectancy, profit factor, max drawdown, losing streak, adherence."""
    ts = _done(trades)
    rs = [t.r for t in ts]
    wins, losses = [r for r in rs if r > 0], [r for r in rs if r < 0]
    curve, peak, dd = 0.0, 0.0, 0.0
    for r in rs:
        curve += r
        peak = max(peak, curve)
        dd = min(dd, curve - peak)
    streak = best = 0
    for r in rs:
        streak = streak + 1 if r < 0 else 0
        best = max(best, streak)
    judged = [t.followed_rules for t in trades if t.followed_rules is not None]
    return {
        "n": len(rs),
        "win_rate": round(len(wins) / len(rs), 3) if rs else None,
        "avg_win_r": round(sum(wins) / len(wins), 3) if wins else None,
        "avg_loss_r": round(sum(losses) / len(losses), 3) if losses else None,
        "expectancy_r": round(sum(rs) / len(rs), 3) if rs else None,
        "total_r": round(sum(rs), 3),
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses else None,
        "max_dd_r": round(dd, 3),
        "longest_losing_streak": best,
        "adherence_rate": round(sum(judged) / len(judged), 3) if judged else None,
    }


def calibration(trades: list[Trade]) -> list[dict]:
    """Per Time Machine verdict: how many trades, how often they won, their average R."""
    groups: dict[str, list[float]] = defaultdict(list)
    for t in _done(trades):
        groups[t.verdict or "none"].append(t.r)
    out = []
    for v in sorted(groups, key=lambda k: VERDICT_ORDER.index(k) if k in VERDICT_ORDER else 99):
        rs = groups[v]
        out.append(
            {
                "verdict": v,
                "n": len(rs),
                "win_rate": round(sum(r > 0 for r in rs) / len(rs), 3),
                "avg_r": round(sum(rs) / len(rs), 3),
            }
        )
    return out


def entry_bucket(entry_time: str | None) -> str:
    if not entry_time:
        return "unknown"
    try:
        t = _entry_time(ExitPlan.model_construct(entry_time=entry_time))
    except ValueError:
        return "unknown"
    return next((name for a, b, name in ENTRY_BUCKETS if a <= t < b), "other")


def breakdown(trades: list[Trade], by: str) -> list[dict]:
    """Results grouped by setup, entry-time bucket or weekday."""

    def key(t: Trade) -> str:
        if by == "setup":
            return t.setup or "unknown"
        if by == "entry_bucket":
            return entry_bucket(t.entry_time)
        if by == "weekday":
            return f"{date.fromisoformat(t.day):%a}"
        raise ValueError(f"unknown breakdown {by!r}")

    groups: dict[str, list[float]] = defaultdict(list)
    for t in _done(trades):
        groups[key(t)].append(t.r)
    return [
        {
            by: k,
            "n": len(v),
            "win_rate": round(sum(r > 0 for r in v) / len(v), 3),
            "expectancy_r": round(sum(v) / len(v), 3),
        }
        for k, v in sorted(groups.items())
    ]


def readiness_card(
    trades: list[Trade], min_trades: int = MIN_TRADES, min_adherence: float = 0.95
) -> list[dict]:
    """The paper → live checklist (display only): enough trades, positive expectancy, rules followed."""
    taken = [t for t in trades if t.taken and not t.simulated]
    s = stats(taken)
    adherence = stats(trades)["adherence_rate"]
    return [
        {"check": f"{min_trades}+ trades taken (paper)", "ok": s["n"] >= min_trades, "value": s["n"]},
        {
            "check": "expectancy above 0R",
            "ok": (s["expectancy_r"] or 0) > 0 and s["n"] > 0,
            "value": s["expectancy_r"],
        },
        {
            "check": f"rules followed in {min_adherence:.0%}+ of decisions",
            "ok": adherence is not None and adherence >= min_adherence,
            "value": adherence,
        },
    ]
