"""
salary.py — Salary Analytics page.
"""
import plotly.express as px
import streamlit as st

from frontend.services.analytics_service import get_salary_by_role
from frontend.services.database_service import fetch_data


def render():
    st.title("Salary Analytics")
    st.markdown("Market salary benchmarks aggregated by role — sourced from live job postings.")

    df = get_salary_by_role(30)

    if df.empty:
        st.info("No salary data available. Most jobs may not include salary information.")
        return

    valid = df[df["avg_salary_midpoint"] > 0].copy()

    if valid.empty:
        st.info("No jobs with non-zero salary data found.")
        return

    # KPIs
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Roles with Salary Data", len(valid))
    c2.metric("Highest Avg Salary", f"${valid['avg_salary_midpoint'].max():,.0f}")
    c3.metric("Lowest Avg Salary", f"${valid['avg_salary_midpoint'].min():,.0f}")
    c4.metric("Overall Market Median", f"${valid['avg_salary_midpoint'].median():,.0f}")

    st.divider()

    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("Salary Range by Role")
        # Show min/midpoint/max as grouped bars
        top15 = valid.head(15)
        fig = px.bar(
            top15,
            x="avg_salary_midpoint",
            y="role",
            error_x_minus=top15["avg_salary_midpoint"] - top15["avg_salary_min"],
            error_x=top15["avg_salary_max"] - top15["avg_salary_midpoint"],
            orientation="h",
            color="total_jobs",
            color_continuous_scale="Blues",
            labels={"avg_salary_midpoint": "Avg Midpoint ($)", "role": ""},
        )
        fig.update_layout(
            yaxis={"categoryorder": "total ascending"},
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.subheader("Salary vs. Number of Postings")
        fig2 = px.scatter(
            valid.head(25),
            x="total_jobs",
            y="avg_salary_midpoint",
            text="role",
            size="total_jobs",
            color="avg_salary_midpoint",
            color_continuous_scale="Greens",
            labels={"total_jobs": "Number of Postings", "avg_salary_midpoint": "Avg Salary ($)"},
        )
        fig2.update_traces(textposition="top center", textfont_size=9)
        fig2.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("Detailed Salary Table")
    st.dataframe(
        valid,
        use_container_width=True,
        column_config={
            "role": "Job Role",
            "total_jobs": st.column_config.NumberColumn("# Postings", format="%d"),
            "avg_salary_min": st.column_config.NumberColumn("Avg Min", format="$%,.0f"),
            "avg_salary_max": st.column_config.NumberColumn("Avg Max", format="$%,.0f"),
            "avg_salary_midpoint": st.column_config.NumberColumn("Avg Midpoint", format="$%,.0f"),
            "lowest_salary": st.column_config.NumberColumn("Absolute Min", format="$%,.0f"),
            "highest_salary": st.column_config.NumberColumn("Absolute Max", format="$%,.0f"),
            "salary_currency": "Currency",
        },
    )
    csv = valid.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Export CSV", csv, "salary_benchmarks.csv", "text/csv")
