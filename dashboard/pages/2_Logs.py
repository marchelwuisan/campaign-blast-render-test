import streamlit as st
from dashboard.api import get

st.set_page_config(page_title="Blast Logs", page_icon="📋", layout="wide")
st.title("Blast Logs hehe")

with st.sidebar:
    search = st.text_input("Search customer ID or phone")
    since = st.date_input("Since", value=None)
    sort_by = st.selectbox("Sort by", ["sent_at", "customer_id", "status", "blast_id"])
    order = st.radio("Order", ["desc", "asc"], horizontal=True)
    limit = st.number_input(
        "Rows per page", min_value=10, max_value=200, value=50, step=10
    )

if "logs_offset" not in st.session_state:
    st.session_state.logs_offset = 0

params = {
    "limit": limit,
    "offset": st.session_state.logs_offset,
    "sort_by": sort_by,
    "order": order,
}
if search:
    params["search"] = search
if since:
    params["since"] = since.isoformat()

try:
    data = get("/blast/logs", params=params)
    total = data["total"]
    results = data["results"]

    st.caption(f"{total} total records")

    if results:
        st.dataframe(results, use_container_width=True)

    else:
        st.info("No logs found.")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if (
            st.button("← Prev", use_container_width=True)
            and st.session_state.logs_offset >= limit
        ):
            st.session_state.logs_offset -= limit
            st.rerun()
    with col2:
        st.caption(
            f"Showing {st.session_state.logs_offset + 1}-{min(st.session_state.logs_offset + limit, total)} of {total}",
            text_alignment="center",
        )
    with col3:
        if (
            st.button("Next →", use_container_width=True)
            and st.session_state.logs_offset + limit < total
        ):
            st.session_state.logs_offset += limit
            st.rerun()

except Exception as e:
    st.error(str(e))
