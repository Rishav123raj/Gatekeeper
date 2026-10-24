"""Trade Lab: see the setup on a chart, plan the exit, and get the honest odds.

Nothing here places an order. The entry, the plan and the replays come from the skills
(entry.py, exit.py, timemachine.py); this page shows them and keeps a record.
"""

from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd
import streamlit as st

from app.components import charts
from app.components.gates import claude_ticket, decision_form, readiness_panel
from app.components.page import Page, footer, setup_page
from app.components.tables import pct, price
from gatekeeper import lab, store
from gatekeeper.clock import NY, load_session_times
from gatekeeper.db import session
from gatekeeper.readiness import build_trade_context, evaluate_trade
from gatekeeper.skills import alerts, broker, budget, entry, exit, risk, timemachine
from gatekeeper.skills.models import EntryStatus, ExitPlan, TimeMachineResult

page = setup_page("Trade Lab", "🧪")
st.title("Trade Lab")
st.caption(
    "The setup on a chart, the exit planned before the entry, and the honest odds. "
    "Nothing on this page places an order."
)

STOP_LABELS = {
    "or-mid": "opening-range midpoint",
    "or-low": "opening-range low",
    "pct": "percent under the entry",
    "atr": "ATR multiple",
    "price": "your price",
}
TARGET_LABELS = {"1R": "1R", "1.5R": "1.5R", "2R": "2R", "3R": "3R", "price": "your price"}
DEFAULT_VARIANTS = [("or-mid", "1R"), ("or-mid", "2R"), ("or-low", "1R"), ("or-low", "2R")]


def busy() -> bool:
    return bool(st.session_state.get("lab_busy"))


def pick_symbol(p: Page) -> str:
    with session(p.engine) as s:
        pins = store.pinned(s, p.mode)
        orb = store.latest_scan(s, p.mode, "orb")
        hits = [h.symbol for h in store.scan_hits(s, orb)] if orb and orb.session_date == p.today else []
    first = st.session_state.get("symbol") or (pins[0] if pins else "TSLA")
    options = list(dict.fromkeys([first, *pins, *hits]))
    c1, c2 = st.columns([2, 1])
    pick = c1.selectbox("Ticker (pinned, then today's breakouts)", options, key="lab_pick")
    other = c2.text_input("Or type a ticker", key="lab_other").strip().upper()
    symbol = other or pick
    st.session_state["symbol"] = symbol
    return symbol


def lab_state(p: Page, symbol: str) -> dict:
    return st.session_state.setdefault("lab", {}).setdefault(f"{p.mode}:{p.today}:{symbol}", {})


def external_plan_banner(p: Page) -> None:
    """Tell the user when trader/plan.json changed outside this page (task 4.7)."""
    path = p.trader_dir / "plan.json"
    h = lab.file_hash(path)
    key = f"plan_hash:{p.mode}"
    if h is None or h == st.session_state.get(key):
        return
    c1, c2 = st.columns([4, 1])
    c1.warning(
        "Plan updated externally (trader/plan.json changed outside this page, for example from Claude chat)."
    )
    if c2.button("Reload plan", key="lab_reload"):
        plan, res = exit.show(runner=p.runner("trade_lab"))
        if plan is not None:
            with session(p.engine) as s:
                row = store.save_plan(s, plan, p.mode)
            st.session_state["symbol"] = plan.symbol
            lab_state(p, plan.symbol).update(plan=plan, plan_id=row.id, tm=None, size=None, risk=None)
        st.session_state[key] = h
        st.rerun()
    if c2.button("Dismiss", key="lab_dismiss"):
        st.session_state[key] = h
        st.rerun()


def session_bounds(d: date) -> tuple[datetime, datetime]:
    return datetime.combine(d, time(9, 30), NY), datetime.combine(d, time(16, 0), NY)


