import streamlit as st

from frontend.services.log_service import get_available_log_files, parse_log_file


def render():
    st.title("Operational Logs")
    st.markdown("Monitor pipeline and application logs.")

    log_files = get_available_log_files()
    if not log_files:
        st.info("No log files found in the 'logs/' directory.")
        return

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        selected_file = st.selectbox("Select Log File", log_files, index=0)
    with col2:
        level_filter = st.selectbox("Log Level", ["ALL", "INFO", "WARNING", "ERROR", "DEBUG"])
    with col3:
        search_term = st.text_input("Search Logs", "")

    df = parse_log_file(selected_file)

    if df.empty:
        st.warning("Log file is empty or corrupted.")
        return

    # Filtering
    if level_filter != "ALL":
        df = df[df['level'] == level_filter]
        
    if search_term:
        df = df[df['message'].str.contains(search_term, case=False, na=False) | df['logger'].str.contains(search_term, case=False, na=False)]

    # Metrics
    c_info = len(df[df['level'] == 'INFO'])
    c_warn = len(df[df['level'] == 'WARNING'])
    c_err = len(df[df['level'] == 'ERROR'])
    
    st.markdown("---")
    m1, m2, m3 = st.columns(3)
    m1.metric("INFO", c_info)
    m2.metric("WARNING", c_warn)
    m3.metric("ERROR", c_err)
    
    st.markdown("### Log Viewer")
    
    def color_level(val):
        if val == 'ERROR': return 'color: #ff4b4b; font-weight: bold;'
        elif val == 'WARNING': return 'color: #ffa421; font-weight: bold;'
        elif val == 'DEBUG': return 'color: #808495;'
        return 'color: #00c04b;'
        
    st.dataframe(
        df.style.applymap(color_level, subset=['level']),
        use_container_width=True,
        height=600
    )
    
    col_dl, _ = st.columns([1, 4])
    with col_dl:
        if not df.empty:
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="⬇ Export Logs (CSV)",
                data=csv,
                file_name='exported_logs.csv',
                mime='text/csv',
            )
