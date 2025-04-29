# stop_loss_app.py  –  fee-centric SL/TP planner with editable broker presets
# Works on any Streamlit version:
# • Streamlit ≥1.25 → “Manage brokers” opens in a floating dialog (st.dialog)
# • Older versions  → form appears in a sidebar expander
# • Streamlit ≥1.42 uses st.rerun(); older keeps st.experimental_rerun

from __future__ import annotations
import json, pathlib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ─── page config must be first ───────────────────────────────────────────────
st.set_page_config(page_title="SL vs Fees", layout="centered")

# use correct rerun helper for all Streamlit versions
rerun = st.rerun if hasattr(st, "rerun") else st.experimental_rerun

# ─── 1 · persistence ─────────────────────────────────────────────────────────
PRESET_PATH = pathlib.Path(__file__).with_name("broker_presets.json")
DEFAULT_PRESETS = {
    "Binance Futures": {
        "exec": {
            "market": {"type": "% of notional (per leg)", "value": 0.04},
            "limit":  {"type": "% of notional (per leg)", "value": 0.02},
        },
        "maintenance": {"type": "% of notional per day", "value": 0.01},
    },
    "IC Markets RAW": {
        "exec": {
            "market": {"type": "Spread (price units per leg)", "value": 0.00008},
            "limit":  {"type": "Spread (price units per leg)", "value": 0.00005},
        },
        "maintenance": {"type": "None", "value": 0.0},
    },
}

