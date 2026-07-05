import plotly.express as px
import streamlit as st

from frontend.services.validation_service import (
    get_data_quality_stats,
    get_validation_history,
    get_validation_summary,
)


def render():
    st.title('Validation Dashboard')
    st.markdown("Monitor data quality and ETL validation metrics.")

    summary = get_validation_summary()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Records Validated", f"{summary['total_validated']:,}")
    with col2:
        st.metric("Passed Records", f"{summary['passed_records']:,}")
    with col3:
        st.metric("Failed Records", f"{summary['failed_records']:,}")
    with col4:
        st.metric("Validation Score", f"{summary['validation_percentage']:.2f}%")
        
    st.markdown("---")
    
    col_l, col_r = st.columns([1, 1])
    
    with col_l:
        st.subheader("Data Quality Rules (Current DB State)")
        dq_df = get_data_quality_stats()
        if not dq_df.empty:
            st.dataframe(dq_df, use_container_width=True)
            
            # Simple pie chart for distribution if there are occurrences
            if dq_df['occurrences'].sum() > 0:
                fig = px.pie(
                    dq_df,
                    names='rule',
                    values='occurrences',
                    title='Quality Issues Distribution',
                    hole=0.4
                )
                fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data quality issues found.")
            
    with col_r:
        st.subheader("Validation History")
        history_df = get_validation_history()
        if not history_df.empty:
            fig2 = px.line(
                history_df,
                x='run_date',
                y=['passed', 'failed'],
                title='Validation Trend over Pipeline Runs',
                markers=True
            )
            fig2.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig2, use_container_width=True)
            st.dataframe(history_df, use_container_width=True)
        else:
            st.info("No validation history available.")
