"""Turning skill results into rows, and reading back what the worker and UI need.

Every function takes an open session and a mode ("live" or "replay"); the caller commits
(`with db.session() as s:` does).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, literal_column
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from gatekeeper.runner import RunResult
from gatekeeper.skills import models as m
from gatekeeper.tables import (
    MODE_TABLES,
    AlertFired,
    EarningsSnapshot,
    EntrySignal,
    JobHeartbeat,
    NewsItem,
    PelosiFiling,
    PinnedTicker,
    Plan,
    PriceMove,
    RegimeSnapshot,
    RiskVerdict,
    ScanHit,
    ScanRun,
    SkillRun,
    TmResult,
    utcnow,
)

IMPORTANT_TAGS = {"earnings", "halt", "legal", "regulatory", "risk"}


def dump(model: Any) -> Any:
    return model.model_dump(mode="json", by_alias=True) if hasattr(model, "model_dump") else model


def parse_utc(value: str | None) -> datetime | None:
    """An ISO time from a skill ("...Z" or with an offset) in UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


# --- skill runs ------------------------------------------------------------------------------


def save_skill_run(s: Session, res: RunResult, mode: str, job: str | None = None) -> SkillRun:
    row = SkillRun(
        mode=mode,
        tool=res.tool,
        args=res.args,
        status=res.status,
        exit_code=res.exit_code,
        message=res.message[:500],
        stderr_excerpt=res.stderr.strip()[-500:],
        writes_state=res.writes_state,
        started_at=res.started_at.astimezone(UTC),
        duration_s=res.duration_s,
        waited_s=res.waited_s,
        job=job,
    )
    s.add(row)
    return row


def skill_run_logger(engine: Engine, mode: str, job: str | None = None) -> Callable[[RunResult], None]:
    """An `on_result` hook for SkillRunner: one SkillRun row per call (task 2.3)."""
    from gatekeeper.db import session

    def log(res: RunResult) -> None:
        with session(engine) as s:
            save_skill_run(s, res, mode, job)

    return log


# --- scans -----------------------------------------------------------------------------------


def save_scan(s: Session, scan: m.ScanResult, mode: str) -> ScanRun:
    session_date = (scan.as_of or scan.created_at)[:10]
    if scan.mode == "daily":
        session_date = scan.created_at[:10]
    run = ScanRun(
        mode=mode,
        scan_mode=scan.mode,
        session_date=session_date,
        as_of=scan.as_of,
        universe=scan.universe,
        scanned=scan.scanned,
        failed=scan.failed,
        unconfirmed=scan.unconfirmed,
        candidates=scan.counts.candidates if scan.counts else None,
        hits_count=len(scan.hits),
        partial=scan.partial,
        payload=dump(scan.model_copy(update={"hits": []})),
    )
    s.add(run)
    s.flush()
    for rank, h in enumerate(scan.hits, 1):
        s.add(
            ScanHit(
                scan_run_id=run.id,
                rank=rank,
                symbol=h.symbol,
                setups=",".join(h.setups),
                price=h.price,
                hit_time=h.at,
                or_high=h.or_high,
                or_low=h.or_low,
                pct_over=h.pct_over,
                rsi=h.rsi,
                volume=h.volume,
                payload=dump(h),
            )
        )
    return run


def latest_scan(s: Session, mode: str, scan_mode: str | None = None) -> ScanRun | None:
    q = select(ScanRun).where(ScanRun.mode == mode)
    if scan_mode:
        q = q.where(ScanRun.scan_mode == scan_mode)
    return s.exec(q.order_by(col(ScanRun.id).desc())).first()


def scan_hits(s: Session, run: ScanRun) -> list[ScanHit]:
    return list(s.exec(select(ScanHit).where(ScanHit.scan_run_id == run.id).order_by(col(ScanHit.rank))))


# --- news ------------------------------------------------------------------------------------


