import time

import pandas as pd
import streamlit as st

from frontend.services.database_service import get_db_engine


def render():
    st.markdown('<div class="element-container">', unsafe_allow_html=True)
    st.title("Enterprise SQL Playground")
    st.markdown("Execute ad-hoc read-only queries against the Data Warehouse. Destructive commands are blocked at the application layer.")
    
    # Examples / Saved Queries
    examples = {
        "Custom Query": "",
        "Count Jobs by Company": "SELECT company_name, COUNT(*) as c FROM jobs WHERE company_name IS NOT NULL GROUP BY company_name ORDER BY c DESC LIMIT 10;",
        "Top Remote Skills": "SELECT s.skill_name, COUNT(*) as c FROM bridge_job_skill b JOIN dim_skill s ON b.sk_skill_id = s.sk_skill_id JOIN jobs j ON b.sk_fact_job_id = j.job_id WHERE j.is_remote = TRUE GROUP BY s.skill_name ORDER BY c DESC LIMIT 10;",
        "Latest Pipeline Runs": "SELECT * FROM pipeline_runs ORDER BY created_at DESC LIMIT 5;"
    }
    
    selected_example = st.selectbox("Saved Queries", list(examples.keys()))
    default_query = examples[selected_example]
    
    # Syntax highlighting is native in st.text_area if used creatively, but we just use plain text area for input
    query = st.text_area("SQL Query", value=default_query, height=150)
    
    col1, col2, _ = st.columns([1, 1, 4])
    with col1:
        run_btn = st.button("▶ Run Query", type="primary", use_container_width=True)
    with col2:
        explain_btn = st.button("🔍 Explain Plan", use_container_width=True)
        
    if "query_history" not in st.session_state:
        st.session_state.query_history = []
        
    if run_btn or explain_btn:
        if not query.strip():
            st.warning("Please enter a SQL query.")
            return
            
        # Security: Read-Only check
        upper_query = query.upper()
        forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE", "COMMIT"]
        if any(f in upper_query for f in forbidden):
            st.error("Access Denied: Only SELECT operations are allowed.")
            return
            
        target_query = f"EXPLAIN ANALYZE {query}" if explain_btn else query
            
        try:
            engine = get_db_engine()
            start_time = time.time()
            with engine.connect() as conn:
                df = pd.read_sql(target_query, conn)
            execution_time = (time.time() - start_time) * 1000
            
            # Save history
            if not explain_btn:
                st.session_state.query_history.insert(0, {"query": query, "time_ms": execution_time, "rows": len(df)})
                if len(st.session_state.query_history) > 20:
                    st.session_state.query_history.pop()
                
            st.success(f"Execution complete in {execution_time:.0f} ms | Rows returned: {len(df)}")
            
            if explain_btn:
                plan_text = "\\n".join(df.iloc[:, 0].astype(str).tolist())
                st.code(plan_text, language="sql")
            else:
                st.dataframe(df, use_container_width=True)
                
                # CSV Export
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="⬇ Export Results (CSV)",
                    data=csv,
                    file_name='query_results.csv',
                    mime='text/csv',
                )
        except Exception as e:
            st.error("SQL Execution Error")
            st.code(str(e))
            
    st.markdown("---")
    with st.expander("Execution History"):
        if st.session_state.query_history:
            st.dataframe(pd.DataFrame(st.session_state.query_history), use_container_width=True)
        else:
            st.info("No queries executed in this session.")
    st.markdown('</div>', unsafe_allow_html=True)
