"""Trade Lab: arrives in Phase 4 (chart, entry, exit plan and the Time Machine)."""

import streamlit as st

from app.components.page import footer, setup_page

page = setup_page("Trade Lab", "🧪")
st.title("Trade Lab")
symbol = st.session_state.get("symbol")
st.info(
    f"The Trade Lab arrives in Phase 4: the chart with the opening range, the entry check, the exit plan "
    f"and the Time Machine{f' for **{symbol}**' if symbol else ''}."
)
footer()