def chart(p: Page, symbol: str, ls: dict) -> None:
    c = p.yahoo().chart(symbol)
    if c is None or c.bars.empty:
        st.info(
            f"No 5-minute chart for {symbol} {'in the recording' if p.mode == 'replay' else 'yet'}."
            + (" The recorded day has full charts for TSLA only." if p.mode == "replay" else "")
        )
        return
    day = c.bars["ts"].iloc[-1].date()  # the bars' session: Friday's on a weekend, not today
    e: EntryStatus | None = ls.get("entry")
    plan: ExitPlan | None = ls.get("plan")
    rng = e.opening_range if e else None
    trig_ts = trig_px = None
    if e and e.trigger:
        trig_ts = datetime.combine(day, datetime.strptime(e.trigger.bar_start, "%H:%M").time(), NY)
        trig_px = e.trigger.price
    flat = plan.flat_by if plan and plan.flat_by else f"{load_session_times(p.trader_dir).flat_by:%H:%M}"
    flat_dt = datetime.combine(day, datetime.strptime(flat, "%H:%M").time(), NY)
    fig = charts.candles_with_levels(
        c.bars,
        rng.high if rng else None,
        rng.low if rng else None,
        plan.entry if plan else None,
        plan.stop if plan else None,
        plan.target if plan else None,
        trig_ts,
        trig_px,
        flat_dt,
        session=session_bounds(day),
    )
    st.plotly_chart(fig, key=f"lab_chart_{symbol}")
    last = c.bars["ts"].iloc[-1]
    st.caption(
        f"{symbol} {price(c.price)} ({pct(c.change_pct)} vs yesterday's close) · last closed bar "
        f"{last:%H:%M} NY · 5-minute bars, Yahoo, free and delayed"
        + (" · refreshes every 60 s" if p.mode == "live" else "")
    )


def entry_panel(p: Page, symbol: str, ls: dict) -> None:
    st.subheader("1 · Entry")
    c1, c2, c3, c4 = st.columns(4)
    setup = c1.radio(
        "Setup",
        ["orb", "level"],
        horizontal=True,
        key="lab_setup",
        format_func=lambda x: "opening-range breakout" if x == "orb" else "close above a level",
    )
    level = c2.number_input(
        "Level",
        min_value=0.0,
        value=0.0,
        step=0.5,
        key="lab_level",
        disabled=setup != "level",
        help="For a level setup, e.g. a 20-day high",
    )
    interval = c3.selectbox("Bars", ["5m", "1m"], key="lab_interval")
    vol = c4.number_input(
        "Volume × range average (0 = off)", min_value=0.0, value=0.0, step=0.5, key="lab_vol"
    )
    if st.button("Check entry", key="lab_check", disabled=busy() or (setup == "level" and not level)):
        status, res = entry.check(
            symbol,
            setup=setup,
            level=level or None,
            interval=interval,
            min_volume_x=vol or None,
            write=True,
            runner=p.runner("trade_lab"),
        )
        if status is not None:
            with session(p.engine) as s:
                store.save_entry(s, status, p.mode)
            ls.update(entry=status, entry_error=None)
        else:
            ls.update(entry=None, entry_error=res.message or res.status)
    e: EntryStatus | None = ls.get("entry")
    if ls.get("entry_error"):
        st.error(ls["entry_error"])
    elif e is None:
        st.caption("Check the entry: entry.py waits for a closed bar above the level (a wick doesn't count).")
    else:
        color = {"triggered": "green", "waiting": "orange"}.get(e.status, "gray")
        st.markdown(f":{color}-badge[{e.status.upper()}] {e.reason} · checked {e.now[11:16]} NY")
        if e.trigger:
            t = e.trigger
            st.markdown(
                f"Triggered **{t.time}** at **{price(t.price)}**: the {t.bar_start} bar (bar {t.bar_index}) "
                f"closed above {price(e.level)} ({pct(t.pct_over)}). Nothing was placed."
            )
        if e.opening_range:
            st.caption(
                f"Opening range {e.opening_range.low:.2f} – {e.opening_range.high:.2f} "
                f"({e.opening_range.minutes} min)"
            )


