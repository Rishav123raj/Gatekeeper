"""Go / No-Go: every check a trade (and the day) has to pass, each with its reason.

Gates are pure functions of a context and the thresholds in Settings (GATE_* in .env), so
they are easy to test. `build_day_context` and `build_trade_context` gather the inputs.

The result is GO, CAUTION or NO_TRADE:
- any **hard** gate FAILs → NO_TRADE;
- otherwise any WARN, or a **soft** gate FAILs → CAUTION;
- otherwise → GO.

GO never means "buy". It means your rules allow the trade and the honest odds aren't
against it. Nothing here places an order.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.engine import Engine
from sqlmodel import col, select

from gatekeeper import store
from gatekeeper.clock import CLOSE, IST, SessionTimes, as_ny, load_session_times, market_day, session_phase
from gatekeeper.db import session
from gatekeeper.settings import Settings
from gatekeeper.skills._base import read_json
from gatekeeper.skills.models import (
    BrokerRecord,
    ClockStatus,
    EntryStatus,
    ExitPlan,
    RiskReport,
    SizeResult,
    TimeMachineResult,
)
from gatekeeper.tables import Decision, EarningsSnapshot, NewsItem, PriceMove, TradeJournal

Status = Literal["PASS", "WARN", "FAIL"]
Level = Literal["hard", "soft"]
Overall = Literal["GO", "CAUTION", "NO_TRADE"]

FAIL_8K_ITEMS = {
    "2.02",
    "4.02",
    "1.03",
    "3.01",
    "1.05",
}  # earnings, restatement, bankruptcy, delisting, cyber
WARN_TAGS = {"legal", "regulatory", "risk"}
FRESH_PRICE = timedelta(minutes=15)  # the skills' own freshness rule for prices.json

VERDICTS = [  # the Time Machine's verdict wording -> a category
    ("Strongly toward the target", "strong_target"),
    ("Leans toward the target", "lean_target"),
    ("Close to a coin flip", "coin_flip"),
    ("Close to break-even", "break_even"),
    ("Leans toward the stop", "lean_stop"),
    ("Strongly toward the stop", "strong_stop"),
    ("No replay reached", "none"),
]


@dataclass
class Gate:
    name: str
    level: Level
    status: Status
    reason: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class ReadinessResult:
    scope: Literal["day", "trade"]
    overall: Overall
    gates: list[Gate]
    symbol: str | None = None
    plan_id: int | None = None

    def problems(self) -> list[Gate]:
        return [g for g in self.gates if g.status != "PASS"]

    def summary(self) -> str:
        bad = self.problems()
        return "; ".join(f"{g.name}: {g.reason}" for g in bad) if bad else "every check passed"


def overall_of(gates: list[Gate]) -> Overall:
    if any(g.level == "hard" and g.status == "FAIL" for g in gates):
        return "NO_TRADE"
    if any(g.status in ("WARN", "FAIL") for g in gates):
        return "CAUTION"
    return "GO"


def _hm(t: time) -> str:
    return f"{t:%H:%M}"


def _ist(d: date, t: time) -> str:
    return f"{as_ny(datetime.combine(d, t)).astimezone(IST):%H:%M}"


def _minus(t: time, delta: timedelta) -> time:
    return (datetime.combine(date.min, t) - delta).time()


def verdict_category(verdict: str) -> str:
    for prefix, cat in VERDICTS:
        if verdict.startswith(prefix):
            return cat
    return "unknown"


# --- the day ---------------------------------------------------------------------------------


@dataclass
class DayContext:
    now: datetime  # New York
    day: ClockStatus | None
    times: SessionTimes
    phase: str
    config: dict[str, Any]
    awake_ist: str
    placed_today: list[BrokerRecord] = field(default_factory=list)
    day_trades_5d: int = 0
    regime: dict[str, Any] | None = None
    breadth_pct: float | None = None
    form_r: list[float] = field(default_factory=list)  # newest first
    form_followed: list[bool] = field(default_factory=list)  # newest first

    @property
    def close(self) -> time:
        return datetime.strptime(self.day.closes, "%H:%M").time() if self.day and self.day.closes else CLOSE

    @property
    def early_shift(self) -> timedelta:
        return datetime.combine(date.min, CLOSE) - datetime.combine(date.min, self.close)


def g_market_open(c: DayContext, s: Settings) -> Gate:
    name, src = "Market open", "alerts.py clock"
    d = c.now.date()
    if c.now.weekday() >= 5 or (c.day is not None and c.day.calendar_known and not c.day.trading_day):
        return Gate(name, "hard", "FAIL", f"closed: {c.day.reason if c.day else 'weekend'}", src)
    if c.phase == "after_close":
        return Gate(name, "hard", "FAIL", f"closed for the day (closed {_hm(c.close)} NY)", src)
    if c.day is not None and c.day.early_close:
        return Gate(name, "hard", "WARN", f"early close at {c.day.closes} NY ({c.day.early_close})", src)
    if c.phase == "premarket":
        return Gate(name, "hard", "PASS", f"opens 09:30 NY ({_ist(d, time(9, 30))} IST)", src)
    return Gate(name, "hard", "PASS", f"open, regular session until {_hm(c.close)} NY", src)


def g_entry_window(c: DayContext, s: Settings) -> Gate:
    name, src = "Entry window", "trader/config.json"
    d = c.now.date()
    start, end = c.times.no_entries_before, _minus(c.times.no_entries_after, c.early_shift)
    now = c.now.time()
    window = f"{_hm(start)}–{_hm(end)} NY ({_ist(d, start)}–{_ist(d, end)} IST)"
    if now < start:
        return Gate(name, "hard", "FAIL", f"no new entries before {_hm(start)} NY: window {window}", src)
    if now >= end:
        return Gate(name, "hard", "FAIL", f"no new entries after {_hm(end)} NY: window {window}", src)
    left = int((datetime.combine(d, end) - datetime.combine(d, now)).total_seconds() // 60)
    status: Status = "WARN" if left < s.gate_window_warn_min else "PASS"
    return Gate(name, "hard", status, f"{left // 60} h {left % 60:02d} min left in the window {window}", src)


def _in_window(t: time, start: time, end: time) -> bool:
    return start <= t <= end if start <= end else (t >= start or t <= end)  # a window can cross midnight


def g_awake(c: DayContext, s: Settings) -> Gate:
    name, src = "Awake window (IST)", "AWAKE_IST + flat_by"
    flat = _minus(c.times.flat_by, c.early_shift)
    flat_ist = as_ny(datetime.combine(c.now.date(), flat)).astimezone(IST).time()
    a, _, b = c.awake_ist.partition("-")
    start, end = (datetime.strptime(x, "%H:%M").time() for x in (a, b))
    if _in_window(flat_ist, start, end):
        return Gate(
            name, "soft", "PASS", f"flat-by {_hm(flat)} NY is {_hm(flat_ist)} IST, inside {c.awake_ist}", src
        )
    return Gate(
        name,
        "soft",
        "FAIL",
        f"flat-by {_hm(flat)} NY is {_hm(flat_ist)} IST, outside your awake hours {c.awake_ist} IST: "
        "nothing closes the trade for you; set flat_by earlier or stay up",
        src,
    )


def g_daily_loss(c: DayContext, s: Settings) -> Gate:
    name, src = "Daily loss budget", "trader/state/broker.json"
    limit = c.config.get("max_daily_loss_usd")
    used = round(sum(r.max_loss or 0 for r in c.placed_today), 2)
    if not limit:
        return Gate(name, "hard", "WARN", "no max_daily_loss_usd in trader/config.json", src)
    text = f"${used:,.2f} of ${limit:,.0f} at risk today"
    if used >= limit:
        return Gate(name, "hard", "FAIL", text + ": the day's limit is used up", src)
    status: Status = "WARN" if used >= limit * s.gate_daily_loss_warn_pct / 100 else "PASS"
    return Gate(name, "hard", status, text, src)


def g_trades_left(c: DayContext, s: Settings) -> Gate:
    name, src = "Trades left", "trader/state/broker.json"
    cap = c.config.get("max_trades_per_day")
    n = len(c.placed_today)
    if not cap:
        return Gate(name, "hard", "WARN", "no max_trades_per_day in trader/config.json", src)
    left = cap - n
    if left <= 0:
        return Gate(name, "hard", "FAIL", f"{n} of {cap} trades placed: none left today", src)
    status: Status = "WARN" if left <= s.gate_trades_warn_left else "PASS"
    return Gate(name, "hard", status, f"{n} of {cap} trades placed, {left} left", src)


def g_pdt(c: DayContext, s: Settings) -> Gate:
    name, src = "Pattern day trader", "trader/config.json pdt_guard"
    if not c.config.get("pdt_guard"):
        return Gate(
            name, "hard", "PASS", "pdt_guard off (turn it on if your broker still applies the old rule)", src
        )
    n = c.day_trades_5d
    if n >= 3:
        return Gate(name, "hard", "FAIL", f"{n} day trades in the last 5 business days", src)
    status: Status = "WARN" if n >= s.gate_pdt_warn else "PASS"
    return Gate(name, "hard", status, f"{n} day trades in the last 5 business days", src)


def g_market_context(c: DayContext, s: Settings) -> Gate:
    name, src = "Market context", "regime (SPY / QQQ / VIX)"
    if not c.regime:
        return Gate(name, "soft", "PASS", "no market context recorded yet", src)
    spy, vix = c.regime["indexes"].get("SPY", {}), c.regime.get("vix", {})
    warns = []
    if vix.get("change_pct") is not None and vix["change_pct"] > s.gate_vix_spike_pct:
        warns.append(f"VIX up {vix['change_pct']:.1f} % today")
    if (spy.get("vs_vwap_pct") or 0) < 0 and spy.get("vs_or") == "below":
        warns.append("SPY below its VWAP and its opening-range low")
    label = f"tape {c.regime['label']} (score {c.regime['score']:+d})"
    if warns:
        return Gate(name, "soft", "WARN", f"{label}: " + "; ".join(warns), src)
    return Gate(name, "soft", "PASS", label, src)


def g_breadth(c: DayContext, s: Settings) -> Gate:
    name, src = "Breadth", "latest ORB scan"
    if c.breadth_pct is None:
        return Gate(name, "soft", "PASS", "no opening-range scan yet today", src)
    text = f"{c.breadth_pct:.0f} % of usable charts broke their opening range"
    if c.breadth_pct < s.gate_breadth_warn_pct:
        return Gate(name, "soft", "WARN", text + ": a weak tape for long breakouts", src)
    return Gate(name, "soft", "PASS", text, src)


def g_recent_form(c: DayContext, s: Settings) -> Gate:
    name, src = "Recent form", "journal and decisions"
    n = s.gate_form_trades
    rs, followed = c.form_r[:n], c.form_followed[:n]
    if not rs and not followed:
        return Gate(name, "soft", "PASS", "no journal yet", src)
    warns = []
    if rs and sum(rs) <= s.gate_form_r_warn:
        warns.append(f"the last {len(rs)} trades sum to {sum(rs):+.1f}R")
    broken = sum(1 for f in followed if not f)
    if broken >= s.gate_form_broken_warn:
        warns.append(f"rules broken in {broken} of the last {len(followed)} decisions")
    if warns:
        return Gate(name, "soft", "WARN", "; ".join(warns) + ": slow down", src)
    parts = [f"last {len(rs)} trades {sum(rs):+.1f}R" if rs else "no journal trades yet"]
    if followed:
        parts.append(f"rules followed in {len(followed) - broken} of the last {len(followed)} decisions")
    return Gate(name, "soft", "PASS", "; ".join(parts), src)


DAY_GATES = [
    g_market_open,
    g_entry_window,
    g_awake,
    g_daily_loss,
    g_trades_left,
    g_pdt,
    g_market_context,
    g_breadth,
    g_recent_form,
]


def evaluate_day(c: DayContext, s: Settings) -> ReadinessResult:
    gates = [g(c, s) for g in DAY_GATES]
    return ReadinessResult("day", overall_of(gates), gates)


# --- the trade -------------------------------------------------------------------------------


@dataclass
class TradeContext:
    now: datetime  # New York
    symbol: str
    entry: EntryStatus | None = None
    plan: ExitPlan | None = None
    plan_error: str | None = None
    plan_id: int | None = None
    tm: TimeMachineResult | None = None
    size: SizeResult | None = None
    risk: RiskReport | None = None
    news: list[NewsItem] = field(default_factory=list)
    move: PriceMove | None = None
    earnings: EarningsSnapshot | None = None
    fresh_price: float | None = None
    min_rr: float = 1.0


def _bar_minutes(e: EntryStatus) -> int:
    return int(e.interval.rstrip("m")) if e.interval and e.interval.rstrip("m").isdigit() else 5


def g_entry(c: TradeContext, s: Settings) -> Gate:
    name, src = "Entry triggered", "entry.py"
    e = c.entry
    if e is None:
        return Gate(name, "hard", "FAIL", "the entry hasn't been checked", src)
    if not e.trigger:
        return Gate(name, "hard", "FAIL", f"{e.status}: {e.reason}", src)
    t = e.trigger
    closed = datetime.combine(c.now.date(), datetime.strptime(t.close_time, "%H:%M").time(), c.now.tzinfo)
    age = int((c.now - closed).total_seconds() // 60)
    text = f"triggered {t.time} at ${t.price:.2f} (the {t.bar_start} bar)"
    if age > _bar_minutes(e) * s.gate_entry_stale_bars:
        return Gate(name, "hard", "WARN", f"{text}, {age} min ago: a late entry is a different trade", src)
    return Gate(name, "hard", "PASS", text, src)


def g_news(c: TradeContext, s: Settings) -> Gate:
    name, src = "News clean", "news.py (headlines, 8-K)"
    fails, warns = [], []
    for n in c.news:
        hit = FAIL_8K_ITEMS & set(n.items_8k or [])
        if n.important and hit:
            fails.append(f"8-K item {', '.join(sorted(hit))}: {n.title}")
        if "halt" in (n.tags or []):
            fails.append(f"halt: {n.title}")
        for tag in sorted(WARN_TAGS & set(n.tags or [])):
            warns.append(f"{tag}: {n.title}")
    if c.move is not None and c.move.moving and not c.news:
        warns.append(f"moving {c.move.pct:+.2f} % with no headline")
    if fails:
        return Gate(name, "hard", "FAIL", "; ".join(fails[:3]), src)
    if warns:
        return Gate(name, "hard", "WARN", "; ".join(warns[:3]), src)
    tags = sorted({t for n in c.news for t in n.tags or []})
    return Gate(
        name,
        "hard",
        "PASS",
        f"{len(c.news)} items in the last {s.gate_news_hours} h, nothing flagged"
        + (f" (tags: {', '.join(tags)})" if tags else ""),
        src,
    )


def _sessions_until(today: date, d: date) -> int:
    n, cur = 0, today
    while cur < d:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def g_earnings(c: TradeContext, s: Settings) -> Gate:
    name, src = "Earnings outside the trade", "earnings date (by hand) + news"
    today = c.now.date()
    if c.earnings is not None and c.earnings.next_report_date:
        d = date.fromisoformat(c.earnings.next_report_date)
        if d == today:
            return Gate(
                name,
                "hard",
                "FAIL",
                f"reports today ({d:%a %d %b}): results can halt or gap it past any stop",
                src,
            )
        if d > today and _sessions_until(today, d) <= s.gate_earnings_warn_sessions:
            return Gate(
                name,
                "hard",
                "WARN",
                f"reports {d:%a %d %b}, in {_sessions_until(today, d)} sessions: "
                "don't hold it past the close",
                src,
            )
        return Gate(name, "hard", "PASS", f"next report {d:%a %d %b}", src)
    if any("earnings" in (n.tags or []) for n in c.news):
        return Gate(
            name,
            "hard",
            "WARN",
            "earnings are in today's news but no report date is set: check it "
            "(Watchlist & News) and stay flat by the close",
            src,
        )
    return Gate(name, "hard", "PASS", "no report date known and no earnings news", src)


def g_plan(c: TradeContext, s: Settings) -> Gate:
    name, src = "Plan valid", "exit.py"
    p = c.plan
    if p is None:
        return Gate(name, "hard", "FAIL", c.plan_error or "no exit plan yet", src)
    risk_pct = 100 * p.risk_per_share / p.entry
    text = (
        f"stop ${p.stop:.2f} ({p.stop_label}), target ${p.target:.2f}, "
        f"risk ${p.risk_per_share:.2f} ({risk_pct:.2f} %)"
    )
    if risk_pct < s.gate_min_risk_pct:
        return Gate(name, "hard", "WARN", text + ": a tight stop, normal wiggle may hit it", src)
    return Gate(name, "hard", "PASS", text, src)


def g_reward_risk(c: TradeContext, s: Settings) -> Gate:
    name, src = "Reward : risk at the fresh price", "plan + trader/prices.json"
    p = c.plan
    if p is None:
        return Gate(name, "hard", "FAIL", "no exit plan yet", src)
    ref = p.entry if c.fresh_price is None else max(p.entry, round(c.fresh_price + 1e-9, 2))
    where = "the plan's entry" if ref == p.entry else f"the fresh price ${ref:.2f}"
    risk, reward = round(ref - p.stop, 2), round(p.target - ref, 2)
    if risk <= 0:
        return Gate(name, "hard", "FAIL", f"{where} is at or under the stop ${p.stop:.2f}", src)
    rr = round(reward / risk, 2)
    text = f"{rr:.2f} from {where} (minimum {c.min_rr:g})"
    if rr < c.min_rr:
        return Gate(
            name,
            "hard",
            "FAIL",
            text + ": the move it was waiting for has mostly happened" if ref > p.entry else text,
            src,
        )
    if rr < c.min_rr * (1 + s.gate_rr_warn_margin_pct / 100):
        return Gate(name, "hard", "WARN", text + ": right at the minimum", src)
    return Gate(name, "hard", "PASS", text, src)


def _same_plan(tm: TimeMachineResult, p: ExitPlan) -> bool:
    q = tm.plan
    return (q.get("symbol"), q.get("entry"), q.get("stop"), q.get("target")) == (
        p.symbol,
        p.entry,
        p.stop,
        p.target,
    )


def g_time_machine(c: TradeContext, s: Settings) -> Gate:
    name, src = "Time Machine verdict", "timemachine.py"
    tm = c.tm
    if tm is None:
        return Gate(name, "hard", "FAIL", "run the Time Machine on this plan first", src)
    if c.plan is not None and not _same_plan(tm, c.plan):
        return Gate(name, "hard", "FAIL", "the replays were run on a different plan: run them again", src)
    cat = verdict_category(tm.verdict)
    neither = 100 * tm.mc.p_neither
    extra = f"; {neither:.1f} % hit neither by {tm.mc.until}" if neither > s.gate_tm_neither_warn_pct else ""
    text = tm.verdict.rstrip(".") + extra + f" (seed {tm.mc.seed})"
    if cat in ("lean_stop", "strong_stop"):
        return Gate(name, "hard", "FAIL", text, src)
    if cat in ("coin_flip", "break_even", "none", "unknown") or extra:
        return Gate(name, "hard", "WARN", text, src)
    return Gate(name, "hard", "PASS", text, src)


def g_history(c: TradeContext, s: Settings) -> Gate:
    name, src = "History agrees", "timemachine.py history"
    tm = c.tm
    if tm is None or tm.history is None:
        return Gate(name, "soft", "WARN", "no history for this rule", src)
    h = tm.history
    text = (
        f"{h.triggered} fired in {h.sessions} sessions: {h.target} target, {h.stop} stop, {h.close} neither"
    )
    if h.triggered < s.gate_history_min_fires:
        return Gate(
            name, "soft", "WARN", text + f": fewer than {s.gate_history_min_fires}, too few to trust", src
        )
    sided = h.target + h.stop
    r = tm.mc.r_at_target or 1.0
    even = 1 / (1 + r)
    if verdict_category(tm.verdict) in ("lean_target", "strong_target") and sided and h.target / sided < even:
        return Gate(
            name,
            "soft",
            "WARN",
            text + f": the target came first in {100 * h.target / sided:.0f} % "
            f"of real sessions, under the {100 * even:.0f} % break-even",
            src,
        )
    return Gate(name, "soft", "PASS", text, src)


def g_risk(c: TradeContext, s: Settings) -> Gate:
    name, src = "Risk check", "check.py"
    rep = c.risk
    if rep is None:
        return Gate(name, "hard", "FAIL", "not checked yet: run Size & check", src)
    mine = [v for v in rep.results if v.symbol == c.symbol] or rep.results
    blocked = [v for v in mine if v.verdict == "BLOCK"]
    if blocked:
        return Gate(name, "hard", "FAIL", "BLOCK: " + "; ".join(r for v in blocked for r in v.reasons), src)
    warns = [w for v in mine for w in v.warnings] + list(rep.warnings)
    v = mine[0] if mine else None
    text = (
        f"PASS: max loss ${v.max_loss:,.2f}, reward:risk {v.reward_risk}"
        if v and v.max_loss is not None
        else "PASS"
    )
    if warns:
        return Gate(name, "hard", "WARN", text + "; " + "; ".join(warns[:2]), src)
    return Gate(name, "hard", "PASS", text, src)


def g_size(c: TradeContext, s: Settings) -> Gate:
    name, src = "Size sane", "size.py"
    z = c.size
    if z is None:
        return Gate(name, "hard", "FAIL", "not sized yet: run Size & check", src)
    sz = z.sizing
    if z.refused:
        return Gate(name, "hard", "FAIL", sz.refusal or "no order", src)
    text = f"{sz.qty} shares, ${sz.cost:,.2f}, bound by {sz.bound_by}; ${sz.max_loss:,.2f} at the stop"
    if sz.bound_by in ("cash", "position cap"):
        return Gate(name, "hard", "WARN", text + ": your max loss isn't what limits it", src)
    return Gate(name, "hard", "PASS", text, src)


TRADE_GATES = [g_entry, g_news, g_earnings, g_plan, g_reward_risk, g_time_machine, g_history, g_risk, g_size]


def evaluate_trade(c: TradeContext, s: Settings) -> ReadinessResult:
    gates = [g(c, s) for g in TRADE_GATES]
    return ReadinessResult("trade", overall_of(gates), gates, symbol=c.symbol, plan_id=c.plan_id)


# --- gathering the inputs --------------------------------------------------------------------


def _business_days_back(d: date, n: int) -> date:
    cur, left = d, n
    while left:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            left -= 1
    return cur


def broker_records(trader_dir: Path) -> list[BrokerRecord]:
    doc = read_json(trader_dir / "state" / "broker.json", {}) or {}
    return [BrokerRecord.model_validate(r) for r in doc.get("orders", [])]


def build_day_context(
    engine: Engine, mode: str, now: datetime, trader_dir: Path, settings: Settings, day_lookup=market_day
) -> DayContext:
    now = as_ny(now)
    today = now.date()
    day = day_lookup(today)
    times = load_session_times(trader_dir)
    entries = [r for r in broker_records(trader_dir) if r.status == "placed" and r.kind == "entry"]
    since = _business_days_back(today, 4).isoformat()
    with session(engine) as s:
        runs = store.scan_runs(s, mode, "orb", today.isoformat())
        reg = store.latest_regime(s, mode)
        n = settings.gate_form_trades
        journal = s.exec(
            select(TradeJournal)
            .where(TradeJournal.mode == mode, col(TradeJournal.r_result).is_not(None))
            .order_by(col(TradeJournal.id).desc())
            .limit(n)
        ).all()
        decisions = s.exec(
            select(Decision).where(Decision.mode == mode).order_by(col(Decision.id).desc()).limit(n)
        ).all()
    regime = (
        reg.payload if reg is not None and (mode == "replay" or _fresh(reg.ts, now, minutes=30)) else None
    )
    last = runs[-1] if runs else None
    return DayContext(
        now=now,
        day=day,
        times=times,
        phase=session_phase(now, times, day),
        config=read_json(trader_dir / "config.json", {}) or {},
        awake_ist=settings.awake_ist,
        placed_today=[r for r in entries if r.day == today.isoformat()],
        day_trades_5d=sum(1 for r in entries if r.day >= since),
        regime=regime,
        breadth_pct=(round(100 * last.hits_count / last.scanned, 1) if last and last.scanned else None),
        form_r=[j.r_result for j in journal],
        form_followed=[d.followed_rules for d in decisions],
    )


def _fresh(ts: datetime | None, now: datetime, minutes: int) -> bool:
    if ts is None:
        return False
    ts = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return abs(now.astimezone(UTC) - ts) <= timedelta(minutes=minutes)


def fresh_price(trader_dir: Path, symbol: str, now: datetime) -> float | None:
    """The price in trader/prices.json if it is under 15 minutes old at `now` (the skills' rule)."""
    doc = read_json(trader_dir / "prices.json", {}) or {}
    price = (doc.get("prices") or {}).get(symbol)
    stamp = ((doc.get("detail") or {}).get(symbol) or {}).get("time") or doc.get("as_of")
    if price is None or not stamp:
        return None
    try:
        t = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    t = t if t.tzinfo else t.replace(tzinfo=UTC)
    age = now.astimezone(UTC) - t
    return float(price) if timedelta(0) <= age <= FRESH_PRICE else None


def build_trade_context(
    engine: Engine,
    mode: str,
    now: datetime,
    trader_dir: Path,
    settings: Settings,
    symbol: str,
    *,
    entry: EntryStatus | None = None,
    plan: ExitPlan | None = None,
    plan_id: int | None = None,
    plan_error: str | None = None,
    tm: TimeMachineResult | None = None,
    size: SizeResult | None = None,
    risk: RiskReport | None = None,
) -> TradeContext:
    """The trade's inputs: whatever the page passes, else the latest stored for that symbol today."""
    now = as_ny(now)
    today = now.date().isoformat()
    since = now.astimezone(UTC) - timedelta(hours=settings.gate_news_hours)
    with session(engine) as s:
        if entry is None and (sig := store.latest_entry(s, mode, symbol, today)) is not None and sig.payload:
            entry = EntryStatus.model_validate(sig.payload)
        if plan is None:
            row = store.latest_plan(s, mode, symbol, today)
            if row is not None:
                plan, plan_id = ExitPlan.model_validate(row.payload), row.id
        if tm is None and plan_id is not None and (t := store.latest_tm(s, mode, plan_id)) is not None:
            tm = TimeMachineResult.model_validate(t.payload)
        news = [
            n
            for n in store.news_items(s, mode, symbols=[symbol], since=since)
            if n.published_at is None or n.published_at <= now
        ]
        move = store.latest_moves(s, mode).get(symbol)
        earnings = store.latest_earnings(s, mode).get(symbol)
    cfg = read_json(trader_dir / "config.json", {}) or {}
    return TradeContext(
        now=now,
        symbol=symbol,
        entry=entry,
        plan=plan,
        plan_error=plan_error,
        plan_id=plan_id,
        tm=tm,
        size=size,
        risk=risk,
        news=news,
        move=move,
        earnings=earnings,
        fresh_price=fresh_price(trader_dir, symbol, now),
        min_rr=float(cfg.get("min_reward_risk") or 1.0),
    )
