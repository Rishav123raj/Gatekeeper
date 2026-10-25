"""The journal's arithmetic, against hand-built bars and hand-calculated answers (task 7.6)."""

from datetime import datetime, time

import pandas as pd
import pytest

from gatekeeper import journal
from gatekeeper.clock import NY
from gatekeeper.journal import Trade
from gatekeeper.skills.models import ExitPlan

PLAN = ExitPlan(
    symbol="TSLA",
    side="buy",
    date="2026-10-19",
    entry=364.18,
    entry_time="10:15 AM",
    stop=358.32,
    target=370.04,
    risk_per_share=5.86,
    flat_by="15:55",
    setup="orb",
)


def bars(*rows, start=(10, 15)):
    """rows of (high, low, close), one 5-minute bar each from `start`."""
    t0 = datetime(2026, 10, 19, *start, tzinfo=NY)
    return pd.DataFrame(
        [
            {"ts": t0 + pd.Timedelta(minutes=5 * i), "open": c, "high": h, "low": lo, "close": c}
            for i, (h, lo, c) in enumerate(rows)
        ]
    )


def test_target_first():
    out = journal.simulate_outcome(PLAN, bars((365, 363, 364.5), (370.5, 364, 370)))
    assert (out.r, out.exit_reason, out.exit_price, out.exit_time) == (1.0, "target", 370.04, "10:20")


def test_stop_first():
    out = journal.simulate_outcome(PLAN, bars((365, 362, 363), (363, 358.0, 358.5), (371, 360, 370)))
    assert (out.r, out.exit_reason, out.exit_time) == (-1.0, "stop", "10:20")


def test_a_bar_touching_both_counts_as_the_stop():
    out = journal.simulate_outcome(PLAN, bars((371, 358, 365)))
    assert (out.r, out.exit_reason) == (-1.0, "stop")


