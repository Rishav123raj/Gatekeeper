"""Go / No-Go: every gate's PASS / WARN / FAIL boundaries, the overall rule, and the store."""

import json
from datetime import date, datetime, time

import pytest
from sqlalchemy import text

from gatekeeper import readiness as rd
from gatekeeper import store
from gatekeeper.clock import NY, SessionTimes
from gatekeeper.contracts import MODELS
from gatekeeper.db import init_db, make_engine, session
from gatekeeper.readiness import DayContext, Gate, TradeContext
from gatekeeper.settings import ROOT, get_settings
from gatekeeper.skills.models import BrokerRecord, ClockStatus
from gatekeeper.tables import EarningsSnapshot, NewsItem, PriceMove

S = get_settings()
D = date(2026, 10, 19)  # Monday
CONTRACTS = ROOT / "tests" / "contracts"


def load(name):
    model, many = MODELS[name]
    data = json.loads((CONTRACTS / f"{name}.json").read_text(encoding="utf-8"))
    return [model.model_validate(x) for x in data] if many else model.model_validate(data)


def ny(h, m, d=D):
    return datetime.combine(d, time(h, m), NY)


def clock(d=D, **kw):
    base = dict(
        now_new_york=f"{d} 12:00",
        date=str(d),
        weekday="Monday",
        calendar_known=True,
        open=True,
        reason="regular session",
        opens="09:30",
        closes="16:00",
    )
    return ClockStatus.model_validate({**base, **kw})


def day(h=10, m=15, d=D, **kw):
    c = DayContext(
        now=ny(h, m, d),
        day=kw.pop("cal", clock(d)),
        times=SessionTimes(),
        phase="entry_window",
        config={"max_daily_loss_usd": 150, "max_trades_per_day": 3},
        awake_ist="18:30-01:30",
    )
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def placed(n, loss=46.88, day_=str(D)):
    return [BrokerRecord(status="placed", kind="entry", date=day_, max_loss=loss) for _ in range(n)]


# --- overall --------------------------------------------------------------------------------


def g(status, level="hard"):
    return Gate("x", level, status, "", "")


@pytest.mark.parametrize(
    ("gates", "expected"),
    [
        ([g("PASS"), g("PASS", "soft")], "GO"),
        ([g("PASS"), g("WARN")], "CAUTION"),
        ([g("PASS"), g("FAIL", "soft")], "CAUTION"),
        ([g("WARN"), g("FAIL")], "NO_TRADE"),
        ([g("FAIL", "soft"), g("FAIL")], "NO_TRADE"),
    ],
)
def test_overall_rule(gates, expected):
    assert rd.overall_of(gates) == expected


@pytest.mark.parametrize(
    ("text_", "cat"),
    [
        ("Strongly toward the target: ...", "strong_target"),
        ("Leans toward the target: ...", "lean_target"),
        ("Close to a coin flip: target first 29.4 %", "coin_flip"),
        ("Close to break-even: at 2R ...", "break_even"),
        ("Leans toward the stop: ...", "lean_stop"),
        ("Strongly toward the stop: ...", "strong_stop"),
        ("No replay reached the target or the stop by 4:00 PM", "none"),
        ("something new", "unknown"),
    ],
)
def test_verdict_categories(text_, cat):
    assert rd.verdict_category(text_) == cat


# --- day gates -------------------------------------------------------------------------------


def test_market_open():
    assert rd.g_market_open(day(), S).status == "PASS"
    holiday = day(
        d=date(2026, 11, 26),
        cal=clock(
            date(2026, 11, 26), opens=None, closes=None, open=False, reason="NYSE holiday: Thanksgiving Day"
        ),
    )
    assert rd.g_market_open(holiday, S).reason == "closed: NYSE holiday: Thanksgiving Day"
    assert rd.g_market_open(day(d=date(2026, 10, 24)), S).status == "FAIL"  # Saturday
    early = day(
        d=date(2026, 11, 27),
        cal=clock(date(2026, 11, 27), closes="13:00", early_close="day after Thanksgiving"),
    )
    assert (rd.g_market_open(early, S).status, "13:00" in rd.g_market_open(early, S).reason) == ("WARN", True)
    assert rd.g_market_open(day(phase="after_close"), S).status == "FAIL"
    assert rd.g_market_open(day(8, 30, phase="premarket"), S).reason == "opens 09:30 NY (19:00 IST)"