def exit_panel(p: Page, symbol: str, ls: dict) -> None:
    st.subheader("2 · Exit plan")
    e: EntryStatus | None = ls.get("entry")
    triggered = bool(e and e.trigger)
    ahead = None
    if not triggered:
        st.caption("exit.py plans from a triggered entry. To plan ahead, give the entry price you expect.")
        ahead = (
            st.number_input("Plan ahead at entry price", min_value=0.0, value=0.0, step=0.5, key="lab_ahead")
            or None
        )
    c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1])
    stop_rule = c1.selectbox("Stop", list(STOP_LABELS), format_func=STOP_LABELS.get, key="lab_stop")
    stop_value = c2.number_input(
        "Stop value",
        min_value=0.0,
        value=1.5 if stop_rule == "atr" else 1.0,
        step=0.25,
        key=f"lab_stop_v_{stop_rule}",
        disabled=stop_rule in ("or-mid", "or-low"),
        help="pct: percent under the entry · atr: multiple · price: the stop price",
    )
    target_rule = c3.selectbox("Target", list(TARGET_LABELS), index=2, key="lab_target")
    target_value = c4.number_input(
        "Target price",
        min_value=0.0,
        value=0.0,
        step=0.5,
        key="lab_target_v",
        disabled=target_rule != "price",
    )
    flat_default = f"{load_session_times(p.trader_dir).flat_by:%H:%M}"
    flat_by = c5.text_input("Flat by (NY)", value=flat_default, key="lab_flat")

    entry_px = e.trigger.price if triggered else ahead
    rng = e.opening_range if e else None
    if entry_px:
        pv = lab.preview(
            entry_px,
            rng.high if rng else None,
            rng.low if rng else None,
            stop_rule,
            stop_value if stop_rule in ("pct", "price") else None,
            target_rule,
            target_value or None,
        )
        if pv.stop is not None and pv.target is not None:
            st.caption(
                f"Preview (exit.py decides): stop {pv.stop:.2f} · target {pv.target:.2f} · "
                f"risk {pv.risk:.2f} a share · reward:risk {pv.reward_risk}"
            )
        else:
            st.caption(f"Preview: {pv.note}")

    if st.button("Plan exit", key="lab_plan", disabled=busy() or not entry_px):
        try:
            stop, target = (
                lab.stop_arg(stop_rule, stop_value),
                lab.target_arg(target_rule, target_value or None),
            )
        except ValueError as err:
            st.error(str(err))
            return
        plan, res = exit.plan(
            stop=stop,
            target=target,
            flat_by=flat_by or None,
            entry=ahead,
            write=True,
            runner=p.runner("trade_lab"),
        )
        if plan is None:
            ls.update(plan_error=res.message or res.status)
        else:
            with session(p.engine) as s:
                row = store.save_plan(s, plan, p.mode)
            ls.update(plan=plan, plan_id=row.id, plan_error=None, tm=None, size=None, risk=None)
            st.session_state[f"plan_hash:{p.mode}"] = lab.file_hash(p.trader_dir / "plan.json")
    if ls.get("plan_error"):
        st.error(ls["plan_error"])
    plan: ExitPlan | None = ls.get("plan")
    if plan is not None:
        m = st.columns(6)
        m[0].metric("Entry", price(plan.entry), help=f"{plan.entry_time or ''} {plan.setup or ''}")
        m[1].metric("Stop", price(plan.stop), help=plan.stop_label)
        m[2].metric("Target", price(plan.target), help=plan.target_label)
        m[3].metric(
            "Risk / share",
            price(plan.risk_per_share),
            f"{100 * plan.risk_per_share / plan.entry:.2f} %",
            delta_color="off",
        )
        m[4].metric("Reward : risk", f"{plan.reward_risk}")
        m[5].metric("Flat by", f"{plan.flat_by} NY")
        st.caption(
            f"Stop: {plan.stop_label} {plan.stop_detail or ''} · Target: {plan.target_label}. "
            "A stop is a plan, not a guarantee: a gap or a fast market can fill past it."
        )
        for w in plan.warnings:
            st.warning(w)
        if st.button(
            "Add plan alerts",
            key="lab_alerts",
            help="alerts.py adds three rules for today: the stop, the target and 'flat by close'.",
        ):
            rules, res = alerts.add_from_plan(runner=p.runner("trade_lab"))
            mine = [r.id for r in rules if r.date == plan.date and (r.symbol or "") in (plan.symbol, "")]
            if res.ok:
                st.success(
                    f"Alerts set: {', '.join(mine)}. The worker checks them every 2 minutes; see "
                    "Positions & Alerts."
                )
            else:
                st.error(res.message or res.status)


