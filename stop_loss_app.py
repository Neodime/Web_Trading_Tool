# stop_loss_fee_tool_v4.py – fee-centric SL/TP planner (bug‑fixed)
"""
Bug fix: **Shrink SL by round‑trip fees** now keeps the *original* position size and
shrinks only the stop‑loss distance, so total risk (price move + fees) equals the
chosen budget R.
All other behaviour unchanged.
"""
from __future__ import annotations
import numpy as np, pandas as pd, plotly.graph_objects as go, streamlit as st

EXEC_TYPES = ["% of notional (per leg)", "Flat $ per leg", "Spread (price units per leg)"]
MAINT_TYPES = ["None", "% of notional per day", "Flat $ per day"]
PTS = 200  # sweep resolution

# ── Fee helpers ───────────────────────────────────────────────

def usd_exec_fee(q, p, t, v):
    if t.startswith("%"):
        return q * p * v / 100
    if t.startswith("Flat $"):
        return v
    if t.startswith("Spread"):
        return q * v
    return 0.0


def usd_maint_fee(q, p, t, v, d):
    if t == MAINT_TYPES[0]:
        return 0.0
    if t.startswith("%"):
        return q * p * v / 100 * d
    return v * d


def fee_price_units(t, v, p):
    return v if t.startswith("Spread") else p * v / 100 if t.startswith("%") else 0.0

# ── Exact sizing helper ──────────────────────────────────────

def solve_size_exact(stp, p, R, et, ev, mt, mv, d):
    fixed = (ev * 2 if et.startswith("Flat $") else 0.0) + (mv * d if mt.startswith("Flat $") else 0.0)
    coeff = stp + (p * ev / 100 * 2 if et.startswith("%") else ev * 2 if et.startswith("Spread") else 0.0) + (p * mv / 100 * d if mt.startswith("%") else 0.0)
    size = max((R - fixed) / coeff, 0.0) if coeff else 0.0
    return size, fixed


def tp_needed(q, p, rr, R, et, ev, mt, mv, d):
    gross = rr * R + usd_exec_fee(q, p, et, ev) * 2 + usd_maint_fee(q, p, mt, mv, d)
    return gross / q if q else float('nan')

# ── Streamlit app ────────────────────────────────────────────

def app():
    st.set_page_config(page_title="SL vs Fees", layout="centered")
    st.title("Stop-Loss tightness vs Fees & TP distance")

    with st.sidebar:
        sizing = st.radio("Sizing method", ("Include fees in sizing", "Shrink SL by round-trip fees", "Widen TP to absorb fees"))

        with st.expander("Risk", True):
            acct = st.number_input("Account size", value=100.0, min_value=10.0, step=10.0)
            rmode = st.radio("Mode", ("%", "$"))
            R = acct * st.number_input("Risk %", value=1.0, step=0.1)/100 if rmode == "%" else st.number_input("Risk $", value=10.0, min_value=0.01)
        with st.expander("Fees", True):
            price = st.number_input("Current price", value=1.1000, format="%.5f")
            exec_t = st.selectbox("Exec type", EXEC_TYPES)
            exec_v = st.number_input("Exec value", value=0.10 if exec_t.startswith("%") else 0.25, min_value=0.0)
            maint_t = st.selectbox("Maint type", MAINT_TYPES)
            maint_v = 0.0 if maint_t == MAINT_TYPES[0] else st.number_input("Maint value", value=0.05 if maint_t.startswith("%") else 0.10, min_value=0.0)
            days = st.number_input("Days held", value=1, min_value=1)
        with st.expander("Position", True):
            min_sl = st.number_input("Min SL", value=0.0001)
            max_sl = st.number_input("Max SL", value=0.0100)
            rr = st.slider("Target R:R", 1.0, 10.0, 1.0, step=0.5)
            fee_cap = st.slider("Fee cap %R", 5, 100, 20)
            show_nofee = st.checkbox("Show no-fee TP", True)

    if not st.button("Generate"):
        return

    rows = []
    for stp in np.linspace(min_sl, max_sl, PTS):
        # -------- sizing modes --------
        if sizing.startswith("Include"):
            q, fixed = solve_size_exact(stp, price, R, exec_t, exec_v, maint_t, maint_v, days)
            eff_sl = stp
            tp = tp_needed(q, price, rr, R, exec_t, exec_v, maint_t, maint_v, days)
        elif sizing.startswith("Shrink"):
            q = R / stp  # keep original size
            if exec_t.startswith("Flat $"):
                eff_sl = stp - 2 * exec_v / q
            else:
                eff_sl = stp - 2 * fee_price_units(exec_t, exec_v, price)
            if eff_sl <= 0:
                continue
            tp = rr * stp
        else:  # Widen TP
            q = R / stp
            eff_sl = stp
            tp = tp_needed(q, price, rr, R, exec_t, exec_v, maint_t, maint_v, days)

        total_fees = usd_exec_fee(q, price, exec_t, exec_v)*2 + usd_maint_fee(q, price, maint_t, maint_v, days)
        rows.append(dict(SL=stp, Eff_SL=eff_sl, Size=q, Fees_pct=100*total_fees/R if R else 0, TP=tp))

    if not rows:
        st.error("No valid points – widen SL or raise risk")
        return

    df = pd.DataFrame(rows)
    min_ok = df[df.Fees_pct <= fee_cap].SL.min()

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.SL, y=df.Fees_pct, name="Fees %R", yaxis="y1"))
    fig.add_trace(go.Scatter(x=df.SL, y=df.TP, name="TP dist", yaxis="y2"))
    if show_nofee:
        fig.add_trace(go.Scatter(x=df.SL, y=rr*df.SL, name="TP no-fee", yaxis="y2", line=dict(dash="dash")))
    fig.add_hrect(y0=fee_cap, y1=df.Fees_pct.max(), yref="y1", fillcolor="rgba(255,0,0,0.05)", line_width=0)
    if not np.isnan(min_ok):
        fig.add_vline(x=min_ok, line_dash="dot", line_color="red", annotation_text="min SL @ fee cap", annotation_position="top left")
    fig.update_layout(xaxis_title="Technical SL", yaxis=dict(title="Fees %R"), yaxis2=dict(title="Distance", overlaying="y", side="right"), legend=dict(orientation="h", y=-0.25, x=0.5))
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(df)
    st.download_button("CSV", df.to_csv(index=False).encode(), "sl_vs_fees.csv", "text/csv")

if __name__ == "__main__":
    app()