@pytest.mark.parametrize(
    ("hm", "status"),
    [((9, 40), "FAIL"), ((9, 45), "PASS"), ((15, 14), "PASS"), ((15, 16), "WARN"), ((15, 30), "FAIL")],
)
def test_entry_window(hm, status):
    assert rd.g_entry_window(day(*hm), S).status == status


def test_entry_window_on_an_early_close():
    early = day(12, 20, d=date(2026, 11, 27), cal=clock(date(2026, 11, 27), closes="13:00", early_close="x"))
    gate = rd.g_entry_window(early, S)
    assert gate.status == "WARN" and "09:45–12:30 NY" in gate.reason  # the 15:30 cutoff moves to 12:30
    assert rd.g_entry_window(day(12, 31, d=date(2026, 11, 27), cal=early.day), S).status == "FAIL"


@pytest.mark.parametrize(
    ("awake", "flat", "status"),
    [
        ("18:30-01:30", time(15, 55), "PASS"),  # 15:55 NY = 01:25 IST, inside a window across midnight
        ("18:30-23:30", time(15, 55), "FAIL"),
        ("18:30-23:30", time(12, 0), "PASS"),  # 12:00 NY = 21:30 IST
    ],
)
def test_awake_window(awake, flat, status):
    c = day(awake_ist=awake, times=SessionTimes(flat_by=flat))
    gate = rd.g_awake(c, S)
    assert (gate.status, gate.level) == (status, "soft")


def test_awake_window_after_daylight_saving():
    c = day(d=date(2026, 11, 2), cal=clock(date(2026, 11, 2)), awake_ist="18:30-01:30")
    assert "02:25 IST" in rd.g_awake(c, S).reason and rd.g_awake(c, S).status == "FAIL"  # EST: +10:30


@pytest.mark.parametrize(("n", "status"), [(0, "PASS"), (2, "PASS"), (3, "FAIL")])
def test_daily_loss(n, status):
    c = day(placed_today=placed(n, loss=50.0))
    assert rd.g_daily_loss(c, S).status == ("WARN" if n == 2 else status)  # $100 of $150 = 67 % ≥ 66 %


def test_daily_loss_without_a_limit():
    assert rd.g_daily_loss(day(config={}), S).status == "WARN"


@pytest.mark.parametrize(("n", "status"), [(0, "PASS"), (1, "PASS"), (2, "WARN"), (3, "FAIL")])
def test_trades_left(n, status):
    assert rd.g_trades_left(day(placed_today=placed(n)), S).status == status


@pytest.mark.parametrize(
    ("guard", "n", "status"), [(False, 5, "PASS"), (True, 1, "PASS"), (True, 2, "WARN"), (True, 3, "FAIL")]
)
def test_pdt(guard, n, status):
    c = day(config={"pdt_guard": guard}, day_trades_5d=n)
    assert rd.g_pdt(c, S).status == status


def regime(spy_vwap=0.2, spy_or="above", vix_chg=1.0):
    return {
        "label": "mixed",
        "score": 0,
        "indexes": {"SPY": {"vs_vwap_pct": spy_vwap, "vs_or": spy_or}},
        "vix": {"change_pct": vix_chg},
    }


