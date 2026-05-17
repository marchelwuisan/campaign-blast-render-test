"""
Temporary test script to validate Stage 1 (loader) + Stage 2 (analyzer) +
Stage 3 (promo assignment) + Stage 4 (message construction) + Stage 5 (mock sender).
Not part of the production pipeline.
"""

import json
from collections import Counter
from datetime import datetime

from Pipeline.data.loader import load_customers
from Pipeline.engine.analyzer import analyze
from Pipeline.promo.mapping import assign_promo
from Pipeline.messaging.constructor import construct_message
from Pipeline.messaging.mock_sender import MockSender

REPORT_PATH = "test_pipeline_report.json"
SAMPLE_SEND_COUNT = 3  # number of customers to run through Stage 4 + 5


def main():
    customers, date_cutoff = load_customers("Pipeline/transactions.csv")

    ml_enabled = True
    at_risk, ml_stats, population_rfm_stats = analyze(
        customers, date_cutoff, ml_enabled=ml_enabled
    )

    print("\n[Sanity Check] R01 sample (long inactivity):")
    r01_sample = [c for c in at_risk if "R01" in c.triggered_rules][:5]
    for c in r01_sample:
        print(
            f"    {c.customer_id} | days_inactive={c.days_since_last_purchase} | churn_prob={c.churn_probability}"
        )

    risk_counts = Counter(c.risk_level for c in at_risk)
    rule_counts = Counter(rule for c in at_risk for rule in c.triggered_rules)
    total_with_rules = sum(1 for c in at_risk if c.triggered_rules)
    scores = [c.rfm.combined_score for c in at_risk]
    inactive_days = [c.days_since_last_purchase for c in at_risk]
    inactive_buckets = {"0-30": 0, "31-90": 0, "91-180": 0, "181-365": 0, "365+": 0}
    for d in inactive_days:
        if d <= 30:
            inactive_buckets["0-30"] += 1
        elif d <= 90:
            inactive_buckets["31-90"] += 1
        elif d <= 180:
            inactive_buckets["91-180"] += 1
        elif d <= 365:
            inactive_buckets["181-365"] += 1
        else:
            inactive_buckets["365+"] += 1

    print(f"\n{'='*50}")
    print(f"[Stage 1] Loaded {len(customers)} customers")
    print(
        f"[Stage 2] At-risk: {len(at_risk)} / {len(customers)} ({round(len(at_risk)/len(customers)*100, 1)}%)"
    )
    print(
        f"  Risk levels  — HIGH: {risk_counts.get('HIGH', 0)}  MEDIUM: {risk_counts.get('MEDIUM', 0)}  LOW: {risk_counts.get('LOW', 0)}"
    )
    print(
        f"  Rules fired  — R01: {rule_counts.get('R01', 0)}  R02: {rule_counts.get('R02', 0)}  R03: {rule_counts.get('R03', 0)}  R04: {rule_counts.get('R04', 0)}"
    )
    print(
        f"  With rules: {total_with_rules}  RFM-only: {len(at_risk) - total_with_rules}"
    )
    print(
        f"  RFM scores   — min: {min(scores)}  max: {max(scores)}  avg: {round(sum(scores)/len(scores), 1)}"
    )
    print(f"{'='*50}")

    # --- Stage 3: assign promos ---
    promos = {c.customer_id: assign_promo(c) for c in at_risk}
    promo_counts = Counter(p.promo_type for p in promos.values())
    print(
        f"[Stage 3] Promos assigned — discount_30: {promo_counts.get('discount_30', 0)}  discount_20: {promo_counts.get('discount_20', 0)}  ship_discount_15: {promo_counts.get('ship_discount_15', 0)}  bogo: {promo_counts.get('bogo', 0)}  points_2x: {promo_counts.get('points_2x', 0)}"
    )

    # --- Stage 4 + 5: construct and mock-send first N customers ---
    sender = MockSender()
    print(f"\n[Stage 4+5] Sending sample of {SAMPLE_SEND_COUNT} messages...\n")
    for customer in at_risk[:SAMPLE_SEND_COUNT]:
        promo = promos[customer.customer_id]
        message = construct_message(customer, promo)
        sender.send(message, customer.customer_id)

    # --- promo distribution ---
    promo_counts = Counter(p.promo_type for p in promos.values())

    from Pipeline.config import (
        RFM_WINDOW_DAYS,
        RFM_AT_RISK_THRESHOLD,
        INACTIVITY_THRESHOLD_DAYS,
        HIGH_VALUE_SPEND_THRESHOLD,
        MAX_BLAST_SIZE,
        ML_MODEL_PATH,
        ML_CHURN_THRESHOLD,
        PROMO_EXPIRY_DAYS,
        SENDER_MODE,
    )

    report = {
        "generated_at": datetime.now().isoformat(),
        "date_cutoff": date_cutoff.date().isoformat(),
        "config": {
            "ml_enabled": ml_enabled,
            "ml_model_path": ML_MODEL_PATH,
            "ml_churn_threshold": ML_CHURN_THRESHOLD,
            "rfm_window_days": RFM_WINDOW_DAYS,
            "rfm_at_risk_threshold": RFM_AT_RISK_THRESHOLD,
            "inactivity_threshold_days": INACTIVITY_THRESHOLD_DAYS,
            "high_value_spend_threshold": HIGH_VALUE_SPEND_THRESHOLD,
            "max_blast_size": MAX_BLAST_SIZE,
            "promo_expiry_days": PROMO_EXPIRY_DAYS,
            "sender_mode": SENDER_MODE,
        },
        "stage_1": {
            "total_customers_loaded": len(customers),
        },
        "stage_2": {
            "at_risk_count": len(at_risk),
            "at_risk_percent": round(len(at_risk) / len(customers) * 100, 1),
            "risk_level_distribution": {
                "HIGH": risk_counts.get("HIGH", 0),
                "MEDIUM": risk_counts.get("MEDIUM", 0),
                "LOW": risk_counts.get("LOW", 0),
            },
            "rule_firing_counts": {
                "R01_long_inactivity": rule_counts.get("R01", 0),
                "R02_frequency_drop": rule_counts.get("R02", 0),
                "R03_high_value_lapse": rule_counts.get("R03", 0),
                "R04_single_purchase": rule_counts.get("R04", 0),
                "customers_with_any_rule": total_with_rules,
                "customers_rfm_only": len(at_risk) - total_with_rules,
            },
            "rfm_score_distribution": {
                "min": min(scores),
                "max": max(scores),
                "avg": round(sum(scores) / len(scores), 1),
            },
            "days_inactive_distribution": {
                "min": min(inactive_days),
                "max": max(inactive_days),
                "avg": round(sum(inactive_days) / len(inactive_days), 1),
                "buckets": inactive_buckets,
            },
            "ml": ml_stats,
            "population_rfm_stats": population_rfm_stats,
        },
        "stage_3": {
            "promos_assigned": len(promos),
            "promo_distribution": {
                "discount_30": promo_counts.get("discount_30", 0),
                "discount_20": promo_counts.get("discount_20", 0),
                "ship_discount_15": promo_counts.get("ship_discount_15", 0),
                "bogo": promo_counts.get("bogo", 0),
                "points_2x": promo_counts.get("points_2x", 0),
            },
        },
        "stage_4_5": {
            "sample_sent": SAMPLE_SEND_COUNT,
            "sender_mode": SENDER_MODE,
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
                "promo": {
                    "promo_type": promos[c.customer_id].promo_type,
                    "promo_value": promos[c.customer_id].promo_value,
                    "promo_code": promos[c.customer_id].promo_code,
                    "expiry_days": promos[c.customer_id].expiry_days,
                },
            }
            for c in at_risk[:10]
        ],
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n[test_pipeline] report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
