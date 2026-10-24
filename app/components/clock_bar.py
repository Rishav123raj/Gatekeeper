"""The bar at the top of every page: New York and IST time, session phase, mode."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from app import state
from gatekeeper.clock import PHASE_LABELS, fmt_dual, load_session_times, market_day, session_phase
from gatekeeper.settings import get_settings


def clock_line(now: datetime, mode: str, phase: str) -> str:
    data = "recorded day, no internet" if mode == "replay" else "Yahoo, delayed"
    return (
        f"**{fmt_dual(now)}** · {now:%a %d %b %Y} · Session: **{PHASE_LABELS[phase]}**"
        f" · Mode: **{mode.upper()}** · Data: {data}"
    )


@st.fragment(run_every="10s")
def clock_bar() -> None:
    settings = get_settings()
    mode, now = state.mode(), state.now()
    trader = (
        settings.resolve(settings.replay_workspace) if mode == "replay" else settings.root_path
    ) / "trader"
    day = market_day(now.date())
    phase = session_phase(now, load_session_times(trader), day)
    line = clock_line(now, mode, phase)
    if day is not None and day.early_close:
        line += f" · Early close {day.closes} ({day.early_close})"
    elif day is not None and not day.trading_day:
        line += f" · {day.reason}"
    st.markdown(line)