@pytest.mark.parametrize(
    ("reg", "status"),
    [
        (None, "PASS"),
        (regime(), "PASS"),
        (regime(vix_chg=10.5), "WARN"),
        (regime(-0.3, "below"), "WARN"),
        (regime(-0.3, "inside"), "PASS"),
    ],
)
def test_market_context(reg, status):
    gate = rd.g_market_context(day(regime=reg), S)
    assert (gate.status, gate.level) == (status, "soft")


@pytest.mark.parametrize(("pct", "status"), [(None, "PASS"), (9.9, "WARN"), (10.0, "PASS"), (18.5, "PASS")])
def test_breadth(pct, status):
    assert rd.g_breadth(day(breadth_pct=pct), S).status == status


def test_recent_form():
    assert rd.g_recent_form(day(), S).reason == "no journal yet"
    assert rd.g_recent_form(day(form_r=[-1, -1, -1, 0, 0]), S).status == "WARN"  # -3R: at the threshold
    assert rd.g_recent_form(day(form_r=[1, -1, -1, 0, 0]), S).status == "PASS"
    assert rd.g_recent_form(day(form_followed=[True, False, False]), S).status == "WARN"
    assert rd.g_recent_form(day(form_followed=[True]), S).reason == (
        "no journal trades yet; rules followed in 1 of the last 1 decisions"
    )


def test_recent_form_boundary():
    gate = rd.g_recent_form(day(form_r=[-1, -1, -1, 1, 0]), S)  # -2R is above the -3R threshold
    assert (gate.status, gate.reason) == ("PASS", "last 5 trades -2.0R")


# --- trade gates -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tsla():
    return {
        "entry": load("entry_tsla_1015"),
        "waiting": load("entry_tsla_1012"),
        "plan": load("exit_plan_or_mid_1r"),
        "tm": load("timemachine_run"),
        "size": load("budget_size"),
        "pass": load("risk_check_pass"),
        "block": load("risk_check_block_9"),
    }


def trade(t, h=10, m=15, **kw):
    base = dict(
        now=ny(h, m),
        symbol="TSLA",
        entry=t["entry"],
        plan=t["plan"],
        tm=t["tm"],
        size=t["size"],
        risk=t["pass"],
        min_rr=1.0,
    )
    return TradeContext(**{**base, **kw})


def news(tags=(), important=False, items=()):
    return NewsItem(
        mode="replay",
        key="k",
        item_id="i",
        symbol="TSLA",
        title="headline",
        tags=list(tags),
        important=important,
        items_8k=list(items),
    )


def test_entry_gate(tsla):
    assert rd.g_entry(trade(tsla), S).status == "PASS"
    assert rd.g_entry(trade(tsla, 10, 20), S).status == "PASS"  # one bar old
    assert rd.g_entry(trade(tsla, 10, 21), S).status == "WARN"  # more than one bar old
    assert rd.g_entry(trade(tsla, entry=tsla["waiting"]), S).status == "FAIL"
    assert rd.g_entry(trade(tsla, entry=None), S).reason == "the entry hasn't been checked"


@pytest.mark.parametrize(
    ("items", "status"),
    [
        ([], "PASS"),
        ([news(["earnings", "deal"])], "PASS"),
        ([news(["legal"])], "WARN"),
        ([news(important=True, items=["2.02"])], "FAIL"),
        ([news(important=True, items=["8.01"])], "PASS"),
        ([news(["halt"])], "FAIL"),
    ],
)
def test_news_gate(tsla, items, status):
    assert rd.g_news(trade(tsla, news=items), S).status == status


def test_moving_without_a_headline(tsla):
    move = PriceMove(mode="r", symbol="TSLA", pct=3.3, moving=True)
    assert rd.g_news(trade(tsla, move=move), S).status == "WARN"
    assert rd.g_news(trade(tsla, move=move, news=[news()]), S).status == "PASS"


