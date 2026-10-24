"""The worker rings the flat-by alert once and notifies once (task 6.9); positions read right."""

from datetime import date, time

from sqlmodel import select

from gatekeeper.db import init_db, make_engine, session
from gatekeeper.settings import get_settings
from gatekeeper.skills import alerts, broker, entry, exit
from gatekeeper.skills.models import Portfolio
from gatekeeper.tables import AlertFired
from worker.scheduler import replay_context, simulate

DAY = date(2026, 10, 19)


def plan_with_alerts(tmp_path):
    engine = init_db(make_engine(f"sqlite:///{(tmp_path / 'g.db').as_posix()}"))
    ctx, clock = replay_context(get_settings(), engine, DAY, time(10, 15), workspace=tmp_path / "ws")
    r = ctx.runner("test")
    entry.check("TSLA", write=True, runner=r)
    exit.plan(stop="or-mid", target="1R", runner=r)
    rules, _ = alerts.add_from_plan(runner=r)
    assert {x.id for x in rules} == {"tsla-plan-stop", "tsla-plan-target", "tsla-flat-by"}
    return engine, ctx, clock, r


def test_flat_by_rings_once_and_notifies_once(tmp_path):
    engine, ctx, clock, _ = plan_with_alerts(tmp_path)
    sent = []
    ctx.notifier = lambda title, body, urgent=False: sent.append((title, body, urgent)) or True
    counts = simulate(ctx, clock, DAY, time(15, 40), time(16, 0), ["alerts_check"])
    assert counts[("alerts_check", "ok")] == 10  # every 2 minutes, 15:40 to 15:58 (16:00 is the close)
    assert len(sent) == 1
    title, body, urgent = sent[0]
    assert urgent is True and title == "URGENT · Gatekeeper: TSLA"
    assert body.startswith("Flat by close: it is 15:56 New York (set for 15:55)")
    with session(engine) as s:
        (row,) = s.exec(select(AlertFired)).all()
    assert (row.rule_id, row.fired_ny, row.notified) == ("tsla-flat-by", "2026-10-19 15:56", True)


def test_replays_record_but_do_not_notify(tmp_path):
    engine, ctx, clock, _ = plan_with_alerts(tmp_path)
    assert ctx.notifier is None  # a replay context has no notifier unless one is plugged in
    simulate(ctx, clock, DAY, time(15, 54), time(15, 58), ["alerts_check"])
    with session(engine) as s:
        (row,) = s.exec(select(AlertFired)).all()
    assert row.notified is False


def test_a_failed_notification_is_recorded_as_not_sent(tmp_path):
    engine, ctx, clock, _ = plan_with_alerts(tmp_path)
    ctx.notifier = lambda *a, **k: False
    simulate(ctx, clock, DAY, time(15, 54), time(15, 58), ["alerts_check"])
    with session(engine) as s:
        (row,) = s.exec(select(AlertFired)).all()
    assert row.notified is False


def test_portfolio_reads_the_skills_format(tmp_path):
    """ticket.py writes positions as ticker / shares / lots (the Phase 1 model guessed otherwise)."""
    _, _, _, r = plan_with_alerts(tmp_path)
    broker.fill("TSLA", "buy", 8, 364.20, runner=r)
    pf = broker.portfolio(r)
    assert isinstance(pf, Portfolio) and pf.cash == 2086.4
    (pos,) = pf.positions
    assert (pos.ticker, pos.shares, pos.avg_cost) == ("TSLA", 8.0, 364.2)
    broker.fill("TSLA", "sell", 8, 370.04, runner=r)
    assert broker.portfolio(r).positions == []
