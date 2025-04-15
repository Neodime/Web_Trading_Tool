import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

def calculate_position_size_and_fees(
    stop_distance: float,
    current_price: float,
    risk_budget: float,
    execution_fee_type: str,
    execution_fee_value: float,
    maintenance_fee_type: str,
    maintenance_fee_value: float,
    days_held: int
):
    """
    Given a stop-loss distance and fee parameters, calculate:
      - The maximum position size x such that:
        (price-based loss + total fees) <= risk_budget
      - The total fees in absolute terms
      - The portion of risk consumed by fees (in %)
      - The portion of risk consumed by price movement (in %)
    """
    # Convert percentage fees to fractions where appropriate
    if execution_fee_type == "Percentage":
        # Execution fee fraction (combined open/close)
        ex_frac = execution_fee_value / 100.0
        ex_abs = 0.0
    else:
        # Absolute execution fee
        ex_frac = 0.0
        ex_abs = execution_fee_value

    if maintenance_fee_type == "Percentage":
        # Maintenance fee fraction per day
        maint_frac = (maintenance_fee_value / 100.0) * days_held
        maint_abs = 0.0
    else:
        # Absolute maintenance fee per day times days_held
        maint_frac = 0.0
        maint_abs = maintenance_fee_value * days_held

    # Combine absolute fees
    total_abs_fees = ex_abs + maint_abs
    # Combine fraction fees
    total_frac_fees = ex_frac + maint_frac

    # We want x such that:
    #    x * stop_distance + [x * current_price * total_frac_fees + total_abs_fees] = risk_budget
    # => x * (stop_distance + current_price * total_frac_fees) + total_abs_fees = risk_budget
    # => x = (risk_budget - total_abs_fees) / (stop_distance + current_price * total_frac_fees)
    numerator = risk_budget - total_abs_fees
    denominator = stop_distance + current_price * total_frac_fees

    # If fees alone exceed risk_budget or denominator <= 0, position size must be zero.
    if denominator <= 0 or numerator <= 0:
        position_size = 0.0
    else:
        position_size = numerator / denominator
        if position_size < 0:
            position_size = 0.0

    # Now calculate the actual monetary fees at that position size
    # Execution fee in absolute terms
    actual_execution_fee = ex_frac * position_size * current_price + ex_abs
    # Maintenance fee in absolute terms
    if maintenance_fee_type == "Percentage":
        actual_maintenance_fee = (maintenance_fee_value / 100.0) * position_size * current_price * days_held
    else:
        actual_maintenance_fee = maintenance_fee_value * days_held

    total_fees = actual_execution_fee + actual_maintenance_fee

    # Price-based loss if the stop is hit
    price_loss = position_size * stop_distance

    # Convert to percentages of total risk budget
    if risk_budget > 0:
        fees_pct_of_risk = (total_fees / risk_budget) * 100.0
        price_loss_pct_of_risk = (price_loss / risk_budget) * 100.0
    else:
        fees_pct_of_risk = 0.0
        price_loss_pct_of_risk = 0.0

    return position_size, total_fees, fees_pct_of_risk, price_loss_pct_of_risk

