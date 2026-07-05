import streamlit as st


def apply_enterprise_theme():
    st.markdown("""
    <style>
    /* Premium Enterprise SaaS Dark Theme */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    :root {
        --bg-color: #0d1117;
        --surface-color: rgba(22, 27, 34, 0.7);
        --primary-color: #58a6ff;
        --secondary-color: #8b949e;
        --text-main: #c9d1d9;
        --border-color: rgba(48, 54, 61, 0.5);
        --glass-bg: rgba(22, 27, 34, 0.6);
        --glass-border: rgba(255, 255, 255, 0.05);
        --success: #238636;
        --danger: #da3633;
        --warning: #d29922;
        --glow: 0 0 15px rgba(88, 166, 255, 0.15);
    }

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
        background-color: var(--bg-color);
        color: var(--text-main);
    }

    /* Glassmorphism Cards (st.metric, expander, dataframes) */
    div[data-testid="metric-container"], 
    div.stExpander, 
    div[data-testid="stDataFrame"] {
        background: var(--glass-bg);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid var(--glass-border);
        border-radius: 12px;
        padding: 1rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
    }

    div[data-testid="metric-container"]:hover {
        transform: translateY(-2px);
        box-shadow: var(--glow);
        border-color: var(--primary-color);
    }

    /* Buttons */
    button[kind="primary"] {
        background: linear-gradient(135deg, #1f6feb, #3fb950);
        border: none;
        color: white;
        border-radius: 8px;
        font-weight: 600;
        transition: opacity 0.2s ease, transform 0.2s ease;
    }
    button[kind="primary"]:hover {
        opacity: 0.9;
        transform: scale(1.02);
    }

    /* Sidebar Styling */
    section[data-testid="stSidebar"] {
        background-color: rgba(13, 17, 23, 0.95);
        border-right: 1px solid var(--border-color);
    }

    /* Headings */
    h1, h2, h3 {
        color: #ffffff;
        font-weight: 600;
        letter-spacing: -0.02em;
    }

    /* Custom Scrollbar */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    ::-webkit-scrollbar-track {
        background: transparent;
    }
    ::-webkit-scrollbar-thumb {
        background: #30363d;
        border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: #484f58;
    }

    /* Loading Shimmer Animation */
    @keyframes shimmer {
        0% { background-position: -1000px 0; }
        100% { background-position: 1000px 0; }
    }
    .stSpinner > div > div {
        border-color: var(--primary-color) transparent transparent transparent !important;
    }
    
    /* Fade In transitions for elements */
    .element-container {
        animation: fadeIn 0.5s ease-out;
    }
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }

    </style>
    """, unsafe_allow_html=True)