def save_news(s: Session, news: m.NewsResult, mode: str) -> list[NewsItem]:
    """New stories only (one row per link), plus each ticker's price line. Returns the new rows."""
    added: list[NewsItem] = []
    for it in news.items:
        key = it.link or it.id
        exists = s.exec(select(NewsItem.id).where(NewsItem.mode == mode, NewsItem.key == key)).first()
        if exists is not None or any(a.key == key for a in added):
            continue
        row = NewsItem(
            mode=mode,
            key=key,
            item_id=it.id,
            symbol=it.ticker,
            published_at=parse_utc(it.time),
            source=it.source,
            kind=it.kind,
            title=it.title,
            link=it.link,
            tags=it.tags,
            touches=it.touches,
            form=it.form,
            items_8k=it.items,
            important=it.important,
            payload=dump(it),
        )
        s.add(row)
        added.append(row)
    checked = parse_utc(news.checked) or utcnow()
    for mv in news.moves:
        s.add(
            PriceMove(
                mode=mode,
                symbol=mv.ticker,
                checked_at=checked,
                price=mv.price,
                prev_close=mv.prev_close,
                pct=mv.pct,
                moving=mv.moving,
                quote_time=parse_utc(mv.time),
            )
        )
    return added


# --- entries ---------------------------------------------------------------------------------


def latest_entry(s: Session, mode: str, symbol: str, session_date: str) -> EntrySignal | None:
    q = select(EntrySignal).where(
        EntrySignal.mode == mode, EntrySignal.symbol == symbol, EntrySignal.session_date == session_date
    )
    return s.exec(q.order_by(col(EntrySignal.id).desc())).first()


def save_entry(s: Session, st: m.EntryStatus, mode: str) -> EntrySignal | None:
    """Stores the check only when the status (or the trigger) changed since the last one."""
    last = latest_entry(s, mode, st.symbol, st.date)
    trig = st.trigger
    if (
        last is not None
        and last.status == st.status
        and last.setup == st.setup
        and (last.trigger_price == (trig.price if trig else None))
    ):
        return None
    row = EntrySignal(
        mode=mode,
        symbol=st.symbol,
        setup=st.setup,
        session_date=st.date,
        status=st.status,
        level=st.level,
        last_close=(st.last or {}).get("close"),
        trigger_time=trig.time if trig else None,
        trigger_price=trig.price if trig else None,
        reason=st.reason,
        checked_ny=st.now,
        payload=dump(st),
    )
    s.add(row)
    return row


# --- plan, time machine, risk ----------------------------------------------------------------


def save_plan(s: Session, plan: m.ExitPlan, mode: str) -> Plan:
    """A new row unless the latest plan for that symbol and day is the same plan."""
    q = select(Plan).where(Plan.mode == mode, Plan.symbol == plan.symbol, Plan.date == plan.date)
    last = s.exec(q.order_by(col(Plan.id).desc())).first()
    if last is not None and (last.entry, last.stop, last.target, last.flat_by) == (
        plan.entry,
        plan.stop,
        plan.target,
        plan.flat_by,
    ):
        return last
    row = Plan(
        mode=mode,
        symbol=plan.symbol,
        date=plan.date,
        setup=plan.setup,
        entry=plan.entry,
        entry_time=plan.entry_time,
        stop=plan.stop,
        stop_rule=plan.stop_rule,
        target=plan.target,
        target_r=plan.target_r,
        risk_per_share=plan.risk_per_share,
        reward_risk=plan.reward_risk,
        flat_by=plan.flat_by,
        payload=dump(plan),
    )
    s.add(row)
    s.flush()
    return row


def save_tm(s: Session, tm: m.TimeMachineResult, mode: str, plan_id: int | None = None) -> TmResult:
    mc, h = tm.mc, tm.history
    row = TmResult(
        mode=mode,
        plan_id=plan_id,
        symbol=tm.plan.get("symbol"),
        seed=mc.seed,
        replays=mc.replays,
        until=mc.until,
        p_target=mc.p_target,
        p_stop=mc.p_stop,
        p_neither=mc.p_neither,
        p_green=mc.p_green,
        avg_r=mc.avg_R,
        hist_sessions=h.sessions if h else None,
        hist_fired=h.triggered if h else None,
        hist_target=h.target if h else None,
        hist_stop=h.stop if h else None,
        hist_neither=h.close if h else None,
        hist_avg_r=h.avg_R if h else None,
        verdict=tm.verdict,
        payload=dump(tm),
    )
    s.add(row)
    return row


def save_risk(s: Session, report: m.RiskReport, mode: str, plan_id: int | None = None) -> list[RiskVerdict]:
    rows = [
        RiskVerdict(
            mode=mode,
            plan_id=plan_id,
            session_date=report.date,
            checked_ny=report.now_new_york,
            order_index=v.index,
            symbol=v.symbol,
            side=v.side,
            kind=v.kind,
            verdict=v.verdict,
            max_loss=v.max_loss,
            reward_risk=v.reward_risk,
            fingerprint=v.fingerprint,
            reasons=v.reasons,
            warnings=v.warnings,
            payload=dump(v),
        )
        for v in report.results
    ]
    s.add_all(rows)
    return rows