def tm_panel(p: Page, ls: dict) -> str | None:
    st.subheader("3 · Time Machine")
    plan: ExitPlan | None = ls.get("plan")
    if plan is None:
        st.caption("Plan the exit first: the Time Machine replays that plan.")
        return None
    c1, c2, c3 = st.columns([2, 1, 1])
    end = c1.radio(
        "End each replay at",
        ["flat", "close"],
        horizontal=True,
        key="lab_until",
        format_func=lambda x: f"your flat-by time ({plan.flat_by})" if x == "flat" else "the close (16:00)",
    )
    until = plan.flat_by if end == "flat" else None
    seed = int(
        c2.number_input(
            "Seed",
            min_value=0,
            value=19,
            step=1,
            key="lab_seed",
            help="Same plan, same data, same seed: the same numbers on any machine.",
        )
    )
    run = c3.button("Run Time Machine", key="lab_tm", disabled=busy())
    if run:
        st.session_state["lab_busy"] = True
        try:
            with st.status("Replaying the rest of the day 10,000 times...", expanded=False) as box:
                tm, res = timemachine.run(until=until, seed=seed, runner=p.runner("trade_lab"))
                box.update(label="Done" if tm else "Failed", state="complete" if tm else "error")
        finally:
            st.session_state["lab_busy"] = False
        if tm is None:
            ls.update(tm=None, tm_error=res.message or res.status)
        else:
            with session(p.engine) as s:
                store.save_tm(s, tm, p.mode, ls.get("plan_id"))
            ls.update(tm=tm, tm_error=None)
    if ls.get("tm_error"):
        st.error(ls["tm_error"])
    tm: TimeMachineResult | None = ls.get("tm")
    if tm is not None:
        mc, h = tm.mc, tm.history
        st.plotly_chart(charts.tm_odds_bar(tm), key="lab_odds")
        m = st.columns(5)
        m[0].metric("Target first", f"{100 * mc.p_target:.1f} %")
        m[1].metric("Stop first", f"{100 * mc.p_stop:.1f} %")
        m[2].metric(f"Neither by {mc.until}", f"{100 * mc.p_neither:.1f} %")
        m[3].metric("Green", f"{100 * mc.p_green:.1f} %", help="Target first, or above the entry at the end")
        m[4].metric("Average R", f"{mc.avg_R:+.3f}")
        f1, f2 = st.columns([3, 2])
        f1.plotly_chart(charts.tm_fan(tm), key="lab_fan")
        f2.plotly_chart(charts.tm_close_hist(tm), key="lab_hist")
        st.caption(
            f"Price at {mc.until}: median {mc.median_close:.2f}, 90 % of replays between "
            f"{mc.p5_close:.2f} and {mc.p95_close:.2f}."
        )
        if h:
            st.markdown(
                f"History: the same rule on each of those {h.sessions} real sessions fired {h.triggered} "
                f"times: {h.target} target, {h.stop} stop, {h.close} neither. Average R {h.avg_R:+.3f}."
            )
        st.markdown(f"**{tm.verdict}**")
        for note in tm.verdict_notes:
            st.markdown(note)
        st.caption(
            f"{mc.replays:,} replays, seed {mc.seed}, from {mc.pool_sessions} full sessions "
            f"({mc.pool_from} to {mc.pool_to}). A simulation built from the last 60 days, not a "
            "prediction: earnings, news and halts can do things those days never did."
        )
    return until


def compare_panel(p: Page, ls: dict, until: str | None) -> None:
    st.subheader("4 · Compare plans")
    if ls.get("plan") is None and not (ls.get("entry") and ls["entry"].trigger):
        st.caption("Check a triggered entry (or plan ahead) to compare stop / target variants.")
        return
    st.caption(
        "Up to 4 variants, each planned by exit.py and replayed with the same seed. "
        "This never changes trader/plan.json."
    )
    base = pd.DataFrame(
        [{"stop": s, "stop value": None, "target": t, "target value": None} for s, t in DEFAULT_VARIANTS]
    )
    edited = st.data_editor(
        base,
        num_rows="dynamic",
        hide_index=True,
        key="lab_variants",
        column_config={
            "stop": st.column_config.SelectboxColumn(options=list(STOP_LABELS), required=True),
            "stop value": st.column_config.NumberColumn(help="pct / atr / price stops"),
            "target": st.column_config.SelectboxColumn(options=list(TARGET_LABELS), required=True),
            "target value": st.column_config.NumberColumn(help="a price target"),
        },
    )
    seed = int(st.session_state.get("lab_seed", 19))
    if st.button("Compare", key="lab_compare", disabled=busy()):
        variants = [
            lab.Variant(
                r["stop"],
                r["target"],
                None if pd.isna(r["stop value"]) else float(r["stop value"]),
                None if pd.isna(r["target value"]) else float(r["target value"]),
            )
            for r in edited.head(4).to_dict("records")
            if r.get("stop") and r.get("target")
        ]
        ahead = st.session_state.get("lab_ahead") or None
        triggered = bool(ls.get("entry") and ls["entry"].trigger)
        st.session_state["lab_busy"] = True
        try:
            with st.status(f"Planning and replaying {len(variants)} variants...", expanded=False):
                results = lab.compare(
                    variants,
                    p.runner("trade_lab"),
                    until=until,
                    seed=seed,
                    entry=None if triggered else ahead,
                )
        finally:
            st.session_state["lab_busy"] = False
        ls["compare"] = [r.row() for r in results]
    if ls.get("compare"):
        st.dataframe(
            pd.DataFrame(ls["compare"]),
            hide_index=True,
            column_config={
                "Stop": st.column_config.NumberColumn(format="$%.2f"),
                "Target": st.column_config.NumberColumn(format="$%.2f"),
                "Risk / share": st.column_config.NumberColumn(format="$%.2f"),
            },
        )
        st.caption(
            f"Replays end at {until or '16:00'} NY, seed {seed}. A bigger target needs to win less often: "
            "the break-even is 1 in (1 + R)."
        )