@pytest.mark.parametrize(
    ("report", "news_tags", "status"),
    [
        (None, [], "PASS"),
        (None, ["earnings"], "WARN"),
        ("2026-10-19", [], "FAIL"),  # reports today
        ("2026-10-22", [], "WARN"),  # Thursday: 3 sessions away
        ("2026-10-23", [], "PASS"),  # Friday: 4 sessions away
    ],
)
def test_earnings_gate(tsla, report, news_tags, status):
    er = EarningsSnapshot(mode="r", symbol="TSLA", next_report_date=report) if report else None
    assert (
        rd.g_earnings(trade(tsla, earnings=er, news=[news(news_tags)] if news_tags else []), S).status
        == status
    )


def test_plan_gate(tsla):
    assert rd.g_plan(trade(tsla), S).status == "PASS"
    tight = tsla["plan"].model_copy(update={"stop": 363.50, "risk_per_share": 0.68})  # 0.19 %
    assert rd.g_plan(trade(tsla, plan=tight), S).status == "WARN"
    assert rd.g_plan(trade(tsla, plan=None, plan_error="the stop is above the entry"), S).reason == (
        "the stop is above the entry"
    )


@pytest.mark.parametrize(
    ("price", "min_rr", "status"),
    [
        (None, 1.0, "WARN"),
        (None, 0.8, "PASS"),
        (None, 1.2, "FAIL"),
        (366.475, 1.0, "FAIL"),
        (360.0, 1.0, "WARN"),
    ],
)
def test_reward_risk_gate(tsla, price, min_rr, status):
    gate = rd.g_reward_risk(trade(tsla, fresh_price=price, min_rr=min_rr), S)
    assert gate.status == status
    if price == 366.475:
        assert gate.reason.startswith("0.44 from the fresh price $366.48")
    if price == 360.0:
        assert "the plan's entry" in gate.reason  # a lower price never shrinks the risk


def tm_with(tsla, verdict, p_neither=0.2, triggered=33, target=13, stop=15):
    tm = tsla["tm"]
    return tm.model_copy(
        update={
            "verdict": verdict,
            "mc": tm.mc.model_copy(update={"p_neither": p_neither}),
            "history": tm.history.model_copy(update={"triggered": triggered, "target": target, "stop": stop}),
        }
    )


@pytest.mark.parametrize(
    ("verdict", "neither", "status"),
    [
        ("Strongly toward the target: x.", 0.2, "PASS"),
        ("Leans toward the target: x.", 0.2, "PASS"),
        ("Leans toward the target: x.", 0.45, "WARN"),
        ("Close to a coin flip: x.", 0.2, "WARN"),
        ("Close to break-even: x.", 0.2, "WARN"),
        ("Leans toward the stop: x.", 0.2, "FAIL"),
        ("Strongly toward the stop: x.", 0.2, "FAIL"),
    ],
)
def test_time_machine_gate(tsla, verdict, neither, status):
    assert rd.g_time_machine(trade(tsla, tm=tm_with(tsla, verdict, neither)), S).status == status


def test_time_machine_gate_needs_this_plan(tsla):
    assert rd.g_time_machine(trade(tsla, tm=None), S).status == "FAIL"
    other = tsla["plan"].model_copy(update={"target": 375.9})
    assert "different plan" in rd.g_time_machine(trade(tsla, plan=other), S).reason


def test_history_gate(tsla):
    assert rd.g_history(trade(tsla), S).status == "PASS"  # coin flip: nothing to disagree with
    few = tm_with(tsla, "Leans toward the target: x.", triggered=10)
    assert rd.g_history(trade(tsla, tm=few), S).status == "WARN"
    disagree = tm_with(tsla, "Leans toward the target: x.", target=10, stop=15)  # 40 % < 50 % at 1R
    assert rd.g_history(trade(tsla, tm=disagree), S).status == "WARN"
    agree = tm_with(tsla, "Leans toward the target: x.", target=16, stop=12)
    assert rd.g_history(trade(tsla, tm=agree), S).status == "PASS"
    assert rd.g_history(trade(tsla), S).level == "soft"


