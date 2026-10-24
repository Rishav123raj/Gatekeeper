"""Per-browser-session state: live or replay, and what time it is for the pages."""

from __future__ import annotations

from datetime import date, datetime, time

import streamlit as st

from gatekeeper.clock import NY, now_ny
from gatekeeper.settings import get_settings

DEFAULT_REPLAY_TIME = time(10, 15)


def mode() -> str:
    """'live' or 'replay': the sidebar's choice, else GATEKEEPER_MODE from .env."""
    return st.session_state.get("mode", get_settings().mode)


def replay_day() -> date:
    return date.fromisoformat(get_settings().replay_date)


def replay_time() -> time:
    return st.session_state.get("replay_time", DEFAULT_REPLAY_TIME)


def now() -> datetime:
    """New York now: the real clock live, the slider's time in replay."""
    if mode() == "replay":
        return datetime.combine(replay_day(), replay_time(), NY)
    return now_ny()


def today() -> str:
    return f"{now():%Y-%m-%d}"
