"""The store: skill results into rows, dedupe rules, pins, heartbeats, clearing a mode."""

import json
import threading

import pytest
from sqlmodel import func, select

from gatekeeper import store
from gatekeeper import tables as t
from gatekeeper.contracts import MODELS
from gatekeeper.db import init_db, make_engine, session
from gatekeeper.runner import RunResult
from gatekeeper.settings import ROOT

CONTRACTS = ROOT / "tests" / "contracts"


def load(name):
    model, many = MODELS[name]
    data = json.loads((CONTRACTS / f"{name}.json").read_text(encoding="utf-8"))
    return [model.model_validate(x) for x in data] if many else model.model_validate(data)


@pytest.fixture
def engine(tmp_path):
    return init_db(make_engine(f"sqlite:///{(tmp_path / 'g.db').as_posix()}"))


def count(s, table):
    return s.exec(select(func.count()).select_from(table)).one()


def test_wal_mode(engine):
    with engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


def test_scan_with_hits(engine):
    with session(engine) as s:
        run = store.save_scan(s, load("scanner_orb_1015"), "replay")
    with session(engine) as s:
        run = store.latest_scan(s, "replay", "orb")
        hits = store.scan_hits(s, run)
        assert (run.session_date, run.hits_count, run.scanned, run.partial) == ("2026-10-19", 41, 222, False)
        tsla = next(h for h in hits if h.symbol == "TSLA")
        assert (tsla.or_low, tsla.or_high, tsla.price, tsla.hit_time) == (354.47, 362.18, 364.18, "10:15 AM")
        assert run.payload["hits"] == []  # hits live in their own table
        assert store.latest_scan(s, "live") is None


def test_news_dedupe_on_link(engine):
    news = load("news_tsla")
    with session(engine) as s:
        first = store.save_news(s, news, "replay")
    with session(engine) as s:
        again = store.save_news(s, news, "replay")
        live = store.save_news(s, news, "live")  # modes don't share rows
    assert len(first) == len(news.items) == 16
    assert again == []
    assert len(live) == 16
    with session(engine) as s:
        assert count(s, t.PriceMove) == 3  # the price line is stored on every check
        item = s.exec(select(t.NewsItem).where(t.NewsItem.mode == "replay")).first()
        assert item.published_at.tzinfo is not None  # stored as UTC


def test_entry_only_on_change(engine):
    with session(engine) as s:
        assert store.save_entry(s, load("entry_tsla_1012"), "replay").status == "waiting"
    with session(engine) as s:
        assert store.save_entry(s, load("entry_tsla_1012"), "replay") is None  # same status
        row = store.save_entry(s, load("entry_tsla_1015"), "replay")
        assert (row.status, row.trigger_price, row.trigger_time) == ("triggered", 364.18, "10:15 AM")
    with session(engine) as s:
        assert store.save_entry(s, load("entry_tsla_1015"), "replay") is None
        assert count(s, t.EntrySignal) == 2
        assert store.latest_entry(s, "replay", "TSLA", "2026-10-19").status == "triggered"


def test_plan_tm_and_risk(engine):
    with session(engine) as s:
        plan = store.save_plan(s, load("exit_plan_or_mid_1r"), "replay")
        assert store.save_plan(s, load("exit_plan_or_mid_1r"), "replay").id == plan.id  # same plan
        tm = store.save_tm(s, load("timemachine_run"), "replay", plan.id)
        verdicts = store.save_risk(s, load("risk_check_block_9"), "replay", plan.id)
    assert (plan.stop, plan.target, plan.risk_per_share) == (358.32, 370.04, 5.86)
    assert (tm.p_target, tm.p_stop, tm.hist_fired, tm.hist_target) == (0.2938, 0.2548, 33, 13)
    assert tm.verdict.startswith("Close to a coin flip")
    assert verdicts[0].verdict == "BLOCK" and "$52.74" in verdicts[0].reasons[0]


