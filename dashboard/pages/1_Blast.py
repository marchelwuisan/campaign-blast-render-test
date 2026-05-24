import streamlit as st
from dashboard.api import post

st.set_page_config(page_title="Blast", page_icon="📤", layout="wide")
st.title("Send Blast")

ml_enabled = st.checkbox("Enable ML churn prediction", value=False)

st.divider()

col1, col2 = st.columns(2)

with col1:
    if st.button("Preview", use_container_width=True):
        with st.spinner("Running preview..."):
            try:
                data = post("/blast/preview", {"ml_enabled": ml_enabled})
                st.success(f"Would send to **{data['total']}** customers")
                if data.get("validation_errors"):
                    st.warning(f"{len(data['validation_errors'])} validation errors")
                    st.json(data["validation_errors"])
                if data.get("messages"):
                    st.dataframe(data["messages"], use_container_width=True)
            except Exception as e:
                st.error(str(e))

with col2:
    if st.button("Send Blast", type="primary", use_container_width=True):
        with st.spinner("Sending..."):
            try:
                data = post("/blast/send", {"ml_enabled": ml_enabled})
                st.success("Blast complete!")
                m1, m2, m3 = st.columns(3)
                m1.metric("Total", data["total"])
                m2.metric("Sent", data["total_sent"])
                m3.metric("Failed", data["total_failed"])
                st.caption(f"Blast ID: `{data['blast_id']}`")
                st.caption(f"Sender mode: `{data['sender_mode']}`")
            except Exception as e:
                st.error(str(e))
