"""Market context for the day: where the indexes, VIX and the breakouts stand.

This is context, not a signal: it describes the tape a long breakout is trying to work in.

The label rule (each signal counts +1, -1, or 0 when its data is missing):

1. SPY above its session VWAP: +1; below: -1.
2. QQQ above its session VWAP: +1; below: -1.
3. SPY above its 20-day average of daily closes: +1; below: -1.
4. VIX: down or flat on the day: +1; up 10 % or more: -1; in between: 0.
5. Breadth (opening-range breakouts / usable charts, latest scan): 25 % or more: +1;
   under 10 %: -1; in between: 0.

Sum of +2 or more: "supportive". -2 or less: "hostile". Otherwise "mixed".
Fewer than 2 signals with data: "unknown" (for example in replay, where the recorded
day has no index or VIX charts).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from gatekeeper.yahoo import Chart, Source

INDEXES = ("SPY", "QQQ", "IWM")
VIX = "^VIX"
OR_BARS = 3  # the 15-minute opening range on 5-minute bars
BREADTH_STRONG, BREADTH_WEAK = 25.0, 10.0
VIX_SPIKE = 10.0
SPARK_POINTS = 78  # a full session of 5-minute closes


@dataclass
class SeriesState:
    symbol: str
    available: bool = False
    price: float | None = None
    prev_close: float | None = None
    change_pct: float | None = None
    vwap: float | None = None
    vs_vwap_pct: float | None = None
    or_high: float | None = None
    or_low: float | None = None
    vs_or: str | None = None  # above | inside | below
    ma20: float | None = None
    ma50: float | None = None
    vs_ma20_pct: float | None = None
    spark: list[float] = field(default_factory=list)


@dataclass
class Regime:
    indexes: dict[str, SeriesState]
    vix: SeriesState
    breadth_pct: float | None
    signals: dict[str, int | None]
    score: int
    label: str  # supportive | mixed | hostile | unknown
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pct(a: float | None, b: float | None) -> float | None:
    return round(100 * (a / b - 1), 2) if a is not None and b else None


def series_state(symbol: str, intraday: Chart | None, daily: Chart | None = None) -> SeriesState:
    """One index from today's 5-minute bars (and, for the averages, its daily closes)."""
    st = SeriesState(symbol)
    if intraday is None or intraday.bars.empty:
        return st
    b = intraday.bars
    st.available = True
    st.price = intraday.price if intraday.price is not None else float(b["close"].iloc[-1])
    st.prev_close = intraday.prev_close
    st.change_pct = _pct(st.price, st.prev_close)
    st.spark = [round(float(x), 2) for x in b["close"].tail(SPARK_POINTS)]
    vol = pd.to_numeric(b["volume"], errors="coerce").fillna(0)
    if vol.sum() > 0:
        typical = (b["high"] + b["low"] + b["close"]) / 3
        st.vwap = round(float((typical * vol).sum() / vol.sum()), 2)
        st.vs_vwap_pct = _pct(st.price, st.vwap)
    if len(b) >= OR_BARS:
        rng = b.head(OR_BARS)
        st.or_high, st.or_low = round(float(rng["high"].max()), 2), round(float(rng["low"].min()), 2)
        st.vs_or = "above" if st.price > st.or_high else "below" if st.price < st.or_low else "inside"
    if daily is not None and not daily.bars.empty:
        closes = daily.bars["close"]
        if len(closes) >= 20:
            st.ma20 = round(float(closes.tail(20).mean()), 2)
            st.vs_ma20_pct = _pct(st.price, st.ma20)
        if len(closes) >= 50:
            st.ma50 = round(float(closes.tail(50).mean()), 2)
    return st


def label(signals: dict[str, int | None]) -> tuple[int, str]:
    known = [v for v in signals.values() if v is not None]
    score = sum(known)
    if len(known) < 2:
        return score, "unknown"
    return score, "supportive" if score >= 2 else "hostile" if score <= -2 else "mixed"


def _sign(x: float | None) -> int | None:
    return None if x is None else (1 if x > 0 else -1 if x < 0 else 0)


def evaluate(indexes: dict[str, SeriesState], vix: SeriesState, breadth_pct: float | None) -> Regime:
    spy, qqq = indexes.get("SPY", SeriesState("SPY")), indexes.get("QQQ", SeriesState("QQQ"))
    vix_signal = None
    if vix.change_pct is not None:
        vix_signal = 1 if vix.change_pct <= 0 else -1 if vix.change_pct >= VIX_SPIKE else 0
    breadth_signal = None
    if breadth_pct is not None:
        breadth_signal = 1 if breadth_pct >= BREADTH_STRONG else -1 if breadth_pct < BREADTH_WEAK else 0
    signals = {
        "spy_vs_vwap": _sign(spy.vs_vwap_pct),
        "qqq_vs_vwap": _sign(qqq.vs_vwap_pct),
        "spy_vs_ma20": _sign(spy.vs_ma20_pct),
        "vix": vix_signal,
        "breadth": breadth_signal,
    }
    score, lab = label(signals)
    reasons = []
    if spy.vs_vwap_pct is not None:
        reasons.append(f"SPY {'above' if spy.vs_vwap_pct > 0 else 'below'} VWAP ({spy.vs_vwap_pct:+.2f} %)")
    if qqq.vs_vwap_pct is not None:
        reasons.append(f"QQQ {'above' if qqq.vs_vwap_pct > 0 else 'below'} VWAP ({qqq.vs_vwap_pct:+.2f} %)")
    if spy.vs_ma20_pct is not None:
        reasons.append(f"SPY {spy.vs_ma20_pct:+.2f} % vs its 20-day average")
    if vix.change_pct is not None:
        reasons.append(f"VIX {vix.price:.2f} ({vix.change_pct:+.2f} % today)")
    if breadth_pct is not None:
        reasons.append(f"{breadth_pct:.0f} % of usable charts broke their opening range")
    missing = [k for k, v in signals.items() if v is None]
    if missing:
        reasons.append("n/a: " + ", ".join(missing))
    return Regime(indexes, vix, breadth_pct, signals, score, lab, reasons)


def snapshot(src: Source, breadth_pct: float | None = None, *, with_daily: bool = True) -> Regime:
    """Fetches the indexes and VIX from `src` (live Yahoo, or the replay recordings)."""
    indexes = {}
    for sym in INDEXES:
        daily = src.chart(sym, "3mo", "1d") if with_daily else None
        indexes[sym] = series_state(sym, src.chart(sym, "1d", "5m"), daily)
    vix = series_state(VIX, src.chart(VIX, "1d", "5m"))
    return evaluate(indexes, vix, breadth_pct)


def breadth(hits: int, usable: int) -> float | None:
    return round(100 * hits / usable, 1) if usable else None
