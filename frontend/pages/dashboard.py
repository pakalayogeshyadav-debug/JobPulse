"""
dashboard.py — Executive Dashboard for JobPulse.

Displays live KPIs and charts from PostgreSQL. No hardcoded values.
"""
import plotly.express as px
import streamlit as st

from frontend.components.db_health import check_db_health
from frontend.services.analytics_service import (
    get_company_hiring,
    get_home_kpis,
    get_jobs_over_time,
    get_live_jobs,
    get_pipeline_health,
    get_salary_by_role,
    get_top_skills,
    get_work_arrangement_breakdown,
)
from frontend.services.validation_service import get_validation_summary


def render():
    # ── Hero ─────────────────────────────────────────────────────────────────
    st.markdown("""
    <div style="text-align:center;padding:1.5rem 0;margin-bottom:1.5rem;
                background:linear-gradient(180deg,rgba(88,166,255,.12) 0%,rgba(13,17,23,0) 100%);
                border-radius:12px;">
        <h1 style="font-size:2.5rem;margin-bottom:0.3rem;
                   background:-webkit-linear-gradient(45deg,#58a6ff,#3fb950);
                   -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
            JobPulse Enterprise
        </h1>
        <p style="color:#8b949e;font-size:1rem;">
            Real-time Job Market Intelligence — Powered by Live PostgreSQL Data
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── DB Health ─────────────────────────────────────────────────────────────
    health = check_db_health()
    if health["connected"]:
        st.success(f"🟢 PostgreSQL Online  ·  {health['latency_ms']} ms  ·  {health.get('db_name','jobpulse')}")
    else:
        st.error(f"🔴 Database Offline — {health.get('error', 'Check connection settings')}")
        st.stop()

    # ── Top KPIs ──────────────────────────────────────────────────────────────
    kpis = get_home_kpis()
    val = get_validation_summary()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Jobs", f"{kpis['total_jobs']:,}")
    c2.metric("Companies", f"{kpis['total_companies']:,}")
    c3.metric("Skills Tracked", f"{kpis['total_skills']:,}")
    c4.metric("Avg Market Salary", f"${kpis['avg_salary']:,.0f}" if kpis["avg_salary"] else "N/A")
    c5.metric("Data Quality", f"{val['validation_percentage']:.1f}%",
              delta=f"{val['passed_records']:,} valid records")

    st.divider()

    # ── Charts Row 1 ──────────────────────────────────────────────────────────
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("📈 Top In-Demand Skills")
        skills_df = get_top_skills(15)
        if not skills_df.empty:
            fig = px.bar(
                skills_df.head(12),
                x="job_count",
                y="skill_name",
                color="skill_category",
                orientation="h",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig.update_layout(
                yaxis={"categoryorder": "total ascending"},
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=10, b=0),
                legend_title_text="Category",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No skill data available yet.")

    with col_r:
        st.subheader("💰 Salary by Role")
        salary_df = get_salary_by_role(15)
        if not salary_df.empty:
            valid = salary_df[salary_df["avg_salary_midpoint"] > 0]
            if not valid.empty:
                fig2 = px.scatter(
                    valid,
                    x="avg_salary_midpoint",
                    y="role",
                    size="total_jobs",
                    color="total_jobs",
                    color_continuous_scale="Blues",
                    labels={"avg_salary_midpoint": "Avg Salary ($)", "role": ""},
                )
                fig2.update_layout(
                    yaxis={"categoryorder": "total ascending"},
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0, r=0, t=10, b=0),
                )
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("No salary data with non-zero values.")
        else:
            st.info("No salary data available.")

    # ── Charts Row 2 ──────────────────────────────────────────────────────────
    col3, col4 = st.columns(2)

    with col3:
        st.subheader("🏢 Top Hiring Companies")
        co_df = get_company_hiring(10)
        if not co_df.empty:
            fig3 = px.bar(
                co_df,
                x="active_postings",
                y="company_name",
                orientation="h",
                color_discrete_sequence=["#58a6ff"],
            )
            fig3.update_layout(
                yaxis={"categoryorder": "total ascending"},
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("No company data available.")

    with col4:
        st.subheader("🗂️ Work Arrangement Split")
        arr_df = get_work_arrangement_breakdown()
        if not arr_df.empty:
            fig4 = px.pie(
                arr_df,
                names="work_type",
                values="job_count",
                hole=0.45,
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig4.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.info("No work arrangement data.")

    # ── Jobs Over Time ────────────────────────────────────────────────────────
    st.divider()
    st.subheader("📅 Job Posting Trends (Last 90 Days)")
    trend_df = get_jobs_over_time()
    if not trend_df.empty:
        fig5 = px.area(
            trend_df,
            x="date",
            y=["job_count", "remote_count"],
            labels={"value": "Jobs Posted", "date": "Date", "variable": "Type"},
            color_discrete_map={"job_count": "#58a6ff", "remote_count": "#3fb950"},
        )
        fig5.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig5, use_container_width=True)
    else:
        st.info("No job posting trend data available (posted_date may be NULL for this dataset).")

    # ── Pipeline Status ───────────────────────────────────────────────────────
    st.divider()
    st.subheader("🔄 ETL Pipeline Status")
    pipe_df = get_pipeline_health()
    if not pipe_df.empty:
        st.dataframe(
            pipe_df,
            use_container_width=True,
            column_config={
                "source_name": "Data Source",
                "total_runs": st.column_config.NumberColumn("Total Runs", format="%d"),
                "success_runs": st.column_config.NumberColumn("✅ Success", format="%d"),
                "failed_runs": st.column_config.NumberColumn("❌ Failed", format="%d"),
                "success_rate_pct": st.column_config.NumberColumn("Success Rate", format="%.1f%%"),
                "last_run_completed": st.column_config.DatetimeColumn("Last Run", format="YYYY-MM-DD HH:mm"),
                "latest_version": "Version",
            },
        )
    else:
        st.info("No pipeline run data available.")

    # ── Latest Jobs ───────────────────────────────────────────────────────────
    st.divider()
    st.subheader("🆕 Latest Job Postings")
    jobs_df = get_live_jobs(10)
    if not jobs_df.empty:
        display_cols = ["job_title", "company_name", "location_name", "work_arrangement",
                        "salary_min", "salary_max", "posted_date"]
        available = [c for c in display_cols if c in jobs_df.columns]
        st.dataframe(jobs_df[available], use_container_width=True)
    else:
        st.info("No job listings available.")