def test_flat_at_flat_by():
    # quiet bars all day: out at the close of the last bar before 15:55, i.e. the 15:50 bar
    n = int((datetime(2026, 10, 19, 15, 55) - datetime(2026, 10, 19, 10, 15)).total_seconds() // 300) + 4
    out = journal.simulate_outcome(PLAN, bars(*[(366, 363, 365.0)] * n))
    assert (out.exit_reason, out.exit_time, out.exit_price) == ("flat", "15:50", 365.0)
    assert out.r == round((365.0 - 364.18) / 5.86, 3) == 0.14


def test_custom_flat_by():
    out = journal.simulate_outcome(PLAN, bars(*[(366, 363, 365.0)] * 30), flat_by=time(11, 0))
    assert (out.exit_reason, out.exit_time) == ("flat", "10:55")


def test_data_ending_early_is_said_so():
    out = journal.simulate_outcome(PLAN, bars((366, 363, 365), (367, 365, 366.68)))
    assert (out.exit_reason, out.r) == ("data_end", round((366.68 - 364.18) / 5.86, 3))


def test_bars_before_the_entry_and_off_grid_ticks_are_ignored():
    b = pd.concat(
        [
            bars((400, 300, 350), start=(10, 0)),  # before 10:15: ignored even though it crosses both
            bars((365, 363, 364.5)),
        ]
    )
    tick = pd.DataFrame(
        [{"ts": datetime(2026, 10, 19, 10, 22, 13, tzinfo=NY), "open": 1, "high": 999, "low": 1, "close": 1}]
    )
    out = journal.simulate_outcome(PLAN, pd.concat([b, tick]))
    assert out.exit_reason == "data_end" and out.exit_time == "10:15"


def test_no_bars():
    assert journal.simulate_outcome(PLAN, bars()).exit_reason == "no_data"


def test_real_r_from_fills():
    assert journal.real_r(PLAN, 364.20, 370.04) == (0.997, "target")
    assert journal.real_r(PLAN, 364.20, 358.30) == (-1.007, "stop")
    assert journal.real_r(PLAN, 364.20, 366.00) == (0.307, "flat")


# --- statistics on 10 trades, answers by hand -------------------------------------------------

RS = [1, -1, 2, -1, -1, 0.5, -1, 1, 0, -1]
VERDICTS = [
    "lean_target",
    "coin_flip",
    "lean_target",
    "coin_flip",
    "lean_stop",
    "lean_target",
    "coin_flip",
    "coin_flip",
    "coin_flip",
    "lean_target",
]


def ten():
    return [
        Trade(
            day=f"2026-10-{19 + i // 5:02d}",
            symbol="TSLA",
            r=r,
            simulated=i % 3 == 0,
            taken=i % 3 != 0,
            followed_rules=i != 4,
            verdict=v,
            setup="orb" if i < 6 else "level",
            entry_time="10:15 AM" if i < 5 else "11:30 AM",
        )
        for i, (r, v) in enumerate(zip(RS, VERDICTS, strict=True))
    ]


def test_stats_by_hand():
    s = journal.stats(ten())
    assert s["n"] == 10
    assert s["win_rate"] == 0.4  # 1, 2, 0.5, 1 won
    assert s["avg_win_r"] == 1.125  # 4.5 / 4
    assert s["avg_loss_r"] == -1.0  # five losses of 1R
    assert (s["total_r"], s["expectancy_r"]) == (-0.5, -0.05)
    assert s["profit_factor"] == 0.9  # 4.5 / 5
    assert s["max_dd_r"] == -2.5  # from +2 down to -0.5
    assert s["longest_losing_streak"] == 2  # the 0R trade breaks the last run
    assert s["adherence_rate"] == 0.9


def test_stats_of_nothing():
    s = journal.stats([Trade(day="2026-10-19", symbol="X", r=None, simulated=False, taken=True)])
    assert (s["n"], s["win_rate"], s["expectancy_r"], s["profit_factor"]) == (0, None, None, None)


def test_calibration_by_hand():
    rows = {r["verdict"]: r for r in journal.calibration(ten())}
    assert rows["lean_target"] == {"verdict": "lean_target", "n": 4, "win_rate": 0.75, "avg_r": 0.625}
    # coin flips: -1, -1, -1, +1, 0 → 1 of 5 won, -2R / 5 = -0.4R
    assert rows["coin_flip"] == {"verdict": "coin_flip", "n": 5, "win_rate": 0.2, "avg_r": -0.4}
    assert rows["lean_stop"] == {"verdict": "lean_stop", "n": 1, "win_rate": 0.0, "avg_r": -1.0}
    assert [r["verdict"] for r in journal.calibration(ten())] == ["lean_target", "coin_flip", "lean_stop"]


def test_breakdowns():
    by_setup = {r["setup"]: r for r in journal.breakdown(ten(), "setup")}
    assert by_setup["orb"]["n"] == 6 and by_setup["orb"]["expectancy_r"] == round(0.5 / 6, 3)
    buckets = {r["entry_bucket"]: r["n"] for r in journal.breakdown(ten(), "entry_bucket")}
    assert buckets == {"09:45–10:30": 5, "10:30–12:00": 5}
    days = {r["weekday"]: r["n"] for r in journal.breakdown(ten(), "weekday")}
    assert days == {"Mon": 5, "Tue": 5}
    with pytest.raises(ValueError):
        journal.breakdown(ten(), "moon")


def test_readiness_card():
    card = journal.readiness_card(ten())
    # taken (real) trades: -1, 2, -1, 0.5, 1, 0 → 6 of them (< 40), +1.5R / 6 = +0.25R (> 0);
    # rules followed in 9 of 10 decisions: 90 % (< 95 %)
    assert [c["ok"] for c in card] == [False, True, False]
    assert [c["value"] for c in card] == [6, 0.25, 0.9]
    many = [Trade(day="2026-10-19", symbol="X", r=0.5, simulated=False, taken=True, followed_rules=True)] * 40
    assert all(c["ok"] for c in journal.readiness_card(many))
