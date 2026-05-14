from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from Pipeline.data.schema import Customer
from Pipeline.engine.rfm import RFMScore, compute_rfm
from Pipeline.engine.rules import evaluate_rules, triggered_rule_ids
from Pipeline.config import (
    RFM_AT_RISK_THRESHOLD,
    MAX_BLAST_SIZE,
    HIGH_VALUE_SPEND_THRESHOLD,
    THRESHOLD_DRIFT_TOLERANCE,
)


RISK_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


@dataclass
class SpendSummary:
    total_spend: float
    avg_order_value: float
    top_category: Optional[str]


@dataclass
class AtRiskCustomer:
    customer_id: str
    name: str
    phone: str
    gender: Optional[str]
    age: Optional[int]
    rfm: RFMScore
    risk_level: str                     # "HIGH" | "MEDIUM" | "LOW"
    triggered_rules: List[str]          # e.g. ["R01", "R03"]
    days_since_last_purchase: int
    spend_summary: SpendSummary
    churn_probability: Optional[float] = field(default=None)  # set by ML if ml_enabled


def _assign_risk_level(rfm: RFMScore, fired_rules: List[str]) -> str:
    if rfm.r_score == 1 or "R01" in fired_rules or "R03" in fired_rules:
        return "HIGH"
    if rfm.r_score == 2 or "R02" in fired_rules or "R04" in fired_rules:
        return "MEDIUM"
    return "LOW"


def _compute_dynamic_threshold(customers: List[Customer]) -> float:
    """Compute the 80th percentile total spend across the population."""
    spends = sorted(c.total_spend for c in customers)
    if not spends:
        return 0.0
    idx = 0.8 * (len(spends) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(spends) - 1)
    return spends[lo] + (idx - lo) * (spends[hi] - spends[lo])


def analyze(customers: List[Customer], date_cutoff: datetime, ml_enabled: bool = False) -> List[AtRiskCustomer]:
    # --- Step 1: compute dynamic threshold and check drift vs fixed config ---
    dynamic_threshold = _compute_dynamic_threshold(customers)
    drift = abs(dynamic_threshold - HIGH_VALUE_SPEND_THRESHOLD) / (HIGH_VALUE_SPEND_THRESHOLD or 1)
    use_threshold = dynamic_threshold if drift > THRESHOLD_DRIFT_TOLERANCE else HIGH_VALUE_SPEND_THRESHOLD

    # --- Step 2: run rules first on all customers (fast path) ---
    rule_results: dict[str, List[str]] = {}
    for customer in customers:
        results = evaluate_rules(customer, date_cutoff, use_threshold)
        rule_results[customer.customer_id] = triggered_rule_ids(results)

    rule_flagged_ids = {cid for cid, fired in rule_results.items() if fired}

    # --- Step 3: compute RFM scores for all customers ---
    rfm_scores = compute_rfm(customers, date_cutoff)
    rfm_map: dict[str, RFMScore] = {r.customer_id: r for r in rfm_scores}

    # --- Step 4: ML scoring for non-rule-flagged customers (if enabled) ---
    ml_scores: dict[str, float] = {}
    if ml_enabled:
        from Pipeline.engine.ml import ChurnPredictor
        predictor = ChurnPredictor()
        for customer in customers:
            if customer.customer_id not in rule_flagged_ids:
                ml_scores[customer.customer_id] = predictor.score(customer, rfm_map.get(customer.customer_id), date_cutoff)

    # --- Step 5: determine at-risk customers and assign risk levels ---
    at_risk: list[AtRiskCustomer] = []

    for customer in customers:
        rfm = rfm_map.get(customer.customer_id)
        if rfm is None:
            continue

        fired = rule_results.get(customer.customer_id, [])
        churn_prob = ml_scores.get(customer.customer_id)

        from Pipeline.config import ML_CHURN_THRESHOLD
        is_at_risk = (
            bool(fired)
            or rfm.combined_score < RFM_AT_RISK_THRESHOLD
            or rfm.r_score <= 2
            or (churn_prob is not None and churn_prob >= ML_CHURN_THRESHOLD)
        )

        if not is_at_risk:
            continue

        risk_level = _assign_risk_level(rfm, fired)

        at_risk.append(AtRiskCustomer(
            customer_id=customer.customer_id,
            name=customer.customer_name,
            phone=customer.phone_number,
            gender=customer.gender,
            age=customer.age,
            rfm=rfm,
            risk_level=risk_level,
            triggered_rules=fired,
            days_since_last_purchase=rfm.recency_days,
            spend_summary=SpendSummary(
                total_spend=customer.total_spend,
                avg_order_value=customer.avg_order_value,
                top_category=customer.top_category,
            ),
            churn_probability=churn_prob,
        ))

    # --- Step 6: sort by risk level, then by days since last purchase (most inactive first) ---
    at_risk.sort(key=lambda c: (RISK_ORDER[c.risk_level], -c.days_since_last_purchase))

    # --- Step 7: apply blast cap ---
    if len(at_risk) > MAX_BLAST_SIZE:
        at_risk = sorted(at_risk, key=lambda c: -c.rfm.combined_score)[:MAX_BLAST_SIZE]
        at_risk.sort(key=lambda c: (RISK_ORDER[c.risk_level], -c.days_since_last_purchase))

    return at_risk
