"""The Trade Lab's figures, built from the recorded TSLA data."""

import json
from datetime import datetime

import pytest

from app.components import charts
from gatekeeper.clock import NY
from gatekeeper.settings import ROOT, get_settings
from gatekeeper.skills.models import TimeMachineResult
from gatekeeper.yahoo import ReplayYahoo

D = (2026, 10, 19)


def ny(h, m):
    return datetime(*D, h, m, tzinfo=NY)


@pytest.fixture(scope="module")
def bars():
    return ReplayYahoo(get_settings().skills_path / "tests" / "fixtures", ny(10, 15)).chart("TSLA").bars


@pytest.fixture(scope="module")
def tm():
    doc = json.loads((ROOT / "tests" / "contracts" / "timemachine_run.json").read_text(encoding="utf-8"))
    # the printed JSON has no sample paths; give it a few, as the written file has
    doc["mc"]["sample_paths"] = [[364.18 + i * 0.1] * len(doc["mc"]["band_times"]) for i in range(60)]
    return TimeMachineResult.model_validate(doc)


def test_candles_with_all_levels(bars):
    fig = charts.candles_with_levels(
        bars,
        362.18,
        354.47,
        364.18,
        358.32,
        370.04,
        ny(10, 10),
        364.18,
        ny(15, 55),
        session=(ny(9, 30), ny(16, 0)),
    )
    assert [t.type for t in fig.data] == ["candlestick", "bar", "scatter"]
    candles, volume, trigger = fig.data
    assert len(candles.x) == len(bars) == 9  # 9:30 to the 10:10 bar, closed by 10:15
    assert candles.text[0] == "19:00 IST"  # 9:30 NY
    assert (trigger.x[0], trigger.y[0]) == (ny(10, 10), 364.18)
    notes = [a.text for a in fig.layout.annotations]
    assert notes == [
        "opening range 354.47 – 362.18",
        "entry 364.18",
        "stop 358.32",
        "target 370.04",
        "flat by 15:55",
    ]
    hlines = sorted(s.y0 for s in fig.layout.shapes if s.type == "line" and s.y0 == s.y1)
    assert hlines == [358.32, 364.18, 370.04]
    band = next(s for s in fig.layout.shapes if s.type == "rect")
    assert (band.y0, band.y1) == (354.47, 362.18)
    assert list(fig.layout.xaxis.range) == [ny(9, 30), ny(16, 0)]


def test_candles_without_a_plan(bars):
    fig = charts.candles_with_levels(bars)
    assert [t.type for t in fig.data] == ["candlestick", "bar"]
    assert not fig.layout.shapes


def test_odds_bar(tm):
    fig = charts.tm_odds_bar(tm)
    assert [t.type for t in fig.data] == ["bar", "bar", "bar", "scatter"]
    assert [round(t.x[0], 2) for t in fig.data] == [29.38, 25.48, 45.14, 51.68]
    assert fig.data[2].name == "neither by 16:00"
    assert sum(t.x[0] for t in fig.data[:3]) == pytest.approx(100, abs=0.05)


def test_fan(tm):
    fig = charts.tm_fan(tm, max_paths=50)
    paths = [t for t in fig.data if t.hoverinfo == "skip" and t.fill is None and t.line.width == 1]
    assert len(paths) == 50
    median = next(t for t in fig.data if t.name == "median")
    assert len(median.y) == len(tm.mc.band_times) == 70
    assert median.y[0] == tm.mc.bands[0][2]
    assert sorted(s.y0 for s in fig.layout.shapes) == [358.32, 364.18, 370.04]


def test_close_histogram(tm):
    fig = charts.tm_close_hist(tm)
    bar = fig.data[0]
    assert len(bar.x) == 24 and list(bar.y) == tm.mc.hist.bins
    assert bar.x[0] == pytest.approx(tm.mc.hist.lo + (tm.mc.hist.hi - tm.mc.hist.lo) / 48)
    assert sorted(s.x0 for s in fig.layout.shapes) == [358.32, 364.18, 370.04]
    assert fig.layout.xaxis.title.text == "price at 16:00 NY"