def main():
    st.title("Stop-Loss Distance vs. Fees and Overall Risk")

    st.sidebar.header("Account Settings")
    account_size = st.sidebar.number_input("Account size", value=1000.0, step=100.0, min_value=0.0)
    risk_percent = st.sidebar.number_input("Risk % of account per trade", value=1.0, step=0.1, min_value=0.0)

    st.sidebar.header("Instrument Settings")
    instrument = st.sidebar.text_input("Instrument (e.g. EUR/USD, BTC/USDT)", value="EUR/USD")
    current_price = st.sidebar.number_input("Current price", value=1.1000, step=0.0001, min_value=0.0)

    st.sidebar.header("Execution Fee")
    execution_fee_type = st.sidebar.radio("Execution fee type", ["Percentage", "Absolute"], index=0)
    if execution_fee_type == "Percentage":
        execution_fee_value = st.sidebar.number_input("Execution fee (%)", value=0.10, step=0.01, min_value=0.0)
    else:
        execution_fee_value = st.sidebar.number_input("Execution fee (flat)", value=0.50, step=0.1, min_value=0.0)

    st.sidebar.header("Maintenance Fee")
    maintenance_fee_type = st.sidebar.radio("Maintenance fee type", ["Percentage", "Absolute"], index=0)
    if maintenance_fee_type == "Percentage":
        maintenance_fee_value = st.sidebar.number_input("Maintenance fee (%) per day", value=0.05, step=0.01, min_value=0.0)
    else:
        maintenance_fee_value = st.sidebar.number_input("Maintenance fee (flat) per day", value=0.10, step=0.1, min_value=0.0)

    days_held = st.sidebar.number_input("Days to hold", value=1, step=1, min_value=1)

    st.sidebar.header("Stop-Loss Range")
    min_sl = st.sidebar.number_input("Min SL distance (absolute)", value=0.0005, step=0.0001, min_value=0.0)
    max_sl = st.sidebar.number_input("Max SL distance (absolute)", value=0.0100, step=0.0010, min_value=0.0)
    n_points = st.sidebar.slider("Number of steps", min_value=10, max_value=200, value=50)

    st.write("## Instructions")
    st.write(
        "1. Adjust all parameters in the **sidebar**.\n"
        "2. Press **Calculate** to generate the chart.\n"
        "3. The chart shows how fees (and price-based loss) vary as you move your stop-loss closer or farther.\n\n"
        "**Note**: All calculations assume a simplistic model where:\n"
        "- Position size is determined so total risk (stop-loss loss + fees) equals your risk limit.\n"
        "- Fees can be percentage-based (applied to notional) or a flat amount.\n"
        "- Maintenance fees accumulate over the specified holding period."
    )

    if st.button("Calculate"):
        risk_budget = account_size * (risk_percent / 100.0)

        distances = np.linspace(min_sl, max_sl, n_points)
        records = {
            "Stop Distance": [],
            "Position Size": [],
            "Total Fees ($)": [],
            "Fees % of Risk": [],
            "Price-based Loss % of Risk": []
        }

        for d in distances:
            (
                position_size,
                total_fees,
                fees_pct_of_risk,
                price_loss_pct_of_risk
            ) = calculate_position_size_and_fees(
                stop_distance=d,
                current_price=current_price,
                risk_budget=risk_budget,
                execution_fee_type=execution_fee_type,
                execution_fee_value=execution_fee_value,
                maintenance_fee_type=maintenance_fee_type,
                maintenance_fee_value=maintenance_fee_value,
                days_held=days_held
            )
            records["Stop Distance"].append(d)
            records["Position Size"].append(position_size)
            records["Total Fees ($)"].append(round(total_fees, 4))
            records["Fees % of Risk"].append(fees_pct_of_risk)
            records["Price-based Loss % of Risk"].append(price_loss_pct_of_risk)

        df = pd.DataFrame(records)

        st.write("### Fees as a Percentage of Risk vs. Stop Distance")
        fig_fees = px.line(
            df, 
            x="Stop Distance", 
            y="Fees % of Risk",
            labels={"Stop Distance": "Stop-Loss Distance", "Fees % of Risk": "Fees (% of Risk Budget)"},
            title="Fees (% of Risk) vs. Stop Distance"
        )
        st.plotly_chart(fig_fees, use_container_width=True)

        st.write("### Fees & Price-Based Loss as % of Risk")
        fig_combo = px.line(
            df, 
            x="Stop Distance", 
            y=["Fees % of Risk", "Price-based Loss % of Risk"],
            labels={
                "Stop Distance": "Stop-Loss Distance", 
                "value": "Percentage of Risk Budget", 
                "variable": "Metric"
            },
            title="Fees and Price-Based Loss (% of Risk) vs. Stop Distance"
        )
        st.plotly_chart(fig_combo, use_container_width=True)

        st.write("### Detailed Results")
        st.dataframe(df)

if __name__ == "__main__":
    main()
