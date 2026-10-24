"""The four Go / No-Go scenarios on the recorded day, end to end through the real skills (task 5.10)."""

import json
from datetime import datetime

import pytest

from gatekeeper import store
from gatekeeper.clock import NY
from gatekeeper.db import init_db, make_engine, session
from gatekeeper.readiness import build_day_context, build_trade_context, evaluate_day, evaluate_trade
from gatekeeper.replay import prepare_workspace
from gatekeeper.runner import SkillRunner
from gatekeeper.settings import get_settings
from gatekeeper.skills import alerts, budget, entry, exit, news, risk, timemachine

S = get_settings()


def ny(h, m):
    return datetime(2026, 10, 19, h, m, tzinfo=NY)


@pytest.fixture(scope="module")
def world(tmp_path_factory, skills_dir):
    """At 10:15: TSLA's news, entry, 1R plan, Time Machine, 8-share bracket and its PASS."""
    tmp = tmp_path_factory.mktemp("gng")
    engine = init_db(make_engine(f"sqlite:///{(tmp / 'g.db').as_posix()}"))
    ctx = prepare_workspace(ny(10, 15).replace(tzinfo=None), tmp / "ws", skills_dir)

    def runner(h, m):
        return SkillRunner.from_settings(replay=ctx.at(datetime(2026, 10, 19, h, m)))

    r = runner(10, 15)
    n, _ = news.check(["TSLA"], runner=r)
    e, _ = entry.check("TSLA", write=True, runner=r)
    p, _ = exit.plan(stop="or-mid", target="1R", runner=r)
    with session(engine) as s:
        store.save_news(s, n, "replay")
        store.save_entry(s, e, "replay")
        plan_id = store.save_plan(s, p, "replay").id
    tm, _ = timemachine.run(runner=r)
    with session(engine) as s:
        store.save_tm(s, tm, "replay", plan_id)
    size, _ = budget.size(runner=r)
    report, _ = risk.check(runner=r)
    return {
        "engine": engine,
        "ctx": ctx,
        "runner": runner,
        "trader": ctx.workspace / "trader",
        "size": size,
        "risk": report,
        "plan_id": plan_id,
    }


def evaluate(w, now, **kw):
    c = build_trade_context(w["engine"], "replay", now, w["trader"], S, "TSLA", **kw)
    return evaluate_trade(c, S)


def reasons(res):
    return {g.name: g.reason for g in res.problems()}


def test_scenario_1_tsla_1015_eight_shares(world):
    res = evaluate(
        world, ny(10, 15), size=world["size"], risk=world["risk"]
    )  # entry, plan, TM from the database
    assert res.overall == "CAUTION"
    r = reasons(res)
    assert r["Time Machine verdict"].startswith(
        "Close to a coin flip: target first 29.4 % vs stop first 25.5 %"
    )
    assert r["Earnings outside the trade"].startswith("earnings are in today's news")
    assert set(r) == {
        "Time Machine verdict",
        "Earnings outside the trade",
        "Reward : risk at the fresh price",
    }
    assert res.plan_id == world["plan_id"]


def test_scenario_2_nine_shares(world):
    doc = json.loads((world["trader"] / "orders.json").read_text(encoding="utf-8"))
    doc["orders"][0]["qty"] = "9"
    (world["trader"] / "orders-9.json").write_text(json.dumps(doc), encoding="utf-8")
    report, _ = risk.check(no_write=True, orders_path="trader/orders-9.json", runner=world["runner"](10, 15))
    res = evaluate(world, ny(10, 15), size=world["size"], risk=report)
    assert res.overall == "NO_TRADE"
    assert reasons(res)["Risk check"] == (
        "BLOCK: loss: 9 shares x 5.86 risk a share = $52.74 at the stop, over your $50 max loss per trade"
    )


def test_scenario_3_at_0940(world):
    report, _ = risk.check(no_write=True, runner=world["runner"](9, 40))
    res = evaluate(world, ny(9, 40), size=world["size"], risk=report)
    assert res.overall == "NO_TRADE"
    assert reasons(res)["Risk check"] == "BLOCK: window: no new entries before 09:45 New York (it is 09:40)"
    day = evaluate_day(build_day_context(world["engine"], "replay", ny(9, 40), world["trader"], S), S)
    assert day.overall == "NO_TRADE"
    assert reasons(day)["Entry window"].startswith("no new entries before 09:45 NY")


def test_scenario_4_quote_36648_at_1055(world):
    r = world["runner"](10, 55)
    alerts.quote(["TSLA"], runner=r)  # the recorded 10:52 quote, 366.475, into trader/prices.json
    size, _ = budget.size(write=False, runner=r)
    report, _ = risk.check(no_write=True, runner=r)
    res = evaluate(world, ny(10, 55), size=size, risk=report)
    assert res.overall == "NO_TRADE"
    rs = reasons(res)
    assert rs["Reward : risk at the fresh price"].startswith("0.44 from the fresh price $366.48")
    assert "$65.28" in rs["Risk check"] and "reward:risk: 0.44" in rs["Risk check"]
    assert rs["Size sane"].startswith("reward:risk 0.44")
    assert "40 min ago" in rs["Entry triggered"]


def test_day_at_1015(world):
    day = evaluate_day(build_day_context(world["engine"], "replay", ny(10, 15), world["trader"], S), S)
    assert day.overall == "CAUTION"  # the default awake hours end at 23:30 IST, flat-by is 01:25 IST
    assert set(reasons(day)) == {"Awake window (IST)"}
