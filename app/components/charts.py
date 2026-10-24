"""Plotly figures for the dashboard. Each returns a figure, so they can be tested without Streamlit."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from gatekeeper.clock import NY, to_ist
from gatekeeper.skills.models import TimeMachineResult
from gatekeeper.tables import ScanRun

UP, DOWN, FLAT = "#2e7d32", "#c62828", "#78909c"
LEVEL_COLORS = {"entry": "#1565c0", "stop": "#c62828", "target": "#2e7d32"}


def _bare(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def sparkline(values: list[float], ref: float | None = None, height: int = 60) -> go.Figure:
    """Today's closes as a small line, green above the reference (yesterday's close), red below."""
    color = FLAT
    if values and ref:
        color = UP if values[-1] >= ref else DOWN
    fig = go.Figure(go.Scatter(y=values, mode="lines", line={"color": color, "width": 1.5}, hoverinfo="y"))
    if ref:
        fig.add_hline(y=ref, line={"color": FLAT, "width": 1, "dash": "dot"})
    return _bare(fig, height)


def breadth_gauge(pct: float | None, height: int = 170) -> go.Figure:
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=pct if pct is not None else 0,
            number={"suffix": " %", "valueformat": ".0f"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#455a64"},
                "steps": [
                    {"range": [0, 10], "color": "#ffcdd2"},
                    {"range": [10, 25], "color": "#eceff1"},
                    {"range": [25, 100], "color": "#c8e6c9"},
                ],
            },
            title={"text": "Breakouts / usable charts" if pct is not None else "Breadth: no ORB scan yet"},
        )
    )
    fig.update_layout(height=height, margin={"l": 20, "r": 20, "t": 40, "b": 0})
    return fig


def breadth_line(runs: list[ScanRun], height: int = 200) -> go.Figure:
    """Share of usable charts above their opening range, at each ORB scan of the day."""
    xs = [(r.as_of or "")[11:16] for r in runs]
    ys = [round(100 * r.hits_count / r.scanned, 1) if r.scanned else None for r in runs]
    fig = go.Figure(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines+markers",
            line={"color": "#455a64"},
            hovertemplate="%{x} NY: %{y} %<extra></extra>",
        )
    )
    fig.update_layout(
        height=height,
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        yaxis={"title": "% broke out", "rangemode": "tozero"},
        xaxis={"title": "ORB scan (NY)"},
    )
    return fig


# --- Trade Lab (Phase 4) ---------------------------------------------------------------------


def candles_with_levels(
    df: pd.DataFrame,
    or_high: float | None = None,
    or_low: float | None = None,
    entry: float | None = None,
    stop: float | None = None,
    target: float | None = None,
    trigger_ts: datetime | None = None,
    trigger_price: float | None = None,
    flat_by: datetime | None = None,
    *,
    session: tuple[datetime, datetime] | None = None,
    height: int = 520,
) -> go.Figure:
    """5-minute candles with volume, the opening range, the entry trigger and the plan's levels.

    The x-axis is New York time; the hover shows IST too. Traces: candles, volume, and the
    trigger marker when there is one. Shapes: the opening-range band, one line per level and
    the flat-by line.
    """
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.03)
    ts = list(pd.to_datetime(df["ts"])) if len(df) else []
    ist = [f"{to_ist(t):%H:%M} IST" for t in ts]
    fig.add_trace(
        go.Candlestick(
            x=ts,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="5-min bars",
            text=ist,
            hoverinfo="x+y+text",
            increasing_line_color=UP,
            decreasing_line_color=DOWN,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=ts,
            y=df["volume"],
            name="volume",
            marker_color="#b0bec5",
            customdata=ist,
            hovertemplate="%{x|%H:%M} NY · %{customdata}<br>%{y:,.0f}<extra></extra>",
        ),
        row=2,
        col=1,
    )
    if or_high is not None and or_low is not None:
        fig.add_hrect(
            y0=or_low,
            y1=or_high,
            fillcolor="#90a4ae",
            opacity=0.18,
            line_width=0,
            row=1,
            col=1,
            annotation_text=f"opening range {or_low:.2f} – {or_high:.2f}",
            annotation_position="top left",
        )
    for name, level in (("entry", entry), ("stop", stop), ("target", target)):
        if level is not None:
            fig.add_hline(
                y=level,
                line={"color": LEVEL_COLORS[name], "width": 1.5, "dash": "dash"},
                row=1,
                col=1,
                annotation_text=f"{name} {level:.2f}",
                annotation_position="right",
            )
    if trigger_ts is not None and trigger_price is not None:
        fig.add_trace(
            go.Scatter(
                x=[trigger_ts],
                y=[trigger_price],
                mode="markers",
                name="entry trigger",
                marker={
                    "symbol": "triangle-up",
                    "size": 14,
                    "color": LEVEL_COLORS["entry"],
                    "line": {"color": "white", "width": 1},
                },
                hovertemplate=(
                    "trigger %{y:.2f} (bar %{x|%H:%M} NY · "
                    f"{to_ist(trigger_ts):%H:%M} IST)<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )
    if flat_by is not None:
        fig.add_vline(x=flat_by, line={"color": "#6d4c41", "width": 1, "dash": "dot"})
        fig.add_annotation(
            x=flat_by,
            y=1,
            yref="paper",
            text=f"flat by {flat_by:%H:%M}",
            showarrow=False,
            xanchor="right",
            font={"size": 11, "color": "#6d4c41"},
        )
    fig.update_layout(
        height=height,
        margin={"l": 0, "r": 70, "t": 10, "b": 0},
        showlegend=False,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )
    if session is not None:
        fig.update_xaxes(range=list(session))
    fig.update_xaxes(tickformat="%H:%M", row=2, col=1)
    fig.update_yaxes(title_text="price", row=1, col=1)
    fig.update_yaxes(title_text="vol", row=2, col=1)
    return fig


def tm_odds_bar(tm: TimeMachineResult, height: int = 140) -> go.Figure:
    """One stacked bar: target first / stop first / neither by the end time; green as a marker."""
    mc = tm.mc
    parts = [
        ("target first", mc.p_target, UP),
        ("stop first", mc.p_stop, DOWN),
        (f"neither by {mc.until}", mc.p_neither, "#b0bec5"),
    ]
    fig = go.Figure()
    for name, p, color in parts:
        fig.add_trace(
            go.Bar(
                y=["odds"],
                x=[100 * p],
                orientation="h",
                name=name,
                marker_color=color,
                text=f"{name} {100 * p:.1f} %",
                textposition="inside",
                insidetextanchor="middle",
                hovertemplate=f"{name}: %{{x:.1f}} %<extra></extra>",
            )
        )
    fig.add_trace(
        go.Scatter(
            y=["odds"],
            x=[100 * mc.p_green],
            mode="markers",
            name="green",
            marker={
                "symbol": "diamond",
                "size": 13,
                "color": "#1b5e20",
                "line": {"color": "white", "width": 1},
            },
            hovertemplate="green (target first, or above the entry at the end): %{x:.1f} %<extra></extra>",
        )
    )
    fig.update_layout(
        barmode="stack",
        height=height,
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        xaxis={"range": [0, 100], "ticksuffix": " %"},
        yaxis={"visible": False},
        legend={"orientation": "h", "y": -0.35},
    )
    return fig


def _session_times(day: str, times: list[str]) -> list[datetime]:
    d = date.fromisoformat(day)
    return [datetime.combine(d, datetime.strptime(t, "%H:%M").time(), NY) for t in times]


def tm_fan(tm: TimeMachineResult, max_paths: int = 50, height: int = 360) -> go.Figure:
    """The replays as a fan: 5–95 % and 25–75 % bands, the median, faint sample paths, stop and target."""
    mc, plan = tm.mc, tm.plan
    x = _session_times(plan.get("date") or "2026-01-01", mc.band_times)
    band = list(zip(*mc.bands, strict=True))  # 5 rows: p5, p25, p50, p75, p95
    fig = go.Figure()
    for path in mc.sample_paths[:max_paths]:
        fig.add_trace(
            go.Scatter(
                x=x[: len(path)],
                y=path,
                mode="lines",
                hoverinfo="skip",
                line={"color": "rgba(69,90,100,0.12)", "width": 1},
                showlegend=False,
            )
        )
    for lo, hi, alpha, label in ((0, 4, 0.15, "5–95 %"), (1, 3, 0.30, "25–75 %")):
        fig.add_trace(
            go.Scatter(x=x, y=band[hi], mode="lines", line={"width": 0}, hoverinfo="skip", showlegend=False)
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=band[lo],
                mode="lines",
                line={"width": 0},
                fill="tonexty",
                fillcolor=f"rgba(21,101,192,{alpha})",
                name=label,
                hoverinfo="skip",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=band[2],
            mode="lines",
            name="median",
            line={"color": "#0d47a1", "width": 2},
            hovertemplate="%{x|%H:%M} NY: median %{y:.2f}<extra></extra>",
        )
    )
    for name in ("stop", "target", "entry"):
        if plan.get(name) is not None:
            fig.add_hline(
                y=plan[name],
                line={"color": LEVEL_COLORS[name], "width": 1.5, "dash": "dash"},
                annotation_text=f"{name} {plan[name]:.2f}",
                annotation_position="right",
            )
    fig.update_layout(
        height=height,
        margin={"l": 0, "r": 70, "t": 10, "b": 0},
        xaxis={"tickformat": "%H:%M"},
        yaxis={"title": "price"},
        legend={"orientation": "h", "y": -0.15},
    )
    return fig


def tm_close_hist(tm: TimeMachineResult, height: int = 260) -> go.Figure:
    """Where the price was at the end time across the replays (24 bins), with the plan's levels."""
    h, plan = tm.mc.hist, tm.plan
    n = len(h.bins)
    width = (h.hi - h.lo) / n if n else 0
    centers = [h.lo + width * (i + 0.5) for i in range(n)]
    fig = go.Figure(
        go.Bar(
            x=centers,
            y=h.bins,
            width=width * 0.95,
            marker_color="#78909c",
            hovertemplate="%{x:.2f}: %{y} replays<extra></extra>",
        )
    )
    for name in ("stop", "entry", "target"):
        if plan.get(name) is not None:
            fig.add_vline(
                x=plan[name],
                line={"color": LEVEL_COLORS[name], "width": 1.5, "dash": "dash"},
                annotation_text=name,
                annotation_position="top",
            )
    fig.update_layout(
        height=height,
        margin={"l": 0, "r": 0, "t": 20, "b": 0},
        bargap=0,
        xaxis={"title": f"price at {tm.mc.until} NY"},
        yaxis={"title": "replays"},
    )
    return fig
