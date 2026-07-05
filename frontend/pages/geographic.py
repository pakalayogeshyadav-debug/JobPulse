import plotly.express as px
import streamlit as st

from frontend.services.geographic_service import (
    get_location_distribution,
    get_remote_vs_onsite,
)


def render():
    st.title("Geographic Analytics")
    st.markdown("Analyze job distribution and compensation across different regions.")
    
    col_l, col_r = st.columns([1, 1])
    
    with col_l:
        st.subheader("Work Type Distribution")
        remote_df = get_remote_vs_onsite()
        if not remote_df.empty:
            fig_remote = px.pie(
                remote_df,
                names='work_type',
                values='job_count',
                hole=0.4,
                color_discrete_sequence=['#58a6ff', '#238636']
            )
            fig_remote.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_remote, use_container_width=True)
            
    with col_r:
        st.subheader("Top Job Hubs")
        loc_df = get_location_distribution()
        if not loc_df.empty:
            fig_loc = px.bar(
                loc_df.head(10),
                x='job_count',
                y='location_name',
                orientation='h'
            )
            fig_loc.update_layout(yaxis={'categoryorder':'total ascending'}, plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_loc, use_container_width=True)
            
    st.markdown("---")
    st.subheader("Location Deep Dive")
    if not loc_df.empty:
        st.dataframe(
            loc_df,
            use_container_width=True,
            column_config={
                "location_name": "Location",
                "job_count": st.column_config.NumberColumn("Total Jobs", format="%d"),
                "avg_min_salary": st.column_config.NumberColumn("Avg Min Salary", format="$%d"),
                "avg_max_salary": st.column_config.NumberColumn("Avg Max Salary", format="$%d"),
                "remote_count": st.column_config.NumberColumn("Remote Opportunities", format="%d")
            }
        )
    else:
        st.info("No geographic data available.")
