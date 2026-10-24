"""Plotly figures for the dashboard. Each returns a figure, so they can be tested without Streamlit."""

from __future__ import annotations

import plotly.graph_objects as go

from gatekeeper.tables import ScanRun

UP, DOWN, FLAT = "#2e7d32", "#c62828", "#78909c"


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
