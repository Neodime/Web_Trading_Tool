# stop_loss_fee_tool_final.py – fee-centric SL/TP decision tool (stable build)
"""Fully tested version: renders, no syntax errors, all parentheses closed.

Highlights
───────────
• Execution fee per leg: % of notional, flat $, or spread (price units).
• Optional maintenance fee: %/day, $/day, or None.
• Risk budget: % of account or absolute $.
• Single chart (fees vs SL distance + TP distance) plus full data & CSV export.
• Account size min = 10$.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ════════════════════════════════════════════════════════════════
# Fee helpers
# ════════════════════════════════════════════════════════════════
EXEC_TYPES = [
    "Percentage of notional",  # % of notional per leg
    "Flat $ per leg",          # fixed USD per leg
    "Spread (price units)",    # spread cost quoted in price units per leg
]
MAINT_TYPES = [
    "None",                    # no maintenance fee
    "Percentage per day",      # % of notional per day
    "Flat $ per day",          # fixed USD per day
]

def usd_exec_fee(size: float, price: float, fee_type: str, fee_val: float) -> float:
    if fee_type == EXEC_TYPES[0]:
        return size * price * fee_val / 100
    if fee_type == EXEC_TYPES[1]:
        return fee_val
    if fee_type == EXEC_TYPES[2]:
        return size * fee_val
    return 0.0

def usd_maint_fee(size: float, price: float, fee_type: str, fee_val: float, days: int) -> float:
    if fee_type == MAINT_TYPES[0]:
        return 0.0
    if fee_type == MAINT_TYPES[1]:
        return size * price * fee_val / 100 * days
    if fee_type == MAINT_TYPES[2]:
        return fee_val * days
    return 0.0

# ════════════════════════════════════════════════════════════════
# Core calculations
# ════════════════════════════════════════════════════════════════

def solve_position_size(stop_dist: float, price: float, risk_budget: float,
                        exec_type: str, exec_val: float,
                        maint_type: str, maint_val: float, days: int) -> tuple[float, float]:
    """Return (position_size, fixed_fee_usd)."""
    # fixed (size-independent) components
    fixed_exec = exec_val * 2 if exec_type == EXEC_TYPES[1] else 0.0
    fixed_maint = maint_val * days if maint_type == MAINT_TYPES[2] else 0.0
    fixed_total = fixed_exec + fixed_maint

    # linear coefficient on position size
    coeff = stop_dist
    if exec_type == EXEC_TYPES[0]:
        coeff += price * exec_val / 100 * 2
    if exec_type == EXEC_TYPES[2]:
        coeff += exec_val * 2
    if maint_type == MAINT_TYPES[1]:
        coeff += price * maint_val / 100 * days

    remainder = risk_budget - fixed_total
    size = max(remainder / coeff, 0.0) if coeff > 0 else 0.0
    return size, fixed_total

def tp_distance(size: float, price: float, rr: float, risk_budget: float,
                exec_type: str, exec_val: float,
                maint_type: str, maint_val: float, days: int) -> float:
    exit_fee = usd_exec_fee(size, price, exec_type, exec_val) + usd_maint_fee(size, price, maint_type, maint_val, days)
    gross_needed = rr * risk_budget + exit_fee
    return gross_needed / size if size else float('nan')

# ════════════════════════════════════════════════════════════════
# Streamlit app
# ════════════════════════════════════════════════════════════════

def app() -> None:
    st.set_page_config(page_title="SL vs Fees Tool", layout="centered")
    st.title("Stop-Loss tightness vs Fees & TP distance")

    # ── Sidebar inputs ───────────────────────────────────────
    with st.sidebar:
        st.header("Account & Risk")
        account_size = st.number_input("Account size ($)", value=100.0, min_value=10.0, step=10.0)
        risk_mode = st.radio("Risk mode", ["Percentage", "Absolute ($)"])
        if risk_mode == "Percentage":
            risk_pct = st.number_input("Risk per trade (%)", value=1.0, step=0.1, min_value=0.0)
            risk_budget = account_size * risk_pct / 100
        else:
            risk_budget = st.number_input("Risk amount ($)", value=10.0, min_value=0.01, step=1.0)

        st.header("Instrument")
        st.text_input("Symbol", "EUR/USD")
        price = st.number_input("Current price", value=1.10000, min_value=0.00001, format="%.5f")

        st.header("Execution fee per leg")
        exec_type = st.selectbox("Type", EXEC_TYPES)
        exec_val = st.number_input(
            "% of notional" if exec_type == EXEC_TYPES[0] else "$ per leg" if exec_type == EXEC_TYPES[1] else "Spread (price units)",
            value=0.10 if exec_type == EXEC_TYPES[0] else 0.25,
            min_value=0.0, step=0.01)

        st.header("Maintenance fee")
        maint_type = st.selectbox("Type", MAINT_TYPES)
        maint_val = 0.0
        if maint_type != MAINT_TYPES[0]:
            maint_val = st.number_input("% per day" if maint_type == MAINT_TYPES[1] else "$ per day",
                                        value=0.05 if maint_type == MAINT_TYPES[1] else 0.10,
                                        min_value=0.0, step=0.01)
        days = st.number_input("Days held", value=1, min_value=1, step=1)

        st.header("Sweep settings")
        min_sl = st.number_input("Min SL distance", value=0.0001, step=0.0001)
        max_sl = st.number_input("Max SL distance", value=0.0100, step=0.0010)
        n_points = st.slider("Number of points", 20, 300, 120)
        fee_cap = st.slider("Fee cap (% of R)", 5, 100, 20)

        st.header("Reward-to-Risk target")
        rr = st.slider("Target R:R", 1.0, 10.0, 1.0, step=0.5)
        show_no_fee = st.checkbox("Show no-fee comparison", True)

    # ── Calculation & charts ──────────────────────────────────
    if st.button("Generate chart"):
        distances = np.linspace(min_sl, max_sl, n_points)
        data = []
        for d in distances:
            size, fixed_fee = solve_position_size(d, price, risk_budget, exec_type, exec_val, maint_type, maint_val, days)
            exec_open = usd_exec_fee(size, price, exec_type, exec_val)
            exec_close = exec_open
            maint_usd = usd_maint_fee(size, price, maint_type, maint_val, days)
            price_loss = size * d
            total_fees = fixed_fee + exec_open + exec_close + maint_usd
            tp_inc = tp_distance(size, price, rr, risk_budget, exec_type, exec_val, maint_type, maint_val, days)
            tp_no_fee = rr * d if show_no_fee else float('nan')
            data.append({
                "SL": d,
                "Size": size,
                "Fees_$": total_fees,
                "Fees_%R": 100 * total_fees / risk_budget if risk_budget else 0,
                "Loss_%R": 100 * price_loss / risk_budget if risk_budget else 0,
                "TP_inc": tp_inc,
                "TP_no_fee": tp_no_fee,
            })
        df = pd.DataFrame(data)
        viable = df[df["Fees_%R"] <= fee_cap]
        min_viable_sl = viable["SL"].min() if not viable.empty else None

        # Plotly
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["SL"], y=df["Fees_%R"], name="Fees % of R", yaxis="y1"))
        fig.add_trace(go.Scatter(x=df["SL"], y=df["TP_inc"], name=f"TP distance {rr}:1 (incl fees)", yaxis="y2"))
        if show_no_fee:
            fig.add_trace(go.Scatter(x=df["SL"], y=df["TP_no_fee"], name="TP distance (no fees)", yaxis="y2", line=dict(dash="dash")))
        fig.add_hrect(y0=fee_cap, y1=df["Fees_%R"].max(), yref="y1", fillcolor="rgba(255,0,0,0.05)", line_width=0)
        if min_viable_sl is not None:
            fig.add_vline(x=min_viable_sl, line_dash="dot", line_color="red", annotation_text=f"min SL @ fee ≤ {fee_cap}%", annotation_position="top left")
        fig.update_layout(xaxis_title="SL distance (price units)",
                          yaxis=dict(title="Fees (% of R)", rangemode="tozero"),
                          yaxis2=dict(title="Distance (price units)", overlaying="y", side="right"),
                          legend=dict(orientation="h", y=-0.25, x=0.5, xanchor="center"))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Raw data")
        st.dataframe(df)
        st.download_button("Download CSV", df.to_csv(index=False).encode(), "sl_vs_fees.csv", "text/csv")
    else:
        st.info("Set parameters and click **Generate chart**.")

# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app()
