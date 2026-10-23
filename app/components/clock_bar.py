"""The bar at the top of every page: New York and IST time, session phase, mode."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from gatekeeper.clock import PHASE_LABELS, fmt_dual, load_session_times, now_ny, session_phase
from gatekeeper.settings import get_settings


def clock_line(now: datetime, mode: str, phase: str) -> str:
    return (
        f"**{fmt_dual(now)}** · {now:%a %d %b %Y} · Session: **{PHASE_LABELS[phase]}**"
        f" · Mode: **{mode.upper()}** · Data: Yahoo, delayed"
    )


@st.fragment(run_every="10s")
def clock_bar() -> None:
    settings = get_settings()
    now = now_ny(st.session_state.get("replay_now"))
    phase = session_phase(now, load_session_times(settings.trader_path))
    st.markdown(clock_line(now, settings.mode, phase))
