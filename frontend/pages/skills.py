"""
skills.py — Skills Analytics page.
"""
import plotly.express as px
import streamlit as st

from frontend.services.analytics_service import get_top_skills
from frontend.services.database_service import fetch_data


def render():
    st.title("Skills Analytics")
    st.markdown("Discover the most demanded tools, languages, and platforms.")

    df = get_top_skills(50)

    if df.empty:
        st.info("No skill data found. Run the ETL pipeline to load data.")
        return

    # KPIs
    c1, c2, c3 = st.columns(3)
    c1.metric("Unique Skills Tracked", len(df))
    c2.metric("Top Skill", df.iloc[0]["skill_name"])
    c3.metric("Top Skill Demand", f"{df.iloc[0]['job_count']:,} jobs")

    st.divider()

    # Category filter
    categories = ["All"] + sorted(df["skill_category"].dropna().unique().tolist())
    selected_cat = st.selectbox("Filter by Category", categories)
    filtered = df if selected_cat == "All" else df[df["skill_category"] == selected_cat]

    col_l, col_r = st.columns([3, 2])
    with col_l:
        st.subheader("Top Skills by Demand")
        fig = px.bar(
            filtered.head(20),
            x="job_count",
            y="skill_name",
            orientation="h",
            color="skill_category",
            color_discrete_sequence=px.colors.qualitative.Set2,
            labels={"job_count": "Jobs Requiring Skill", "skill_name": ""},
        )
        fig.update_layout(
            yaxis={"categoryorder": "total ascending"},
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.subheader("Category Distribution")
        cat_df = (
            df.groupby("skill_category")["job_count"]
            .sum()
            .reset_index()
            .sort_values("job_count", ascending=False)
        )
        fig2 = px.pie(
            cat_df,
            names="skill_category",
            values="job_count",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig2.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("Complete Skills Table")
    st.dataframe(
        filtered,
        use_container_width=True,
        column_config={
            "skill_name": "Skill",
            "skill_category": "Category",
            "job_count": st.column_config.NumberColumn("Jobs Demanding", format="%d"),
        },
    )
    csv = filtered.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Export CSV", csv, "skills.csv", "text/csv")
