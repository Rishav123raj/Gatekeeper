"""The worker's jobs (plan Section 7) and their New York schedule.

Each job checks the market clock first and skips when it doesn't apply (weekend, holiday,
outside its part of the session). Then it calls a skill wrapper, saves the result and
records a heartbeat. A job never places, cancels or changes an order.

The schedule is a set of cron rules in New York time. The live scheduler (APScheduler)
and the replay simulator both read it, so a replay fires exactly what a live day would.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from sqlalchemy.engine import Engine

from gatekeeper import store
from gatekeeper.clock import SessionTimes, as_ny, load_session_times, market_day, session_phase
from gatekeeper.db import session
from gatekeeper.runner import RunResult, SkillRunner
from gatekeeper.settings import Settings
from gatekeeper.skills import alerts, analyst, broker, entry, news, pelosi, scanner
from gatekeeper.skills._base import read_json
from gatekeeper.skills.models import ClockStatus

log = logging.getLogger("gatekeeper.worker")

OPEN_PHASES = {"opening_range", "entry_window", "late"}
ORB_FIRST = time(9, 50)  # the scanner refuses an opening-range scan before 9:50
FULL_ORB_AT = time(10, 15)  # the one universe-wide ORB scan of the day, if switched on
NEWS_FROM_SCAN = 10  # news also covers the latest scan's top hits

WEEKDAYS = "mon-fri"

# job -> cron rules (New York time). Jobs fire in this order when several are due at once.
SCHEDULE: dict[str, list[dict[str, Any]]] = {
    "clock": [{"minute": "*"}],
    "universe": [{"day_of_week": "sun", "hour": 18, "minute": 0}],
    "analyst_watchlist": [{"day_of_week": WEEKDAYS, "hour": 7, "minute": 0}],
    "daily_scan": [{"day_of_week": WEEKDAYS, "hour": 8, "minute": 30}],
    "premarket_news": [{"day_of_week": WEEKDAYS, "hour": 8, "minute": 45}],
    "regime": [{"day_of_week": WEEKDAYS, "hour": "9-15", "minute": "*/5"}],
    "orb_scan": [
        {"day_of_week": WEEKDAYS, "hour": 9, "minute": 50},
        {"day_of_week": WEEKDAYS, "hour": "10-15", "minute": "0,15,30,45"},
    ],
    "intraday_news": [{"day_of_week": WEEKDAYS, "hour": "9-15", "minute": "*/15"}],
    "entry_watch": [{"day_of_week": WEEKDAYS, "hour": "9-15", "minute": "*"}],
    "quotes": [{"day_of_week": WEEKDAYS, "hour": "9-15", "minute": "*/5"}],
    "alerts_check": [{"day_of_week": WEEKDAYS, "hour": "9-15", "minute": "*/2"}],
    "pelosi": [{"day_of_week": WEEKDAYS, "hour": "8-20", "minute": 0}],
    "eod_journal": [{"day_of_week": WEEKDAYS, "hour": 16, "minute": 10}],
}

# In replay the recorded data covers a fixed set of tickers.
REPLAY_TICKERS = {"news": ["TSLA"], "analyst": ["AAPL", "KO"]}


class Skip(Exception):
    """The job does not apply now; the reason goes in the heartbeat."""


@dataclass
class JobContext:
    """Everything a job needs: the clock, the database, and a runner for a given moment."""

    engine: Engine
    mode: str  # live | replay
    settings: Settings
    make_runner: Callable[[datetime, str], SkillRunner]  # (New York time, job) -> runner
    clock: Callable[[], datetime]  # New York now (the simulated clock in replay)
    day_lookup: Callable[[date], ClockStatus | None] = market_day
    _days: dict[date, ClockStatus | None] = field(default_factory=dict)

    def now(self) -> datetime:
        return as_ny(self.clock())

    def runner(self, job: str) -> SkillRunner:
        return self.make_runner(self.now(), job)

    def day(self, d: date | None = None) -> ClockStatus | None:
        d = d or self.now().date()
        if d not in self._days:
            self._days[d] = self.day_lookup(d)
        return self._days[d]

    def times(self, job: str) -> SessionTimes:
        return load_session_times(self.runner(job).trader_dir)

    def phase(self, job: str) -> str:
        return session_phase(self.now(), self.times(job), self.day())

    def trading_day(self) -> bool:
        day = self.day()
        return self.now().weekday() < 5 and (day is None or not day.calendar_known or day.trading_day)

    def tickers(self, kind: str) -> list[str]:
        if self.mode == "replay" and kind in REPLAY_TICKERS:
            return REPLAY_TICKERS[kind]
        return list(self.settings.core_tickers)


# --- guards ----------------------------------------------------------------------------------


def need_trading_day(ctx: JobContext) -> None:
    if not ctx.trading_day():
        day = ctx.day()
        raise Skip(day.reason if day else "weekend")


def need_phase(ctx: JobContext, job: str, phases: set[str]) -> str:
    need_trading_day(ctx)
    phase = ctx.phase(job)
    if phase not in phases:
        raise Skip(f"not now ({phase})")
    return phase


def _checked(res: RunResult, what: str) -> None:
    if res.status == "error":
        raise RuntimeError(f"{what}: {res.message or 'failed'}")


# --- jobs ------------------------------------------------------------------------------------


def job_clock(ctx: JobContext) -> str:
    """The NYSE clock, every minute: the worker's pulse."""
    if ctx.mode == "live":
        status, res = alerts.clock(runner=ctx.runner("clock"))
        _checked(res, "clock")
    else:
        status = ctx.day()  # a replay doesn't need a subprocess a minute for a static calendar
    phase = ctx.phase("clock")
    return f"{phase}; {status.reason if status else 'calendar unknown'}"


