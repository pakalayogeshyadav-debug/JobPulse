"""
pipeline.py — Live Pipeline Monitor page.

Shows pipeline run history from actual pipeline_runs table schema.
"""
import plotly.express as px
import streamlit as st

from frontend.services.analytics_service import get_pipeline_health
from frontend.services.database_service import fetch_data
from frontend.services.validation_service import get_validation_history


def render():
    st.title("Live Pipeline Monitor")
    st.markdown("Real-time ETL pipeline execution metrics from PostgreSQL.")

    # Summary row
    summary = fetch_data("""
        SELECT
            COUNT(*)                                                           AS total_runs,
            COUNT(*) FILTER (WHERE UPPER(status) = 'SUCCESS')                 AS success_count,
            COUNT(*) FILTER (WHERE UPPER(status) = 'FAILED')                  AS failed_count,
            MAX(completed_at)                                                  AS last_completed,
            ROUND(AVG(EXTRACT(EPOCH FROM (completed_at - started_at))), 0)
                                                                               AS avg_duration_sec
        FROM pipeline_runs
    """)

    if not summary.empty:
        row = summary.iloc[0]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Runs", int(row["total_runs"] or 0))
        c2.metric("Successful", int(row["success_count"] or 0))
        c3.metric("Failed", int(row["failed_count"] or 0))
        c4.metric("Last Completed", str(row["last_completed"])[:16] if row["last_completed"] else "N/A")
        c5.metric("Avg Duration", f"{int(row['avg_duration_sec'] or 0)}s")

    st.divider()

    # Pipeline source breakdown
    st.subheader("Source-Level Statistics")
    pipe_df = get_pipeline_health()
    if not pipe_df.empty:
        col_l, col_r = st.columns(2)
        with col_l:
            fig = px.bar(
                pipe_df,
                x="source_name",
                y=["success_runs", "failed_runs"],
                barmode="group",
                color_discrete_map={"success_runs": "#3fb950", "failed_runs": "#da3633"},
                labels={"value": "Runs", "variable": "Status"},
            )
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_r:
            st.dataframe(
                pipe_df,
                use_container_width=True,
                column_config={
                    "source_name": "Source",
                    "total_runs": st.column_config.NumberColumn("Runs", format="%d"),
                    "success_rate_pct": st.column_config.NumberColumn("Success %", format="%.1f%%"),
                    "last_run_completed": st.column_config.DatetimeColumn("Last Run", format="YYYY-MM-DD HH:mm"),
                },
            )

    st.divider()

    # Full run history
    st.subheader("Run History")
    history = get_validation_history()
    if not history.empty:
        col_config = {
            "run_id": "Run ID",
            "source_name": "Source",
            "status": "Status",
            "run_date": st.column_config.DatetimeColumn("Started At", format="YYYY-MM-DD HH:mm:ss"),
            "completed_at": st.column_config.DatetimeColumn("Completed At", format="YYYY-MM-DD HH:mm:ss"),
            "duration_seconds": st.column_config.NumberColumn("Duration (s)", format="%d"),
            "jobs_in_run": st.column_config.NumberColumn("Jobs Loaded", format="%d"),
            "pipeline_version": "Version",
        }
        st.dataframe(history, use_container_width=True, column_config=col_config)
    else:
        st.info("No pipeline run history found.")

    # Trigger panel
    st.divider()
    st.subheader("Manual Execution Triggers")
    st.warning("⚠️ These actions modify the live database.")

    col_a, col_b, _ = st.columns([1, 1, 3])
    with col_a:
        if st.button("▶ Run ETL Pipeline", type="primary", use_container_width=True):
            with st.spinner("Executing ETL pipeline..."):
                try:
                    import sys, os
                    from pathlib import Path
                    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
                    from jobpulse.pipeline.orchestrator import PipelineOrchestrator
                    from jobpulse.config.settings import Settings
                    from jobpulse.database.engine import create_db_engine
                    settings = Settings()
                    engine = create_db_engine(settings)
                    orchestrator = PipelineOrchestrator(settings, engine)
                    report = orchestrator.run()
                    st.success(f"Pipeline completed: {report.status}")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Pipeline execution failed: {exc}")

    with col_b:
        if st.button("🔄 Clear Cache", use_container_width=True):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.success("Cache cleared.")
            st.rerun()
