"""
companies.py — Company Hiring Analytics page.
"""
import plotly.express as px
import streamlit as st

from frontend.services.analytics_service import get_company_hiring


def render():
    st.title("Company Hiring Activity")
    st.markdown("Companies actively hiring for data and technology roles.")

    df = get_company_hiring(50)

    if df.empty:
        st.info("No company data available.")
        return

    # KPIs
    c1, c2, c3 = st.columns(3)
    c1.metric("Companies Hiring", len(df))
    c2.metric("Total Active Postings", f"{df['active_postings'].sum():,}")
    c3.metric("Remote Roles Available", f"{df['remote_roles'].sum():,}")

    st.divider()

    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("Top 15 Companies by Postings")
        fig = px.bar(
            df.head(15),
            x="active_postings",
            y="company_name",
            orientation="h",
            color="remote_roles",
            color_continuous_scale="Blues",
            labels={"active_postings": "Job Postings", "company_name": ""},
        )
        fig.update_layout(
            yaxis={"categoryorder": "total ascending"},
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.subheader("Average Salary by Company")
        salary_df = df[df["avg_salary"].notna() & (df["avg_salary"] > 0)].head(15)
        if not salary_df.empty:
            fig2 = px.scatter(
                salary_df,
                x="avg_salary",
                y="company_name",
                size="active_postings",
                color="avg_salary",
                color_continuous_scale="Greens",
                labels={"avg_salary": "Avg Salary ($)", "company_name": ""},
            )
            fig2.update_layout(
                yaxis={"categoryorder": "total ascending"},
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Salary data not available for these companies.")

    st.divider()
    st.subheader("Full Company Table")
    st.dataframe(
        df,
        use_container_width=True,
        column_config={
            "company_name": "Company",
            "active_postings": st.column_config.NumberColumn("Postings", format="%d"),
            "remote_roles": st.column_config.NumberColumn("Remote Roles", format="%d"),
            "avg_salary": st.column_config.NumberColumn("Avg Salary", format="$%,.0f"),
        },
    )

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Export CSV", csv, "companies.csv", "text/csv")