def job_universe(ctx: JobContext) -> str:
    result, res = scanner.universe(runner=ctx.runner("universe"))
    _checked(res, "universe")
    return f"{result.count:,} stocks in the universe"


def job_analyst_watchlist(ctx: JobContext) -> str:
    need_trading_day(ctx)
    if ctx.mode == "live" and not ctx.settings.sec_user_agent:
        raise Skip("SEC_USER_AGENT is not set in .env")
    tickers = ctx.tickers("analyst")
    facts, res = analyst.facts(
        tickers, metrics_path="trader/metrics.json", runner=ctx.runner("analyst_watchlist")
    )
    _checked(res, "analyst")
    with session(ctx.engine) as s:
        store.save_earnings(s, facts or [], ctx.mode)
    failed = f" ({res.status}: {res.stderr.strip().splitlines()[-1]})" if res.status == "partial" else ""
    return f"earnings for {len(facts or [])} of {len(tickers)} tickers{failed}"


def job_daily_scan(ctx: JobContext) -> str:
    need_phase(ctx, "daily_scan", {"premarket"})
    r = ctx.runner("daily_scan")
    if ctx.mode == "live" and not (r.trader_dir / "universe.txt").exists():
        _, res = scanner.universe(runner=r)  # first run: build the universe the scan reads
        _checked(res, "universe")
    scan, res = scanner.daily(runner=r)
    _checked(res, "daily scan")
    with session(ctx.engine) as s:
        store.save_scan(s, scan, ctx.mode)
    return f"{len(scan.hits)} hits of {scan.scanned:,} scanned"


def _news(ctx: JobContext, job: str) -> str:
    tickers = list(dict.fromkeys(ctx.tickers("news") + _pinned(ctx) + _scan_symbols(ctx)))
    result, res = news.check(tickers, runner=ctx.runner(job))
    _checked(res, "news")
    with session(ctx.engine) as s:
        added = store.save_news(s, result, ctx.mode)
    moving = [mv.ticker for mv in result.moves if mv.moving]
    return f"{len(added)} new items for {len(tickers)} tickers" + (
        f"; moving: {', '.join(moving)}" if moving else ""
    )


def job_premarket_news(ctx: JobContext) -> str:
    need_phase(ctx, "premarket_news", {"premarket"})
    return _news(ctx, "premarket_news")


def job_intraday_news(ctx: JobContext) -> str:
    need_phase(ctx, "intraday_news", OPEN_PHASES)
    return _news(ctx, "intraday_news")


def job_regime(ctx: JobContext) -> str:
    need_phase(ctx, "regime", OPEN_PHASES)
    raise Skip("market context arrives in Phase 3")


def job_orb_scan(ctx: JobContext) -> str:
    need_phase(ctx, "orb_scan", {"entry_window"})
    now = ctx.now()
    if now.time() < ORB_FIRST:
        raise Skip("the opening-range scan starts at 9:50")
    if ctx.mode == "replay":
        symbols = None  # the recorded 234-chart wall
    elif ctx.settings.full_universe_orb and now.time().replace(second=0, microsecond=0) == FULL_ORB_AT:
        symbols = None  # the whole universe, once a day
    else:
        symbols = list(dict.fromkeys(ctx.tickers("orb") + _pinned(ctx)))
    scan, res = scanner.orb(symbols, runner=ctx.runner("orb_scan"))
    _checked(res, "orb scan")
    with session(ctx.engine) as s:
        store.save_scan(s, scan, ctx.mode)
    partial = f" (PARTIAL: {scan.unconfirmed} unchecked)" if scan.partial else ""
    return f"{len(scan.hits)} breakouts of {scan.scanned:,} usable charts{partial}"


