from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

from Pipeline.data.schema import Customer
from Pipeline.config import (
    INACTIVITY_THRESHOLD_DAYS,
    RFM_WINDOW_DAYS,
    FREQUENCY_DROP_THRESHOLD,
    HIGH_VALUE_LAPSE_DAYS,
)


@dataclass
class RuleResult:
    rule_id: str  # e.g. "R01"
    rule_name: str  # e.g. "Long Inactivity"
    triggered: bool
    detail: str  # human-readable reason, e.g. "inactive for 45 days"


def check_r01_long_inactivity(customer: Customer, date_cutoff: datetime) -> RuleResult:
    """R01 — No purchase in last INACTIVITY_THRESHOLD_DAYS days."""
    date_cutoff = date_cutoff.replace(tzinfo=timezone.utc)

    if customer.last_purchase_date is None:
        return RuleResult("R01", "Long Inactivity", True, "no purchases recorded")

    # Single-purchase customers
    if customer.purchase_count == 1:
        return RuleResult(
            "R01", "Long Inactivity", False, "single-purchase customer - handled by R04"
        )

    days_inactive = (date_cutoff - customer.last_purchase_date).days
    triggered = days_inactive > INACTIVITY_THRESHOLD_DAYS
    return RuleResult(
        rule_id="R01",
        rule_name="Long Inactivity",
        triggered=triggered,
        detail=f"inactive for {days_inactive} days",
    )


def check_r02_frequency_drop(customer: Customer, date_cutoff: datetime) -> RuleResult:
    """R02 — Purchase count in current half-window < 50% of prior half-window."""
    date_cutoff = date_cutoff.replace(tzinfo=timezone.utc)
    half = RFM_WINDOW_DAYS // 2

    from datetime import timedelta

    if customer.last_purchase_date:
        days_inactive = date_cutoff - customer.last_purchase_date
        if days_inactive <= timedelta(days=30):
            return RuleResult(
                "R02",
                "Frequency Drop",
                False,
                f"recently active ({days_inactive} days ago)",
            )

    current_start = date_cutoff - timedelta(days=half)
    prior_start = date_cutoff - timedelta(days=RFM_WINDOW_DAYS)

    current_count = sum(
        1
        for t in customer.transactions
        if current_start <= t.purchase_date <= date_cutoff
    )
    prior_count = sum(
        1
        for t in customer.transactions
        if prior_start <= t.purchase_date < current_start
    )

    if prior_count == 0:
        return RuleResult(
            "R02", "Frequency Drop", False, "no prior period purchases to compare"
        )

    if prior_count < 3:
        return RuleResult(
            "R02",
            "Frequency Drop",
            False,
            "prior period too sparse ({prior_count} purchases)",
        )

    triggered = current_count < (prior_count * FREQUENCY_DROP_THRESHOLD)
    return RuleResult(
        rule_id="R02",
        rule_name="Frequency Drop",
        triggered=triggered,
        detail=f"current period: {current_count} purchases, prior period: {prior_count} purchases",
    )


def check_r03_high_value_lapse(
    customer: Customer, date_cutoff: datetime, top_20_threshold: float
) -> RuleResult:
    """R03 — Customer was top 20% spender historically, now inactive > 14 days."""
    date_cutoff = date_cutoff.replace(tzinfo=timezone.utc)

    is_high_value = customer.total_spend >= top_20_threshold

    if not is_high_value:
        return RuleResult("R03", "High-Value Lapse", False, "not a high-value customer")

    days_inactive = (date_cutoff - customer.last_purchase_date).days
    triggered = days_inactive > HIGH_VALUE_LAPSE_DAYS
    return RuleResult(
        rule_id="R03",
        rule_name="High-Value Lapse",
        triggered=triggered,
        detail=f"high-value customer inactive for {days_inactive} days",
    )


def check_r04_single_purchase(customer: Customer) -> RuleResult:
    """R04 — Only 1 purchase ever recorded, no subsequent return."""
    triggered = customer.purchase_count == 1
    return RuleResult(
        rule_id="R04",
        rule_name="Single Purchase",
        triggered=triggered,
        detail=f"total purchases: {customer.purchase_count}",
    )


def evaluate_rules(
    customer: Customer, date_cutoff: datetime, top_20_threshold: float
) -> List[RuleResult]:
    """Run all rules against a customer and return the full list of results."""
    return [
        check_r01_long_inactivity(customer, date_cutoff),
        check_r02_frequency_drop(customer, date_cutoff),
        check_r03_high_value_lapse(customer, date_cutoff, top_20_threshold),
        check_r04_single_purchase(customer),
    ]


def triggered_rule_ids(results: List[RuleResult]) -> List[str]:
    """Returns list of rule IDs that fired, e.g. ['R01', 'R03']."""
    return [r.rule_id for r in results if r.triggered]