@st.cache_resource
def load_presets() -> dict:
    if PRESET_PATH.exists():
        try:
            return json.loads(PRESET_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return DEFAULT_PRESETS.copy()

def save_presets(data: dict) -> None:
    PRESET_PATH.write_text(json.dumps(data, indent=2))

BROKERS = load_presets()
BROKERS.setdefault("Custom", {})          # always keep a custom slot

# ─── 2 · constants ───────────────────────────────────────────────────────────
ORDER_COMBOS = {
    "Market + Market": ("market", "market"),
    "Limit  + Limit" : ("limit",  "limit"),
    "Market + Limit" : ("market", "limit"),
}
EXEC_TYPES  = ["% of notional (per leg)", "Flat $ per leg", "Spread (price units per leg)"]
MAINT_TYPES = ["None", "% of notional per day", "Flat $ per day"]
PTS = 200   # stop-loss sweep resolution

# ─── 3 · fee helpers (math) ─────────────────────────────────────────────────
def usd_exec_fee(q, p, t, v):
    if t.startswith("%"):     return q * p * v / 100
    if t.startswith("Flat $"):return v
    if t.startswith("Spread"):return q * v
    return 0.0

def usd_maint_fee(q, p, t, v, d):
    if t == MAINT_TYPES[0]:   return 0.0
    if t.startswith("%"):     return q * p * v / 100 * d
    return v * d

def fee_price_units(t, v, p):
    return v if t.startswith("Spread") else p * v / 100 if t.startswith("%") else 0.0

def solve_size_exact(stp, p, R, et, ev, mt, mv, d):
    fixed = (ev*2 if et.startswith("Flat $") else 0.0) + (mv*d if mt.startswith("Flat $") else 0.0)
    coeff = (stp +
             (p*ev/100*2 if et.startswith("%") else ev*2 if et.startswith("Spread") else 0.0) +
             (p*mv/100*d if mt.startswith("%") else 0.0))
    size  = max((R-fixed)/coeff, 0.0) if coeff else 0.0
    return size, fixed

def tp_needed(q, p, rr, R, et, ev, mt, mv, d):
    gross = rr*R + usd_exec_fee(q,p,et,ev)*2 + usd_maint_fee(q,p,mt,mv,d)
    return gross/q if q else float("nan")

# ─── 4 · broker dialog (modal if available, expander fallback) ───────────────
def broker_dialog(existing: str | None = None):
    def body():
        template = {
            "exec": {"market": {"type": EXEC_TYPES[0], "value": 0.0},
                     "limit":  {"type": EXEC_TYPES[0], "value": 0.0}},
            "maintenance": {"type": MAINT_TYPES[0], "value": 0.0},
        }
        base = BROKERS.get(existing, template)

        name = st.text_input("Broker name", value=existing or "")
        st.subheader("Execution fees per leg")
        c1, c2 = st.columns(2)
        with c1:
            etm = st.selectbox("Market leg type", EXEC_TYPES,
                               index=EXEC_TYPES.index(base["exec"]["market"]["type"]))
            evm = st.number_input("Market leg value", value=base["exec"]["market"]["value"], key="evm")
        with c2:
            etl = st.selectbox("Limit  leg type", EXEC_TYPES,
                               index=EXEC_TYPES.index(base["exec"]["limit"]["type"]))
            evl = st.number_input("Limit  leg value", value=base["exec"]["limit"]["value"], key="evl")

        st.subheader("Maintenance fee")
        mt = st.selectbox("Maint type", MAINT_TYPES,
                          index=MAINT_TYPES.index(base["maintenance"]["type"]))
        mv = st.number_input("Maint value", value=base["maintenance"]["value"], key="mv")

        if st.button("Save broker"):
            if not name:
                st.error("Name cannot be empty")
            else:
                BROKERS[name] = {
                    "exec": {"market": {"type": etm, "value": evm},
                             "limit":  {"type": etl, "value": evl}},
                    "maintenance": {"type": mt, "value": mv},
                }
                save_presets(BROKERS)
                rerun()

        if existing and existing not in DEFAULT_PRESETS and st.button("Delete broker", type="secondary"):
            BROKERS.pop(existing, None)
            save_presets(BROKERS)
            rerun()

    if hasattr(st, "dialog"):      # Streamlit ≥1.25 → floating modal
        @st.dialog("Manage broker")
        def _launch():
            body()
        _launch()
    else:                          # older Streamlit → sidebar panel
        with st.sidebar.expander("Manage broker", True):
            body()

# ─── 5 · main app ────────────────────────────────────────────────────────────
def main():
    st.title("Stop-Loss tightness vs Fees & TP distance")

    # ---------- sidebar ----------
    with st.sidebar:
        sizing = st.radio("Sizing method",
                          ("Include fees in sizing", "Shrink SL by round-trip fees", "Widen TP to absorb fees"))
        st.subheader("Broker preset")
        broker = st.selectbox("Broker", list(BROKERS))
        if st.button("Manage brokers"):
            broker_dialog(None if broker == "Custom" else broker)

        combo  = st.radio("Order combo", list(ORDER_COMBOS), horizontal=True)
        leg1,_ = ORDER_COMBOS[combo]
        preset = BROKERS.get(broker, {})
        use_preset = broker != "Custom" and preset

        # ---- Risk
        with st.expander("Risk", True):
            acct = st.number_input("Account size", value=100.0, min_value=10.0)
            if st.radio("Mode", ("%","$"), horizontal=True) == "%":
                R = acct * st.number_input("Risk %", value=1.0) / 100
            else:
                R = st.number_input("Risk $", value=10.0)

        # ---- Fees
        with st.expander("Fees", True):
            price = st.number_input("Current price", value=1.10000, format="%.5f")
            if use_preset:
                et, ev = preset["exec"][leg1]["type"],  preset["exec"][leg1]["value"]
                mt, mv = preset["maintenance"]["type"], preset["maintenance"]["value"]
                st.info(f"Exec: {et} – {ev}\nMaintenance: {mt} – {mv}")
            else:
                et = st.selectbox("Exec type", EXEC_TYPES)
                ev = st.number_input("Exec value", value=0.10 if et.startswith("%") else 0.25)
                mt = st.selectbox("Maint type", MAINT_TYPES)
                mv = 0.0 if mt == MAINT_TYPES[0] else st.number_input("Maint value",
                                                                      value=0.05 if mt.startswith("%") else 0.10)
            days = st.number_input("Days held", value=1, min_value=1)

        # ---- Position
        with st.expander("Position", True):
            min_sl = st.number_input("Min SL", value=0.0001)
            max_sl = st.number_input("Max SL", value=0.0100)
            rr     = st.number_input("Target R:R", value=1.0, min_value=0.1)
            fee_cap= st.number_input("Fee cap %R", value=20.0)
            show_nf= st.checkbox("Show no-fee TP curve", True)

    if not st.button("Generate"):
        return

    # ---------- calculation ----------
    rows = []
    for stp in np.linspace(min_sl, max_sl, PTS):
        if sizing.startswith("Include"):
            q,_ = solve_size_exact(stp, price, R, et, ev, mt, mv, days)
            eff = stp
            tp  = tp_needed(q, price, rr, R, et, ev, mt, mv, days)
        elif sizing.startswith("Shrink"):
            q   = R / stp
            eff = stp - (2*ev/q if et.startswith("Flat $") else 2*fee_price_units(et, ev, price))
            if eff <= 0:
                continue
            tp  = rr * stp
        else:  # widen TP
            q   = R / stp
            eff = stp
            tp  = tp_needed(q, price, rr, R, et, ev, mt, mv, days)

        var_maint = 0.0 if mt.startswith("Flat $") else usd_maint_fee(q, price, mt, mv, days)
        tot       = usd_exec_fee(q, price, et, ev)*2 + var_maint + (mv*days if mt.startswith("Flat $") else 0.0)
        rows.append(
            dict(SL=stp, Eff_SL=eff, Size=q,
                 Fees_pct=tot*100/R if R else 0,
                 TP=tp,
                 BE_dist=tot/q if q else float("nan"))
        )

    if not rows:
        st.error("No valid points – widen SL or raise risk")
        return

    df = pd.DataFrame(rows)
    min_ok = df[df.Fees_pct <= fee_cap].SL.min()

    # ---------- plot ----------
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.SL, y=df.Fees_pct, name="Fees %R", yaxis="y1"))
    fig.add_trace(go.Scatter(x=df.SL, y=df.TP,        name="TP dist", yaxis="y2"))
    if show_nf:
        fig.add_trace(go.Scatter(x=df.SL, y=rr*df.SL, name="TP no-fee", yaxis="y2",
                                 line=dict(dash="dash")))

    # shaded fee-cap band
    fig.add_hrect(y0=fee_cap,
                  y1=df.Fees_pct.max(),
                  yref="y1",
                  fillcolor="rgba(255,0,0,0.05)",
                  line_width=0)

    # vertical line for minimum SL that respects cap
    if not np.isnan(min_ok):
        fig.add_vline(x=min_ok,
                      line_dash="dot",
                      line_color="red",
                      annotation_text="min SL @ fee cap",
                      annotation_position="top left")

    fig.update_layout(
        xaxis_title="Technical SL",
        yaxis=dict(title="Fees %R"),
        yaxis2=dict(title="Distance", overlaying="y", side="right"),
        legend=dict(orientation="h", y=-0.25, x=0.5, xanchor="center")
    )
    st.plotly_chart(fig, use_container_width=True)

    # ---------- table & download ----------
    st.dataframe(df)
    st.download_button(
        "Download CSV",
        df.to_csv(index=False).encode(),
        file_name="sl_vs_fees.csv",
        mime="text/csv"
    )

# ─── run app ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
