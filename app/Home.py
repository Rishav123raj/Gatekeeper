"""Gatekeeper Desk: Market Overview. Run with `uv run streamlit run app/Home.py`."""

import streamlit as st

from app.components.clock_bar import clock_bar

st.set_page_config(page_title="Gatekeeper", page_icon="🛡️", layout="wide")

clock_bar()

st.title("Gatekeeper")
st.caption("Every trade has to earn its way in.")

st.info(
    "Phase 0: the foundation is in place. Market overview, scanner and news arrive in Phase 3; "
    "see IMPLEMENTATION_GUIDE.md for progress."
)

st.divider()
st.caption("Data: Yahoo (free, delayed, unofficial) · Not financial advice.")