# --- alerts, earnings, congress --------------------------------------------------------------


def save_alert_fired(s: Session, check: m.AlertCheck, mode: str) -> list[AlertFired]:
    rows = [
        AlertFired(
            mode=mode,
            rule_id=r.id,
            symbol=r.symbol,
            message=r.message,
            session_date=check.market.date,
            fired_ny=check.market.now_new_york,
        )
        for r in check.rings
    ]
    s.add_all(rows)
    return rows


def save_earnings(s: Session, facts: list[m.EarningsFacts], mode: str) -> list[EarningsSnapshot]:
    rows = []
    for f in facts:
        q = f.result.rows[0] if f.result.rows else None
        flags = [n for n in [f.note] if n]
        if q and q.derived:
            flags.append("derived quarter")
        if (
            q
            and q.net_income is not None
            and q.operating_income is not None
            and q.net_income > q.operating_income
        ):
            flags.append("net income above operating income")
        rows.append(
            EarningsSnapshot(
                mode=mode,
                symbol=f.ticker,
                period_end=q.end if q else None,
                fiscal=q.fiscal if q else None,
                revenue=q.revenue if q else None,
                rev_yoy=q.revenue_yoy if q else None,
                eps=q.eps_diluted if q else None,
                eps_yoy=q.eps_yoy if q else None,
                gross_m=q.gross_margin if q else None,
                op_m=q.operating_margin if q else None,
                net_m=q.net_margin if q else None,
                flags=flags,
                payload=dump(f),
            )
        )
    s.add_all(rows)
    return rows


def save_pelosi(
    s: Session,
    filings: list[m.PtrFiling],
    mode: str,
    holdings: set[str] | None = None,
    reports: dict[str, m.PtrReport] | None = None,
) -> list[PelosiFiling]:
    """New filings only (one row per doc id)."""
    added = []
    for f in filings:
        exists = s.exec(
            select(PelosiFiling.id).where(PelosiFiling.mode == mode, PelosiFiling.doc_id == f.doc_id)
        ).first()
        if exists is not None:
            continue
        rep = (reports or {}).get(f.doc_id)
        rows = [dump(r) for r in rep.rows] if rep else None
        overlap = bool(holdings and rep and any(r.ticker in holdings for r in rep.rows))
        row = PelosiFiling(
            mode=mode,
            doc_id=f.doc_id,
            member=f.name,
            district=f.district,
            filing_type=f.type,
            filed=f.filed,
            url=f.url,
            rows=rows,
            overlaps_holdings=overlap,
            payload=dump(f),
        )
        s.add(row)
        added.append(row)
    return added


# --- pins and heartbeats ---------------------------------------------------------------------


def pin(s: Session, symbol: str, mode: str, note: str = "") -> None:
    if s.get(PinnedTicker, (mode, symbol.upper())) is None:
        s.add(PinnedTicker(mode=mode, symbol=symbol.upper(), note=note))


def unpin(s: Session, symbol: str, mode: str) -> None:
    row = s.get(PinnedTicker, (mode, symbol.upper()))
    if row is not None:
        s.delete(row)


def pinned(s: Session, mode: str) -> list[str]:
    """Pinned tickers in the order they were pinned.

    Ordered by SQLite's rowid (insertion order), not `added_at`: two pins added in the same
    instant can share a timestamp (Windows' clock ticks about every 15 ms), which made the
    order arbitrary.
    """
    q = select(PinnedTicker.symbol).where(PinnedTicker.mode == mode).order_by(literal_column("rowid"))
    return list(s.exec(q))


def heartbeat(
    s: Session, job: str, mode: str, status: str, detail: str = "", clock_ny: str | None = None
) -> None:
    hb = s.get(JobHeartbeat, (mode, job)) or JobHeartbeat(mode=mode, job=job)
    now = utcnow()
    hb.last_run_at, hb.last_run_ny, hb.last_status, hb.last_detail = now, clock_ny, status, detail[:500]
    hb.runs += 1
    if status == "error":
        hb.errors += 1
        hb.last_error, hb.last_error_at = detail[:500], now
    else:
        hb.last_ok_at = now
    s.add(hb)