def test_alerts_earnings_and_congress(engine):
    with session(engine) as s:
        fired = store.save_alert_fired(s, load("alerts_check_1556"), "replay")
        earn = store.save_earnings(s, load("analyst_aapl"), "replay")
        filings = store.save_pelosi(s, load("pelosi_index"), "replay")
    with session(engine) as s:
        assert store.save_pelosi(s, load("pelosi_index"), "replay") == []  # one row per doc id
    assert [(a.rule_id, a.session_date) for a in fired] == [("tsla-flat-by", "2026-10-19")]
    assert (earn[0].symbol, earn[0].revenue, earn[0].eps) == ("AAPL", 109417000000.0, 2.02)
    assert len(filings) == 4 and filings[0].member == "Hon. Nancy Pelosi"


def test_pins(engine):
    with session(engine) as s:
        store.pin(s, "tsla", "replay")
        store.pin(s, "TSLA", "replay")
        store.pin(s, "NVDA", "replay")
    with session(engine) as s:
        assert store.pinned(s, "replay") == ["TSLA", "NVDA"]
        store.unpin(s, "nvda", "replay")
    with session(engine) as s:
        assert store.pinned(s, "replay") == ["TSLA"]
        assert store.pinned(s, "live") == []


def test_heartbeat(engine):
    with session(engine) as s:
        store.heartbeat(s, "clock", "live", "ok", "entry_window", "2026-10-19 10:15")
        store.heartbeat(s, "clock", "live", "error", "RuntimeError: boom")
        store.heartbeat(s, "clock", "live", "skipped", "weekend")
    with session(engine) as s:
        (hb,) = store.heartbeats(s, "live")
    assert (hb.runs, hb.errors, hb.last_status, hb.last_error) == (3, 1, "skipped", "RuntimeError: boom")
    assert hb.last_ok_at is not None


def test_skill_run_logger(engine):
    log = store.skill_run_logger(engine, "replay", "orb_scan")
    log(RunResult("scanner", ["orb", "--json"], "ok", 0, writes_state=True, duration_s=0.9, waited_s=0.1))
    with session(engine) as s:
        row = s.exec(select(t.SkillRun)).one()
    assert (row.tool, row.job, row.writes_state, row.waited_s, row.args) == (
        "scanner",
        "orb_scan",
        True,
        0.1,
        ["orb", "--json"],
    )


def test_concurrent_writers(engine):
    """Worker threads each open their own session; WAL and the busy timeout let them all commit."""

    def work(i):
        for k in range(20):
            with session(engine) as s:
                store.heartbeat(s, f"job{i}", "live", "ok", str(k))

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    with session(engine) as s:
        assert sum(h.runs for h in store.heartbeats(s, "live")) == 80


def test_clear_mode(engine):
    with session(engine) as s:
        store.save_scan(s, load("scanner_orb_1015"), "replay")
        store.save_scan(s, load("scanner_orb_1015"), "live")
        plan = store.save_plan(s, load("exit_plan_or_mid_1r"), "replay")
        store.save_tm(s, load("timemachine_run"), "replay", plan.id)
        store.save_news(s, load("news_tsla"), "replay")
        store.pin(s, "TSLA", "replay")
    with session(engine) as s:
        store.clear_mode(s, "replay")
    with session(engine) as s:
        assert count(s, t.ScanRun) == 1 and count(s, t.ScanHit) == 41  # the live scan stays
        assert count(s, t.Plan) == count(s, t.TmResult) == count(s, t.NewsItem) == 0
        assert store.pinned(s, "replay") == []


def test_pins_keep_insertion_order_with_equal_timestamps(engine):
    """Windows' clock is coarse: pins made in the same instant must still keep their order."""
    from datetime import UTC, datetime

    same = datetime(2026, 10, 19, 14, 15, tzinfo=UTC)
    with session(engine) as s:
        for sym in ("ZZZ", "AAA", "MMM"):
            s.add(t.PinnedTicker(mode="live", symbol=sym, added_at=same))
    with session(engine) as s:
        assert store.pinned(s, "live") == ["ZZZ", "AAA", "MMM"]
