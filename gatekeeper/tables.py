"""Gatekeeper's SQLite tables (plan Section 8).

Conventions:
- `mode` is "live" or "replay" on every result table, so a replay never mixes with live history.
- Times are UTC (time-zone aware); `session_date` is the New York trading day.
- `payload` keeps the skill's whole JSON, so nothing is lost when a model changes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


def _json(**kw: Any) -> Any:
    return Field(default=None, sa_column=Column(JSON, **kw))


class SkillRun(SQLModel, table=True):
    """Every skill call: what ran, how it ended, and when it really held trader/."""

    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    tool: str = Field(index=True)
    args: list[str] | None = _json()
    status: str
    exit_code: int | None = None
    message: str = ""
    stderr_excerpt: str = ""
    writes_state: bool = False
    started_at: datetime = Field(index=True)  # when the script started (after any lock wait)
    duration_s: float = 0.0
    waited_s: float = 0.0
    job: str | None = None


class JobHeartbeat(SQLModel, table=True):
    """The last run of each worker job, per mode."""

    mode: str = Field(primary_key=True)
    job: str = Field(primary_key=True)
    last_run_at: datetime | None = None  # UTC, real time
    last_run_ny: str | None = None  # the job's clock in New York ("2026-10-19 10:15"), replay or live
    last_status: str | None = None  # ok | empty | skipped | error
    last_detail: str = ""
    last_ok_at: datetime | None = None
    last_error: str = ""
    last_error_at: datetime | None = None
    runs: int = 0
    errors: int = 0


class ScanRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    scan_mode: str  # daily | orb
    session_date: str = Field(index=True)
    as_of: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    universe: int = 0
    scanned: int = 0
    failed: int = 0
    unconfirmed: int = 0
    candidates: int | None = None
    hits_count: int = 0
    partial: bool = False
    payload: dict[str, Any] | None = _json()


class ScanHit(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    scan_run_id: int = Field(foreign_key="scanrun.id", index=True)
    rank: int
    symbol: str = Field(index=True)
    setups: str  # comma-separated
    price: float
    hit_time: str | None = None  # orb: when it broke out, e.g. "10:15 AM"
    or_high: float | None = None
    or_low: float | None = None
    pct_over: float | None = None
    rsi: float | None = None
    volume: int | None = None
    payload: dict[str, Any] | None = _json()


class NewsItem(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("mode", "key"),)

    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    key: str  # the link, else the skill's item id: one row per story
    item_id: str
    symbol: str | None = Field(default=None, index=True)
    published_at: datetime | None = Field(default=None, index=True)
    source: str = ""
    kind: str = ""  # headline | filing
    title: str = ""
    link: str | None = None
    tags: list[str] | None = _json()
    touches: list[str] | None = _json()
    form: str | None = None
    items_8k: list[str] | None = _json()
    important: bool = False
    first_seen: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] | None = _json()


class PriceMove(SQLModel, table=True):
    """Each news check's price line per ticker: how far from yesterday's close."""

    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    symbol: str = Field(index=True)
    checked_at: datetime = Field(default_factory=utcnow, index=True)
    price: float | None = None
    prev_close: float | None = None
    pct: float = 0.0
    moving: bool = False
    quote_time: datetime | None = None


class EarningsSnapshot(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    symbol: str = Field(index=True)
    as_of: datetime = Field(default_factory=utcnow)
    period_end: str | None = None
    fiscal: str | None = None
    revenue: float | None = None
    rev_yoy: float | None = None
    eps: float | None = None
    eps_yoy: float | None = None
    gross_m: float | None = None
    op_m: float | None = None
    net_m: float | None = None
    flags: list[str] | None = _json()
    next_report_date: str | None = None  # entered by hand, or from the news (Phase 3)
    payload: dict[str, Any] | None = _json()


class RegimeSnapshot(SQLModel, table=True):
    """Market context (filled in Phase 3)."""

    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    ts: datetime = Field(default_factory=utcnow, index=True)
    spy_chg: float | None = None
    qqq_chg: float | None = None
    iwm_chg: float | None = None
    spy_vs_vwap: float | None = None
    vix: float | None = None
    vix_chg: float | None = None
    breadth_orb_up: float | None = None
    label: str | None = None
    payload: dict[str, Any] | None = _json()


class EntrySignal(SQLModel, table=True):
    """An entry check, stored only when its status changes."""

    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    symbol: str = Field(index=True)
    setup: str
    session_date: str = Field(index=True)
    status: str  # waiting | triggered | expired | no-data | ...
    level: float | None = None
    last_close: float | None = None
    trigger_time: str | None = None
    trigger_price: float | None = None
    reason: str = ""
    checked_ny: str  # the check's New York clock, "2026-10-19 10:15:00"
    created_at: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] | None = _json()


class Plan(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    symbol: str = Field(index=True)
    date: str = Field(index=True)
    setup: str | None = None
    entry: float
    entry_time: str | None = None
    stop: float
    stop_rule: str | None = None
    target: float
    target_r: float | None = None
    risk_per_share: float
    reward_risk: float | None = None
    flat_by: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] | None = _json()


class TmResult(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    plan_id: int | None = Field(default=None, foreign_key="plan.id", index=True)
    symbol: str | None = None
    seed: int
    replays: int
    until: str
    p_target: float
    p_stop: float
    p_neither: float
    p_green: float
    avg_r: float
    hist_sessions: int | None = None
    hist_fired: int | None = None
    hist_target: int | None = None
    hist_stop: int | None = None
    hist_neither: int | None = None
    hist_avg_r: float | None = None
    verdict: str
    created_at: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] | None = _json()


class RiskVerdict(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    plan_id: int | None = Field(default=None, foreign_key="plan.id", index=True)
    session_date: str = Field(index=True)
    checked_ny: str
    order_index: int
    symbol: str
    side: str
    kind: str
    verdict: str  # PASS | BLOCK
    max_loss: float | None = None
    reward_risk: float | None = None
    fingerprint: str
    reasons: list[str] | None = _json()
    warnings: list[str] | None = _json()
    created_at: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] | None = _json()


class Readiness(SQLModel, table=True):
    """A Go / No-Go evaluation (Phase 5)."""

    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    ts: datetime = Field(default_factory=utcnow, index=True)
    scope: str  # day | trade
    plan_id: int | None = Field(default=None, foreign_key="plan.id")
    symbol: str | None = None
    overall: str  # GO | CAUTION | NO_TRADE
    gates: list[dict[str, Any]] | None = _json()


class Decision(SQLModel, table=True):
    """Taken or skipped, and whether the rules were followed (Phase 5)."""

    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    plan_id: int | None = Field(default=None, foreign_key="plan.id", index=True)
    ts: datetime = Field(default_factory=utcnow)
    action: str  # TAKEN | SKIPPED
    reason_note: str = ""
    followed_rules: bool = True
    symbol: str | None = None
    readiness_id: int | None = Field(default=None, foreign_key="readiness.id")
    overall: str | None = None  # the trade's Go / No-Go result when the decision was made


class TradeJournal(SQLModel, table=True):
    """The outcome of each plan, real or simulated (Phase 7)."""

    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    plan_id: int | None = Field(default=None, foreign_key="plan.id", index=True)
    decision_id: int | None = Field(default=None, foreign_key="decision.id")
    entry_fill: float | None = None
    exit_fill: float | None = None
    exit_reason: str | None = None  # target | stop | flat | manual
    r_result: float | None = None
    simulated: bool = False
    notes: str = ""


class AlertFired(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    rule_id: str = Field(index=True)
    symbol: str | None = None
    message: str
    session_date: str = Field(index=True)
    fired_ny: str
    fired_at: datetime = Field(default_factory=utcnow)
    notified: bool = False


class PelosiFiling(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("mode", "doc_id"),)

    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True)
    doc_id: str
    member: str
    district: str | None = None
    filing_type: str | None = None
    filed: str = Field(index=True)
    url: str
    rows: list[dict[str, Any]] | None = _json()
    overlaps_holdings: bool = False
    first_seen: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] | None = _json()


class ReplayState(SQLModel, table=True):
    """How far the replay day has been simulated, so the dashboard's time slider only runs what's new."""

    id: int = Field(default=1, primary_key=True)
    day: str
    until_ny: str  # "HH:MM", the last simulated minute
    workspace: str
    updated_at: datetime = Field(default_factory=utcnow)


class PinnedTicker(SQLModel, table=True):
    """The tickers the entry watch follows."""

    mode: str = Field(primary_key=True)
    symbol: str = Field(primary_key=True)
    added_at: datetime = Field(default_factory=utcnow)
    note: str = ""


# Tables with a `mode` column, children before parents (for deleting one mode's rows).
MODE_TABLES: list[type[SQLModel]] = [
    TradeJournal,
    Decision,
    Readiness,
    RiskVerdict,
    TmResult,
    Plan,
    SkillRun,
    JobHeartbeat,
    NewsItem,
    PriceMove,
    EarningsSnapshot,
    RegimeSnapshot,
    EntrySignal,
    AlertFired,
    PelosiFiling,
    PinnedTicker,
]