def heartbeats(s: Session, mode: str) -> list[JobHeartbeat]:
    return list(s.exec(select(JobHeartbeat).where(JobHeartbeat.mode == mode).order_by(col(JobHeartbeat.job))))


def clear_mode(s: Session, mode: str) -> None:
    """Deletes every row of one mode (used to start a replay from scratch)."""
    runs = select(ScanRun.id).where(ScanRun.mode == mode)
    s.exec(delete(ScanHit).where(col(ScanHit.scan_run_id).in_(runs)))
    s.exec(delete(ScanRun).where(ScanRun.mode == mode))
    for table in MODE_TABLES:
        s.exec(delete(table).where(table.mode == mode))


# --- reads for the dashboard (Phase 3) -------------------------------------------------------


def save_regime(s: Session, regime: Any, mode: str) -> RegimeSnapshot:
    spy, qqq, iwm = (regime.indexes.get(k) for k in ("SPY", "QQQ", "IWM"))
    row = RegimeSnapshot(
        mode=mode,
        spy_chg=spy.change_pct if spy else None,
        qqq_chg=qqq.change_pct if qqq else None,
        iwm_chg=iwm.change_pct if iwm else None,
        spy_vs_vwap=spy.vs_vwap_pct if spy else None,
        vix=regime.vix.price,
        vix_chg=regime.vix.change_pct,
        breadth_orb_up=regime.breadth_pct,
        label=regime.label,
        payload=regime.to_dict(),
    )
    s.add(row)
    return row


def latest_regime(s: Session, mode: str) -> RegimeSnapshot | None:
    q = select(RegimeSnapshot).where(RegimeSnapshot.mode == mode).order_by(col(RegimeSnapshot.id).desc())
    return s.exec(q).first()


def scan_runs(s: Session, mode: str, scan_mode: str, day: str) -> list[ScanRun]:
    q = select(ScanRun).where(
        ScanRun.mode == mode, ScanRun.scan_mode == scan_mode, ScanRun.session_date == day
    )
    return list(s.exec(q.order_by(col(ScanRun.id))))


def news_items(
    s: Session,
    mode: str,
    *,
    symbols: list[str] | None = None,
    since: datetime | None = None,
    limit: int = 200,
) -> list[NewsItem]:
    q = select(NewsItem).where(NewsItem.mode == mode)
    if symbols:
        q = q.where(col(NewsItem.symbol).in_(symbols))
    if since is not None:
        q = q.where(col(NewsItem.published_at) >= since)
    return list(s.exec(q.order_by(col(NewsItem.published_at).desc()).limit(limit)))


def is_important(item: NewsItem) -> bool:
    return item.important or bool(set(item.tags or []) & IMPORTANT_TAGS)


def latest_moves(s: Session, mode: str) -> dict[str, PriceMove]:
    """The newest price line per ticker."""
    out: dict[str, PriceMove] = {}
    for mv in s.exec(select(PriceMove).where(PriceMove.mode == mode).order_by(col(PriceMove.id).desc())):
        out.setdefault(mv.symbol, mv)
    return out


def entries_for_day(s: Session, mode: str, day: str) -> dict[str, EntrySignal]:
    """The latest entry status per ticker for one session."""
    q = select(EntrySignal).where(EntrySignal.mode == mode, EntrySignal.session_date == day)
    out: dict[str, EntrySignal] = {}
    for e in s.exec(q.order_by(col(EntrySignal.id).desc())):
        out.setdefault(e.symbol, e)
    return out


def alerts_for_day(s: Session, mode: str, day: str) -> list[AlertFired]:
    q = select(AlertFired).where(AlertFired.mode == mode, AlertFired.session_date == day)
    return list(s.exec(q.order_by(col(AlertFired.id).desc())))


def latest_earnings(s: Session, mode: str) -> dict[str, EarningsSnapshot]:
    out: dict[str, EarningsSnapshot] = {}
    q = (
        select(EarningsSnapshot)
        .where(EarningsSnapshot.mode == mode)
        .order_by(col(EarningsSnapshot.id).desc())
    )
    for e in s.exec(q):
        out.setdefault(e.symbol, e)
    return out


def set_next_report_date(s: Session, symbol: str, mode: str, day: str | None) -> EarningsSnapshot:
    """Records (or clears) the next earnings date by hand: on the latest snapshot, or a new one."""
    row = latest_earnings(s, mode).get(symbol.upper()) or EarningsSnapshot(mode=mode, symbol=symbol.upper())
    row.next_report_date = day
    s.add(row)
    return row
