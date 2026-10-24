"""Typed views of the skills' JSON output.

Field names are copied from the scripts' real output (pinned commit, captured in
tests/contracts/). `extra="allow"` keeps any field not listed here, so a new field
upstream never breaks parsing; the contract tests catch removed or renamed ones.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _M(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


# --- alerts.py clock / quote / check / rules -------------------------------------------------


class ClockStatus(_M):
    now_new_york: str
    date: str
    weekday: str
    calendar_known: bool
    open: bool
    reason: str
    early_close: str | None = None
    opens: str | None = None  # absent on weekends and holidays
    closes: str | None = None  # "13:00" on an early close
    next_open: str | None = None

    @property
    def trading_day(self) -> bool:
        return self.opens is not None


class Quote(_M):
    symbol: str
    price: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    time: str | None = None
    currency: str | None = None
    source: str | None = None


class QuoteResult(_M):
    quotes: dict[str, Quote] = {}
    errors: list[Any] = []


class AlertRing(_M):
    id: str
    symbol: str | None = None
    message: str


class AlertCheck(_M):
    market: ClockStatus
    rings: list[AlertRing] = []
    errors: list[Any] = []
    quotes: dict[str, float] = {}


class AlertRule(_M):
    """A rule in trader/alerts.json (read from the file: `alerts.py list` has no JSON mode)."""

    id: str
    type: str
    symbol: str | None = None
    price: float | None = None
    pct: float | None = None
    at: str | None = None
    label: str | None = None
    before_close: bool | None = None
    date: str | None = None
    note: str | None = None
    rang: str | None = None  # filled from trader/state/alerts.json


# --- scan.py ---------------------------------------------------------------------------------


class UniverseResult(_M):
    count: int
    rows: int
    files_created: str | None = None
    dropped: dict[str, int] = {}
    out: str | None = None
    seconds: float | None = None


class ScanHit(_M):
    symbol: str
    setups: list[str]
    price: float
    # daily scan
    close_date: str | None = None
    rsi: float | None = None
    volume: int | None = None
    # opening-range scan
    at: str | None = None
    bar_start: str | None = None
    bar_index: int | None = None
    or_high: float | None = None
    or_low: float | None = None
    pct_over: float | None = None


class ScanCounts(_M):
    requested: int | None = None
    fetched: int | None = None
    unusable: int | None = None
    illiquid: int | None = None
    short: int | None = None
    scanned: int | None = None
    candidates: int | None = None
    confirmed: int | None = None
    unconfirmed: int | None = None
    hits: int | None = None


class ScanResult(_M):
    mode: Literal["daily", "orb"]
    created_at: str
    as_of: str | None = None
    universe: int
    scanned: int
    failed: int
    unconfirmed: int = 0
    source: str | None = None
    or_minutes: int | None = None
    interval: str | None = None
    filters: dict[str, Any] = {}
    note: str = ""
    hits: list[ScanHit] = []
    counts: ScanCounts | None = None
    offline: str | None = None
    seconds: float | None = None

    @property
    def partial(self) -> bool:
        return self.unconfirmed > 0


# --- news.py ---------------------------------------------------------------------------------


class NewsMove(_M):
    ticker: str
    price: float | None = None
    prev_close: float | None = None
    pct: float
    time: str | None = None
    moving: bool = False


class NewsItem(_M):
    id: str
    source: str
    kind: Literal["headline", "filing"] | str
    ticker: str | None = None
    title: str
    summary: str | None = None
    link: str | None = None
    time: str | None = None
    touches: list[str] = []
    tags: list[str] = []
    new: bool = False
    # SEC filings only
    form: str | None = None
    items: list[str] = []
    important: bool = False


class NewsResult(_M):
    checked: str
    moves: list[NewsMove] = []
    items: list[NewsItem] = []
    notes: list[str] = []


# --- entry.py --------------------------------------------------------------------------------


class OpeningRange(_M):
    high: float
    low: float
    minutes: int
    bars: int | None = None
    of: int | None = None
    complete: bool | None = None
    avg_volume: float | None = None


class Trigger(_M):
    time: str
    close_time: str
    bar_start: str
    bar_index: int
    price: float
    close: float | None = None
    volume: int | None = None
    volume_x: float | None = None
    pct_over: float | None = None


class EntryStatus(_M):
    symbol: str
    setup: str
    side: str
    date: str
    interval: str
    or_minutes: int
    now: str
    status: str  # waiting | triggered | expired | ...
    phase: str | None = None
    reason: str = ""
    opening_range: OpeningRange | None = None
    level: float | None = None
    trigger: Trigger | None = None
    last: dict[str, Any] | None = None
    forming: dict[str, Any] | None = None
    min_volume_x: float | None = None
    prev_close: float | None = None
    data_time: str | None = None
    bars_closed: int | None = None
    minutes_since: int | None = None
    no_entries_before: str | None = None
    no_entries_after: str | None = None

    @property
    def triggered(self) -> bool:
        return self.status == "triggered"


# --- exit.py ---------------------------------------------------------------------------------


class ExitPlan(_M):
    symbol: str
    side: str
    date: str
    setup: str | None = None
    entry: float
    entry_time: str | None = None
    entry_bar: int | None = None
    interval: str | None = None
    opening_range: OpeningRange | None = None
    stop: float
    stop_rule: str | None = None
    stop_label: str | None = None
    stop_detail: str | None = None
    target: float
    target_r: float | None = None
    target_label: str | None = None
    risk_per_share: float
    reward_risk: float | None = None
    flat_by: str | None = None
    created_at: str | None = None
    note: str | None = None
    warnings: list[str] = []


# --- timemachine.py --------------------------------------------------------------------------

BAND_QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)  # timemachine.py BAND_Q: one row of bands per bar


class TMHistogram(_M):
    lo: float
    hi: float
    bins: list[int]


class TMMonteCarlo(_M):
    replays: int
    seed: int
    window: int
    bars_left: int
    p_target: float
    p_stop: float
    p_neither: float
    p_green: float
    median_close: float
    p5_close: float
    p95_close: float
    avg_R: float
    r_at_target: float
    band_paths: int
    bands: list[list[float]]
    band_times: list[str]
    hist: TMHistogram
    until: str
    pool_sessions: int
    pool_from: str | None = None
    pool_to: str | None = None
    sample_paths: list[list[float]] = []  # only in the written file, not in --json stdout


class TMTrade(_M):
    date: str
    time: str | None = None
    entry: float
    stop: float
    target: float
    outcome: str
    R: float


class TMHistory(_M):
    sessions: int
    triggered: int
    target: int
    stop: int
    close: int
    green: int | None = None
    avg_R: float | None = None
    rule: dict[str, Any] = {}
    trades: list[TMTrade] = []


class TimeMachineResult(_M):
    created_at: str | None = None
    source: str | None = None
    data: dict[str, Any] = {}
    plan: dict[str, Any] = {}
    mc: TMMonteCarlo
    history: TMHistory | None = None
    verdict: str
    verdict_notes: list[str] = []
    warnings: list[str] = []
    note: str | None = None


# --- size.py ---------------------------------------------------------------------------------


class SizeLimit(_M):
    name: str
    usd: float | None = None
    per: float | None = None
    shares: int
    how: str = ""
    binds: bool = False


class Sizing(_M):
    symbol: str
    side: str | None = None
    setup: str | None = None
    date: str | None = None
    entry: float | None = None
    entry_plan: float | None = None
    entry_from: str | None = None
    stop: float | None = None
    target: float | None = None
    risk_per_share: float | None = None
    reward_risk: float | None = None
    budget: float | None = None
    cash_buffer: float | None = None
    cash_available: float | None = None
    max_loss_per_trade_usd: float | None = None
    limits: list[SizeLimit] = []
    qty: int = 0
    bound_by: str | None = None
    cost: float | None = None
    max_loss: float | None = None
    flat_by: str | None = None
    order_type: str | None = None
    refusal: str | None = None


class Order(_M):
    """One proposed order, in the shape of Alpaca's place_stock_order (plus `why` and `plan` notes)."""

    symbol: str
    side: str
    qty: str | None = None
    notional: str | None = None
    type: str
    time_in_force: str
    order_class: str | None = None
    limit_price: str | None = None
    take_profit_limit_price: str | None = None
    stop_loss_stop_price: str | None = None
    why: str | None = None
    plan: dict[str, Any] | None = None