def test_risk_and_size_gates(tsla):
    assert rd.g_risk(trade(tsla), S).reason == "PASS: max loss $46.88, reward:risk 1.0"
    assert "$52.74" in rd.g_risk(trade(tsla, risk=tsla["block"]), S).reason
    assert rd.g_risk(trade(tsla, risk=None), S).status == "FAIL"
    assert rd.g_size(trade(tsla), S).status == "PASS"
    assert rd.g_size(trade(tsla, size=None), S).status == "FAIL"
    cash = tsla["size"].model_copy(
        update={"sizing": tsla["size"].sizing.model_copy(update={"bound_by": "cash"})}
    )
    assert rd.g_size(trade(tsla, size=cash), S).status == "WARN"


def test_documented_trade_is_caution(tsla):
    res = rd.evaluate_trade(trade(tsla, news=[news(["earnings", "deal"])]), S)
    assert res.overall == "CAUTION"
    assert [g.name for g in res.problems()] == [
        "Earnings outside the trade",
        "Reward : risk at the fresh price",
        "Time Machine verdict",
    ]


# --- store -----------------------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path):
    return init_db(make_engine(f"sqlite:///{(tmp_path / 'g.db').as_posix()}"))


def test_readiness_storage_skips_unchanged_repeats(engine, tsla):
    res = rd.evaluate_trade(trade(tsla), S)
    with session(engine) as s:
        a = store.save_readiness(s, res, "replay")
        b = store.save_readiness(s, res, "replay")  # same result, same reasons, just now: not stored again
    assert a.id == b.id
    worse = rd.evaluate_trade(trade(tsla, risk=tsla["block"]), S)
    with session(engine) as s:
        c = store.save_readiness(s, worse, "replay")
        assert c.id != a.id and c.overall == "NO_TRADE"
        assert store.save_readiness(s, res, "replay", min_minutes=0).id not in (a.id, c.id)


def test_decision_is_logged_with_its_result(engine, tsla):
    res = rd.evaluate_trade(trade(tsla), S)
    with session(engine) as s:
        rid = store.save_readiness(s, res, "replay").id
        store.save_decision(
            s,
            "replay",
            "SKIPPED",
            plan_id=None,
            symbol="TSLA",
            note="coin flip",
            followed_rules=True,
            readiness_id=rid,
            overall=res.overall,
        )
    with session(engine) as s:
        (d,) = store.decisions(s, "replay")
    assert (d.action, d.symbol, d.overall, d.reason_note, d.followed_rules, d.readiness_id) == (
        "SKIPPED",
        "TSLA",
        "CAUTION",
        "coin flip",
        True,
        rid,
    )
    with session(engine) as s, pytest.raises(ValueError):
        store.save_decision(s, "replay", "MAYBE", plan_id=None, symbol="TSLA")


def test_old_databases_get_the_new_columns(tmp_path):
    """A database made before Phase 5 lacks Decision.overall etc.; init_db adds them."""
    path = tmp_path / "old.db"
    eng = make_engine(f"sqlite:///{path.as_posix()}")
    with eng.begin() as c:
        c.execute(
            text(
                "CREATE TABLE decision (id INTEGER PRIMARY KEY, mode VARCHAR, plan_id INTEGER, ts DATETIME, "
                "action VARCHAR, reason_note VARCHAR, followed_rules BOOLEAN)"
            )
        )
        c.execute(
            text(
                "INSERT INTO decision (mode, action, reason_note, followed_rules) "
                "VALUES ('live', 'TAKEN', '', 1)"
            )
        )
    init_db(eng)
    with eng.connect() as c:
        cols = {r[1] for r in c.execute(text("PRAGMA table_info(decision)"))}
        assert {"symbol", "readiness_id", "overall"} <= cols
        assert c.execute(text("SELECT action FROM decision")).scalar() == "TAKEN"  # the old row is kept
