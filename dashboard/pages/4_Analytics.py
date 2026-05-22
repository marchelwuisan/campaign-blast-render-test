import streamlit as st
import plotly.express as px
from dashboard.api import get

st.set_page_config(page_title="Analytics", page_icon="📊", layout="wide")
st.title("Analytics")

# Engine analytics
st.subheader("Engine Overview")
if "engine_stats" not in st.session_state:
    with st.spinner("Running engine..."):
        try:
            st.session_state.engine_stats = get("/analytics/engine")
        except Exception as e:
            st.error(str(e))
            st.stop()

if st.button("Refresh Engine Stats"):
    del st.session_state["engine_stats"]
    st.rerun()

eng = st.session_state.engine_stats
st.metric("Total At-Risk Customers", eng["total_at_risk"])

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Risk Distribution**")
    risk = eng.get("risk_distribution", {})
    if risk:
        fig = px.pie(names=list(risk.keys()), values=list(risk.values()), hole=0.4)
        fig.update_layout(margin=dict(t=0, b=0, l=0, r=0))
        st.plotly_chart(fig, use_container_width=True)

with col2:
    st.markdown("**Rule Trigger Counts**")
    rules = eng.get("rule_counts", {})
    if rules:
        fig = px.bar(
            x=list(rules.keys()),
            y=list(rules.values()),
            labels={"x": "Rule", "y": "Customers"},
            color=list(rules.keys()),
        )
        fig.update_layout(showlegend=False, margin=dict(t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)

st.divider()
st.subheader("Blast Analytics")

# Pick a blast from recent logs or type manually
try:
    logs = get(
        "/blast/logs", params={"limit": 20, "sort_by": "sent_at", "order": "desc"}
    )
    recent = list({r["blast_id"] for r in logs["results"]})
except Exception:
    recent = []

if recent:
    blast_id = st.selectbox("Select a recent blast", recent)
else:
    blast_id = st.text_input("Blast ID")

if not blast_id:
    st.info("Select or enter a blast ID to view analytics.")
    st.stop()

try:
    data = get(f"/analytics/blast/{blast_id}")
except Exception as e:
    st.error(str(e))
    st.stop()

# Summary metrics
st.divider()
m1, m2, m3 = st.columns(3)
m1.metric("Total", data["total"])
m2.metric("Sent", data["total_sent"])
m3.metric("Failed", data["total_failed"])

# Promo breakdown chart
st.divider()
st.subheader("Promo Breakdown")
breakdown = data.get("promo_breakdown", {})
if breakdown:
    fig = px.bar(
        x=list(breakdown.keys()),
        y=list(breakdown.values()),
        labels={"x": "Promo Code", "y": "Count"},
        color=list(breakdown.keys()),
    )
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No promo data.")

# Failures
st.divider()
st.subheader("Failures")
failures = data.get("failures", [])
if failures:
    st.dataframe(failures, use_container_width=True)
else:
    st.success("No failures in this blast.")
