"""Market context: the label rule, the per-index numbers, and replay without index data."""

from datetime import datetime

import pandas as pd
import pytest

from gatekeeper import regime
from gatekeeper.clock import NY
from gatekeeper.regime import SeriesState, evaluate, label, series_state
from gatekeeper.settings import get_settings
from gatekeeper.yahoo import Chart, ReplayYahoo


def chart(closes, highs=None, lows=None, volumes=None, prev=100.0, symbol="SPY"):
    n = len(closes)
    ts = pd.date_range("2026-10-19 09:30", periods=n, freq="5min", tz=NY)
    df = pd.DataFrame(
        {
            "ts": ts,
            "open": closes,
            "high": highs or [c + 0.5 for c in closes],
            "low": lows or [c - 0.5 for c in closes],
            "close": closes,
            "volume": volumes or [1000] * n,
        }
    )
    return Chart(symbol, df, prev, closes[-1])


@pytest.mark.parametrize(
    ("signals", "expected"),
    [
        ({"a": 1, "b": 1, "c": None}, (2, "supportive")),
        ({"a": 1, "b": 1, "c": 1, "d": -1}, (2, "supportive")),
        ({"a": 1, "b": 0, "c": 0}, (1, "mixed")),
        ({"a": 1, "b": -1}, (0, "mixed")),
        ({"a": -1, "b": -1}, (-2, "hostile")),
        ({"a": -1, "b": None, "c": None}, (-1, "unknown")),  # only one signal with data
        ({}, (0, "unknown")),
    ],
)
def test_label_rule(signals, expected):
    assert label(signals) == expected


def test_series_state_numbers():
    st = series_state("SPY", chart([100, 101, 102, 103, 104], volumes=[1, 1, 1, 1, 6]))
    assert st.available and st.price == 104 and st.change_pct == 4.0
    assert st.vwap == pytest.approx(103.0)  # typical price = close here, volume-weighted
    assert st.vs_vwap_pct == pytest.approx(0.97)
    assert (st.or_low, st.or_high, st.vs_or) == (99.5, 102.5, "above")
    assert st.spark == [100, 101, 102, 103, 104]


def test_series_state_daily_average():
    daily = chart([float(x) for x in range(100, 125)])  # 25 daily closes, last 20 average 114.5
    st = series_state("SPY", chart([110, 111, 112]), daily)
    assert st.ma20 == 114.5 and st.ma50 is None
    assert st.vs_ma20_pct == pytest.approx(-2.18)


def test_missing_series():
    assert series_state("^VIX", None) == SeriesState("^VIX")


def s(**kw):
    return SeriesState("X", available=True, **kw)


@pytest.mark.parametrize(
    ("vix_chg", "vix_signal"), [(-1.0, 1), (0.0, 1), (5.0, 0), (9.99, 0), (10.0, -1), (25.0, -1)]
)
def test_vix_thresholds(vix_chg, vix_signal):
    r = evaluate({}, s(price=20, change_pct=vix_chg), None)
    assert r.signals["vix"] == vix_signal


@pytest.mark.parametrize(
    ("breadth", "signal"), [(5.0, -1), (9.9, -1), (10.0, 0), (24.9, 0), (25.0, 1), (60, 1)]
)
def test_breadth_thresholds(breadth, signal):
    assert evaluate({}, SeriesState("^VIX"), breadth).signals["breadth"] == signal


def test_supportive_and_hostile_tapes():
    up = evaluate(
        {"SPY": s(vs_vwap_pct=0.3, vs_ma20_pct=1.0), "QQQ": s(vs_vwap_pct=0.2)},
        s(price=15, change_pct=-3.0),
        30.0,
    )
    assert (up.score, up.label) == (5, "supportive")
    down = evaluate(
        {"SPY": s(vs_vwap_pct=-0.3, vs_ma20_pct=-1.0), "QQQ": s(vs_vwap_pct=-0.2)},
        s(price=25, change_pct=12.0),
        5.0,
    )
    assert (down.score, down.label) == (-5, "hostile")
    assert "SPY below VWAP (-0.30 %)" in down.reasons


def test_replay_has_no_index_data():
    src = ReplayYahoo(
        get_settings().skills_path / "tests" / "fixtures", datetime(2026, 10, 19, 10, 15, tzinfo=NY)
    )
    snap = regime.snapshot(src, breadth_pct=regime.breadth(41, 222))
    assert not any(x.available for x in snap.indexes.values()) and not snap.vix.available
    assert snap.breadth_pct == 18.5 and snap.signals["breadth"] == 0
    assert snap.label == "unknown"
    assert "n/a: spy_vs_vwap, qqq_vs_vwap, spy_vs_ma20, vix" in snap.reasons


def test_breadth():
    assert regime.breadth(41, 222) == 18.5
    assert regime.breadth(3, 0) is None
