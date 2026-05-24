import streamlit as st
from dashboard.api import get

st.set_page_config(page_title="At-Risk Customers", page_icon="👥", layout="wide")
st.title("At-Risk Customers")

# Load all customers once per session
if "all_customers" not in st.session_state:
    with st.spinner("Running engine..."):
        try:
            data = get("/customers/at-risk", params={"limit": 9999, "offset": 0})
            st.session_state.all_customers = data["results"]
        except Exception as e:
            st.error(str(e))
            st.stop()

if st.button("Refresh"):
    del st.session_state["all_customers"]
    st.session_state.customers_offset = 0
    st.rerun()

# Sidebar filters (applied client-side)
with st.sidebar:
    risk_level = st.selectbox("Risk Level", ["All", "HIGH", "MEDIUM", "LOW"])
    search = st.text_input("Search customer ID or name")
    sort_by = st.selectbox("Sort by", ["days_since_last_purchase", "rfm_combined", "total_spend"])
    order = st.radio("Order", ["desc", "asc"], horizontal=True)
    limit = int(st.number_input("Rows per page", min_value=10, max_value=200, value=50, step=10))


def flatten(c: dict) -> dict:
    rfm = c.get("rfm") or {}
    spend = c.get("spend_summary") or {}
    return {
        "customer_id": c["customer_id"],
        "name": c["name"],
        "phone": c["phone"],
        "risk_level": c["risk_level"],
        "triggered_rules": ", ".join(c.get("triggered_rules") or []),
        "days_since_last_purchase": c["days_since_last_purchase"],
        "r_score": rfm.get("r_score"),
        "f_score": rfm.get("f_score"),
        "m_score": rfm.get("m_score"),
        "rfm_combined": rfm.get("combined_score"),
        "total_spend": spend.get("total_spend"),
        "avg_order_value": round(spend.get("avg_order_value") or 0, 2),
        "top_category": spend.get("top_category"),
    }


filtered = [flatten(c) for c in st.session_state.all_customers]

if risk_level != "All":
    filtered = [c for c in filtered if c["risk_level"] == risk_level]

if search:
    s = search.lower()
    filtered = [c for c in filtered if s in (c["customer_id"] or "").lower() or s in (c["name"] or "").lower()]

sort_key = {"days_since_last_purchase": "days_since_last_purchase", "rfm_combined": "rfm_combined", "total_spend": "total_spend"}.get(sort_by, "days_since_last_purchase")
filtered.sort(key=lambda c: (c[sort_key] is None, c[sort_key] or 0), reverse=(order == "desc"))

total = len(filtered)
st.caption(f"{total} at-risk customers")

if "customers_offset" not in st.session_state:
    st.session_state.customers_offset = 0

offset = st.session_state.customers_offset
page_data = filtered[offset: offset + limit]

if page_data:
    st.dataframe(page_data, use_container_width=True)
else:
    st.info("No at-risk customers found.")

col1, col2, col3 = st.columns([1, 2, 1])
with col1:
    if st.button("← Prev", use_container_width=True) and offset >= limit:
        st.session_state.customers_offset -= limit
        st.rerun()
with col2:
    st.markdown(
        f"<p style='text-align: center; color: gray; margin-top: 6px;'>"
        f"Showing {offset + 1}–{min(offset + limit, total)} of {total}"
        f"</p>",
        unsafe_allow_html=True,
    )
with col3:
    if st.button("Next →", use_container_width=True) and offset + limit < total:
        st.session_state.customers_offset += limit
        st.rerun()
