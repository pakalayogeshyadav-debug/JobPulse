import pandas as pd
import streamlit as st

from frontend.services.database_service import fetch_data


@st.cache_data(ttl=600)
def get_tables_metadata() -> pd.DataFrame:
    query = """
        SELECT
            relname as table_name,
            n_live_tup as row_count,
            pg_size_pretty(pg_total_relation_size(relid)) as total_size,
            pg_size_pretty(pg_relation_size(relid)) as table_size,
            pg_size_pretty(pg_indexes_size(relid)) as index_size
        FROM pg_stat_user_tables
        ORDER BY n_live_tup DESC
    """
    return fetch_data(query)

@st.cache_data(ttl=600)
def get_columns_metadata(table_name: str) -> pd.DataFrame:
    query = """
        SELECT 
            column_name, 
            data_type, 
            is_nullable, 
            column_default
        FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = %(table_name)s
        ORDER BY ordinal_position
    """
    return fetch_data(query, {"table_name": table_name})

@st.cache_data(ttl=600)
def get_indexes_metadata(table_name: str) -> pd.DataFrame:
    query = """
        SELECT 
            indexname as index_name, 
            indexdef as index_definition
        FROM pg_indexes 
        WHERE schemaname = 'public' AND tablename = %(table_name)s
    """
    return fetch_data(query, {"table_name": table_name})

@st.cache_data(ttl=600)
def get_foreign_keys(table_name: str) -> pd.DataFrame:
    query = """
        SELECT
            tc.table_name, 
            kcu.column_name, 
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name 
        FROM 
            information_schema.table_constraints AS tc 
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
              AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name = %(table_name)s
    """
    return fetch_data(query, {"table_name": table_name})