def size_and_check(p: Page, ls: dict) -> None:
    """size.py writes one bracket order; check.py PASSes or BLOCKs it (task 5.8). Nothing is placed."""
    r = p.runner("trade_lab")
    size, res = budget.size(write=True, runner=r)
    ls.update(size=size, size_error=None if size else (res.message or res.status), risk=None, risk_error=None)
    if size is None or size.refused:
        return  # no order was written: checking trader/orders.json now would check an older order
    report, res = risk.check(runner=r)
    ls.update(risk=report, risk_error=None if report else (res.message or res.status))
    if report is not None:
        with session(p.engine) as s:
            store.save_risk(s, report, p.mode, ls.get("plan_id"))


def go_no_go(p: Page, symbol: str, ls: dict) -> None:
    st.subheader("5 · Size, check and Go / No-Go")
    plan = ls.get("plan")
    c1, c2 = st.columns([1, 3])
    if c1.button(
        "Size & check",
        key="lab_size",
        disabled=busy() or plan is None,
        help="size.py sizes the plan to your max loss and writes one bracket order; check.py then "
        "checks it against every limit. Nothing is placed.",
    ):
        with st.spinner("Sizing and checking..."):
            size_and_check(p, ls)
    size, report = ls.get("size"), ls.get("risk")
    if plan is None:
        c2.caption("Plan the exit first.")
    elif size is not None:
        z = size.sizing
        if size.refused:
            c2.error(z.refusal or "size.py wrote no order")
        else:
            c2.markdown(
                f"**{z.qty} shares** · ${z.cost:,.2f} · ${z.max_loss:,.2f} at the stop · bound by "
                f"**{z.bound_by}** · one bracket order (stop {z.stop}, target {z.target}) in "
                "trader/orders.json"
            )
        if report is not None:
            for v in report.results:
                (c2.success if v.verdict == "PASS" else c2.error)(
                    f"check.py {v.verdict}: " + ("; ".join(v.reasons) if v.reasons else "; ".join(v.info[:2]))
                )
    for err in (ls.get("size_error"), ls.get("risk_error")):
        if err:
            st.error(err)

    ctx = build_trade_context(
        p.engine,
        p.mode,
        p.now,
        p.trader_dir,
        p.settings,
        symbol,
        entry=ls.get("entry"),
        plan=plan,
        plan_id=ls.get("plan_id"),
        plan_error=ls.get("plan_error"),
        tm=ls.get("tm"),
        size=size,
        risk=report,
    )
    result = evaluate_trade(ctx, p.settings)
    with session(p.engine) as s:
        rid = store.save_readiness(s, result, p.mode, min_minutes=p.settings.gate_readiness_store_min).id
    readiness_panel(result, f"Trade: {symbol}")
    if report is not None and not report.block:
        tickets, _ = broker.show(runner=p.runner("trade_lab"))
        claude_ticket(tickets)
    decision_form(p.engine, p.mode, result, rid, key=f"decide_{symbol}")


symbol = pick_symbol(page)
external_plan_banner(page)
ls = lab_state(page, symbol)

st.fragment(run_every="60s" if page.mode == "live" else None)(chart)(page, symbol, ls)
left, right = st.columns(2)
with left:
    entry_panel(page, symbol, ls)
with right:
    exit_panel(page, symbol, ls)
until = tm_panel(page, ls)
compare_panel(page, ls, until)
go_no_go(page, symbol, ls)
footer()