class SizeResult(_M):
    sizing: Sizing
    orders: list[Order] = []
    notes: list[str] = []

    @property
    def refused(self) -> bool:
        return not self.orders


# --- check.py --------------------------------------------------------------------------------


class RiskVerdict(_M):
    index: int
    symbol: str
    side: str
    kind: str  # entry | exit
    amount: str | None = None
    value_usd: float | None = None
    entry_ref: float | None = None
    entry_ref_from: str | None = None
    stop: float | None = None
    target: float | None = None
    risk_per_share: float | None = None
    max_loss: float | None = None
    reward_risk: float | None = None
    fingerprint: str
    verdict: Literal["PASS", "BLOCK"]
    reasons: list[str] = []
    warnings: list[str] = []
    info: list[str] = []


class RiskToday(_M):
    orders_placed: int = 0
    entries_placed: int = 0
    loss_at_risk: float = 0.0
    day_trades_5d: int | None = None


class RiskReport(_M):
    date: str
    now_new_york: str
    paper: bool
    results: list[RiskVerdict] = []
    passed: int = Field(alias="pass")
    block: int
    warnings: list[str] = []
    cash_after: float | None = None
    today: RiskToday | None = None
    prices_as_of: str | None = None


# --- ticket.py -------------------------------------------------------------------------------


