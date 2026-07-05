"""
warehouse.py — Data Warehouse Explorer page.
Removed graphviz dependency — uses Streamlit graphviz_chart which renders
Graphviz DOT syntax as SVG server-side (no Python graphviz package needed).
"""
import streamlit as st

from frontend.services.database_service import fetch_data
from frontend.services.warehouse_service import (
    get_columns_metadata,
    get_foreign_keys,
    get_indexes_metadata,
    get_tables_metadata,
)


def _build_er_diagram(tables_df, get_fk_fn) -> str:
    """Build a DOT language ER diagram string without needing the graphviz package."""
    lines = [
        "digraph ERD {",
        '  rankdir=LR;',
        '  node [shape=box style="rounded,filled" fillcolor="#1a2233" fontcolor="white" color="#58a6ff"];',
        '  edge [color="#8b949e"];',
    ]
    for t in tables_df["table_name"]:
        lines.append(f'  "{t}";')
        fks = get_fk_fn(t)
        for _, row in fks.iterrows():
            lines.append(
                f'  "{row["table_name"]}" -> "{row["foreign_table_name"]}"'
                f' [label="{row["column_name"]}"];'
            )
    lines.append("}")
    return "\n".join(lines)


def render():
    st.title("Data Warehouse Explorer")
    st.markdown("Inspect schema, relationships, and storage metrics of the underlying PostgreSQL database.")

    tables_df = get_tables_metadata()

    if tables_df.empty:
        st.warning("Could not load warehouse metadata. Check database connection.")
        return

    # ── High-level metrics ────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    total_rows = tables_df["row_count"].sum() if not tables_df.empty else 0

    with col1:
        st.metric("Total Tables", len(tables_df))
    with col2:
        st.metric("Total Rows (Est.)", f"{int(total_rows):,}")
    with col3:
        size_df = fetch_data(
            "SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size"
        )
        st.metric("Warehouse Size", size_df.iloc[0]["db_size"] if not size_df.empty else "N/A")

    st.divider()

    tab_schema, tab_er, tab_explorer = st.tabs(["Schema Browser", "ER Diagram", "Table Inspector"])

    with tab_schema:
        st.subheader("All Tables & Storage")
        st.dataframe(
            tables_df,
            use_container_width=True,
            column_config={
                "table_name": "Table Name",
                "row_count": st.column_config.NumberColumn("Row Count (Est.)", format="%d"),
                "total_size": "Total Size",
                "table_size": "Table Data",
                "index_size": "Indexes",
            },
        )

    with tab_er:
        st.subheader("Entity Relationship Diagram")
        st.info("Diagram auto-generated from PostgreSQL foreign key constraints.")
        try:
            dot_source = _build_er_diagram(tables_df, get_foreign_keys)
            st.graphviz_chart(dot_source, use_container_width=True)
        except Exception as e:
            st.warning(f"Could not render ER diagram: {e}")
            st.markdown("**Manual relationship summary:**")
            for t in tables_df["table_name"]:
                fks = get_foreign_keys(t)
                if not fks.empty:
                    for _, row in fks.iterrows():
                        st.markdown(
                            f"- `{row['table_name']}.{row['column_name']}` → "
                            f"`{row['foreign_table_name']}.{row['foreign_column_name']}`"
                        )

    with tab_explorer:
        st.subheader("Table Inspector")
        selected_table = st.selectbox("Select Table", tables_df["table_name"].tolist())

        if selected_table:
            row_count_df = fetch_data(
                f"SELECT COUNT(*) AS exact_count FROM {selected_table}"  # noqa: S608
            )
            exact_count = int(row_count_df.iloc[0]["exact_count"]) if not row_count_df.empty else 0
            st.markdown(f"**Exact row count:** `{exact_count:,}`")

            st.markdown(f"**Columns for `{selected_table}`**")
            cols = get_columns_metadata(selected_table)
            st.dataframe(cols, use_container_width=True)

            col_left, col_right = st.columns(2)
            with col_left:
                st.markdown("**Indexes**")
                idxs = get_indexes_metadata(selected_table)
                st.dataframe(idxs, use_container_width=True)
            with col_right:
                st.markdown("**Foreign Keys**")
                fks = get_foreign_keys(selected_table)
                if not fks.empty:
                    st.dataframe(fks, use_container_width=True)
                else:
                    st.info("No foreign keys defined.")
