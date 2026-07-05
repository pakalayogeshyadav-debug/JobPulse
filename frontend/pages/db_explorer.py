import pandas as pd
import streamlit as st

from frontend.services.database_service import get_db_engine
from frontend.services.warehouse_service import (
    get_columns_metadata,
    get_tables_metadata,
)


def render():
    st.markdown('<div class="element-container">', unsafe_allow_html=True)
    st.title("Database Explorer")
    st.markdown("Browse, filter, and export table data dynamically.")

    tables_df = get_tables_metadata()
    if tables_df.empty:
        st.warning("Database offline or no tables found.")
        return
        
    tables = tables_df['table_name'].tolist()
    
    col1, col2 = st.columns([1, 2])
    with col1:
        selected_table = st.selectbox("Select Table", tables)
    with col2:
        search_term = st.text_input("🔍 Quick Search (Searches all text columns)", help="Type to filter rows")
        
    st.markdown("---")
    
    engine = get_db_engine()
    
    try:
        cols_df = get_columns_metadata(selected_table)
        text_cols = cols_df[cols_df['data_type'].isin(['character varying', 'text', 'character'])]['column_name'].tolist()
        
        where_clause = ""
        params = {}
        if search_term and text_cols:
            conditions = []
            for col in text_cols:
                conditions.append(f"{col} ILIKE %(search)s")
            where_clause = " WHERE " + " OR ".join(conditions)
            params = {"search": f"%{search_term}%"}
            
        limit = st.slider("Row Limit", 10, 1000, 100)
        
        query = f"SELECT * FROM {selected_table}{where_clause} LIMIT %(limit)s"
        params["limit"] = limit
        
        with engine.connect() as conn:
            data_df = pd.read_sql(query, conn, params=params)
            
        st.subheader(f"Data Preview: {selected_table}")
        
        if not data_df.empty:
            st.dataframe(data_df, use_container_width=True)
            csv = data_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="⬇ Download Export (CSV)",
                data=csv,
                file_name=f'{selected_table}_export.csv',
                mime='text/csv',
                type="primary"
            )
        else:
            st.info("No records matched your search.")
            
    except Exception as e:
        st.error(f"Failed to load data from {selected_table}")
        st.code(str(e))
        
    st.markdown('</div>', unsafe_allow_html=True)