class Ticket(_M):
    index: int
    ready: bool
    status: str
    plain: str
    fingerprint: str | None = None
    paper: bool | None = None
    broker: str | None = None
    tool: str | None = None
    tool_input: dict[str, Any] = {}
    why: str | None = None
    bracket: bool | None = None
    max_loss: float | None = None
    stop: float | None = None


class BrokerRecord(_M):
    """One decision in trader/state/broker.json (`ticket.py log` has no JSON mode)."""

    at: str | None = None
    date: str | None = None  # the trading day it belongs to (ticket.py rec_day)
    index: int | None = None
    status: str | None = None  # approved | declined | placed | denied | failed | filled
    plain: str | None = None
    reply: str | None = None
    fingerprint: str | None = None
    symbol: str | None = None
    side: str | None = None
    qty: str | None = None
    kind: str | None = None
    max_loss: float | None = None
    stop: float | None = None
    price: float | None = None
    broker_order_id: str | None = None

    @property
    def day(self) -> str:
        return self.date or (self.at or "")[:10]


class Position(_M):
    symbol: str
    qty: float | str | None = None
    avg_price: float | None = None


class Portfolio(_M):
    cash: float | None = None
    positions: list[Position] = []


# --- facts.py --------------------------------------------------------------------------------


class EarningsRow(_M):
    end: str
    start: str | None = None
    fiscal: str | None = None
    derived: bool = False
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    eps_diluted: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    revenue_yoy: float | None = None
    net_income_yoy: float | None = None
    eps_yoy: float | None = None
    filed: str | None = None
    form: str | None = None


class EarningsResult(_M):
    entity: str | None = None
    cik: str
    rows: list[EarningsRow] = []
    ttm: dict[str, float | None] = {}
    concepts: dict[str, list[str]] = {}


class EarningsFacts(_M):
    ticker: str
    result: EarningsResult
    filings: dict[str, Any] | None = None
    changes: list[str] = []
    note: str | None = None


# --- ptr.py ----------------------------------------------------------------------------------


class PtrFiling(_M):
    doc_id: str
    type: str
    type_name: str | None = None
    last: str | None = None
    first: str | None = None
    name: str
    district: str | None = None
    year: int
    filed: str
    url: str


class PtrRow(_M):
    owner: str | None = None
    owner_name: str | None = None
    type: str | None = None
    type_name: str | None = None
    date: str | None = None
    notified: str | None = None
    amount: str | None = None
    status: str | None = None
    account: str | None = None
    description: str | None = None
    ticker: str | None = None
    asset_type: str | None = None
    asset: str | None = None
    amount_low: int | None = None
    amount_high: int | None = None
    shares: int | None = None
    days_to_disclose: int | None = None
    late: bool | None = None


class PtrReport(_M):
    name: str | None = None
    status: str | None = None
    district: str | None = None
    doc_id: str | None = None
    filed: str | None = None
    rows: list[PtrRow] = []


class PtrNewReport(_M):
    filing: PtrFiling
    pdf: str | None = None
    report: PtrReport | None = None  # None when pdftotext is not installed


class PtrNew(_M):
    new: list[PtrFiling] = []
    reports: list[PtrNewReport] = []