def job_entry_watch(ctx: JobContext) -> str:
    """Pinned tickers, every minute in the entry window, until each triggers or expires."""
    need_phase(ctx, "entry_watch", {"entry_window"})
    today = f"{ctx.now():%Y-%m-%d}"
    with session(ctx.engine) as s:
        done = {
            sym
            for sym in store.pinned(s, ctx.mode)
            if (e := store.latest_entry(s, ctx.mode, sym, today)) and e.status in ("triggered", "expired")
        }
        symbols = [sym for sym in store.pinned(s, ctx.mode) if sym not in done]
    if not symbols:
        raise Skip("no pinned ticker left to watch" if done else "no pinned tickers")
    changes = []
    for sym in symbols:
        status, res = entry.check(sym, runner=ctx.runner("entry_watch"))
        if status is None:
            changes.append(f"{sym}: {res.message or res.status}")
            continue
        with session(ctx.engine) as s:
            row = store.save_entry(s, status, ctx.mode)
        if row is not None:
            changes.append(
                f"{sym} {status.status}" + (f" at {status.trigger.price}" if status.trigger else "")
            )
    return "; ".join(changes) or f"no change for {', '.join(symbols)}"


def job_quotes(ctx: JobContext) -> str:
    """Fresh prices for sizing and the risk check, while a plan or a position is open."""
    need_phase(ctx, "quotes", OPEN_PHASES)
    r = ctx.runner("quotes")
    plan = read_json(r.trader_dir / "plan.json") or {}
    pf = broker.portfolio(r)
    if plan.get("date") != f"{ctx.now():%Y-%m-%d}" and not (pf and pf.positions):
        raise Skip("no plan for today and no open position")
    result, res = alerts.quote(holdings=True, runner=r)
    _checked(res, "quotes")
    return ", ".join(f"{k} {q.price:.2f}" for k, q in result.quotes.items()) or "no quotes"


def job_alerts_check(ctx: JobContext) -> str:
    need_phase(ctx, "alerts_check", OPEN_PHASES)
    r = ctx.runner("alerts_check")
    today = f"{ctx.now():%Y-%m-%d}"
    if not any(rule.date in (None, today) for rule in alerts.list_rules(r)):
        raise Skip("no alert rules for today")
    result, res = alerts.check(runner=r)
    _checked(res, "alerts")
    with session(ctx.engine) as s:
        fired = store.save_alert_fired(s, result, ctx.mode)
    return "; ".join(f"RANG {a.rule_id}" for a in fired) or "nothing rang"


def job_pelosi(ctx: JobContext) -> str:
    if ctx.now().weekday() >= 5:
        raise Skip("weekend")
    result, res = pelosi.new(runner=ctx.runner("pelosi"))
    _checked(res, "pelosi")
    with session(ctx.engine) as s:
        added = store.save_pelosi(s, result.new, ctx.mode)
    return f"{len(added)} new filings" + (f": {', '.join(f.member for f in added[:3])}" if added else "")


def job_eod_journal(ctx: JobContext) -> str:
    need_phase(ctx, "eod_journal", {"after_close"})
    raise Skip("the end-of-day journal arrives in Phase 7")


JOBS: dict[str, Callable[[JobContext], str]] = {
    "clock": job_clock,
    "universe": job_universe,
    "analyst_watchlist": job_analyst_watchlist,
    "daily_scan": job_daily_scan,
    "premarket_news": job_premarket_news,
    "regime": job_regime,
    "orb_scan": job_orb_scan,
    "intraday_news": job_intraday_news,
    "entry_watch": job_entry_watch,
    "quotes": job_quotes,
    "alerts_check": job_alerts_check,
    "pelosi": job_pelosi,
    "eod_journal": job_eod_journal,
}
assert list(JOBS) == list(SCHEDULE)


def _pinned(ctx: JobContext) -> list[str]:
    with session(ctx.engine) as s:
        return store.pinned(s, ctx.mode)


def _scan_symbols(ctx: JobContext) -> list[str]:
    with session(ctx.engine) as s:
        run = store.latest_scan(s, ctx.mode)
        if run is None or run.session_date != f"{ctx.now():%Y-%m-%d}":
            return []
        return [h.symbol for h in store.scan_hits(s, run)[:NEWS_FROM_SCAN]]


def enabled_jobs(settings: Settings) -> list[str]:
    off = set(settings.disabled_jobs)
    unknown = off - set(JOBS)
    if unknown:
        log.warning("DISABLED_JOBS names unknown jobs: %s", ", ".join(sorted(unknown)))
    return [j for j in JOBS if j not in off]


def run_job(ctx: JobContext, name: str) -> tuple[str, str]:
    """Runs one job and records its heartbeat. Never raises: an error is a status."""
    clock_ny = f"{ctx.now():%Y-%m-%d %H:%M}"
    try:
        detail = JOBS[name](ctx)
        status = "ok"
    except Skip as e:
        status, detail = "skipped", str(e)
    except Exception as e:  # a failing job must not stop the worker
        status, detail = "error", f"{type(e).__name__}: {e}"
        log.exception("job %s failed at %s", name, clock_ny)
    with session(ctx.engine) as s:
        store.heartbeat(s, name, ctx.mode, status, detail, clock_ny)
    level = logging.WARNING if status == "error" else logging.INFO
    log.log(level, "%s %-17s %-7s %s", clock_ny, name, status, detail)
    return status, detail
