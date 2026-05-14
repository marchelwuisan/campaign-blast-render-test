"""
Temporary test script to validate Stage 1 (loader) + Stage 2 (analyzer).
Not part of the production pipeline.
"""

import json
from collections import Counter
from datetime import datetime

from Pipeline.data.loader import load_customers
from Pipeline.engine.analyzer import analyze

REPORT_PATH = "test_pipeline_report.json"


def main():
    customers, date_cutoff = load_customers("Pipeline/transactions.csv")

    at_risk = analyze(customers, date_cutoff, ml_enabled=True)

    # --- risk level distribution ---
    risk_counts = Counter(c.risk_level for c in at_risk)

    # --- combined score distribution ---
    scores = [c.rfm.combined_score for c in at_risk]

    # --- rule firing counts ---
    rule_counts = Counter(rule for c in at_risk for rule in c.triggered_rules)
    total_with_rules = sum(1 for c in at_risk if c.triggered_rules)

    report = {
        "generated_at": datetime.now().isoformat(),
        "date_cutoff": date_cutoff.date().isoformat(),
        "summary": {
            "total_customers": len(customers),
            "at_risk_count": len(at_risk),
            "at_risk_percent": round(len(at_risk) / len(customers) * 100, 1),
        },
        "risk_level_distribution": {
            "HIGH": risk_counts.get("HIGH", 0),
            "MEDIUM": risk_counts.get("MEDIUM", 0),
            "LOW": risk_counts.get("LOW", 0),
        },
        "combined_score_distribution": {
            "min": min(scores),
            "max": max(scores),
            "avg": round(sum(scores) / len(scores), 1),
        },
        "rule_firing_counts": {
            "R01_long_inactivity": rule_counts.get("R01", 0),
            "R02_frequency_drop": rule_counts.get("R02", 0),
            "R03_high_value_lapse": rule_counts.get("R03", 0),
            "R04_single_purchase": rule_counts.get("R04", 0),
            "customers_with_any_rule": total_with_rules,
            "customers_rfm_only": len(at_risk) - total_with_rules,
        },
        "sample_at_risk": [
            {
                "customer_id": c.customer_id,
                "name": c.name,
                "phone": c.phone,
                "risk_level": c.risk_level,
                "days_inactive": c.days_since_last_purchase,
                "rfm": {
                    "r_score": c.rfm.r_score,
                    "f_score": c.rfm.f_score,
                    "m_score": c.rfm.m_score,
                    "combined_score": c.rfm.combined_score,
                },
                "triggered_rules": c.triggered_rules,
                "spend_summary": {
                    "total_spend": round(c.spend_summary.total_spend, 2),
                    "avg_order_value": round(c.spend_summary.avg_order_value, 2),
                    "top_category": c.spend_summary.top_category,
                },
            }
            for c in at_risk[:10]
        ],
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"[test_pipeline] report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
