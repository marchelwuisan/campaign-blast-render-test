from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List

from Pipeline.data.schema import Customer
from Pipeline.config import RFM_WINDOW_DAYS


@dataclass
class RFMScore:
    customer_id: str
    recency_days: int       # days since last purchase (raw value)
    frequency: int          # number of purchases within RFM_WINDOW_DAYS
    monetary: float         # total spend within RFM_WINDOW_DAYS
    r_score: int            # 1–5
    f_score: int            # 1–5
    m_score: int            # 1–5
    combined_score: int     # r + f + m (range 3–15)


def _percentile_score(value: float, breakpoints: list[float], reverse: bool = False) -> int:
    """
    Assigns a 1–5 score based on where value falls among the 4 quintile breakpoints.
    reverse=True means lower value = higher score (used for recency).
    """
    for i, bp in enumerate(breakpoints):
        if value <= bp:
            score = i + 1
            return (6 - score) if reverse else score
    score = 5
    return (6 - score) if reverse else score


def _quintile_breakpoints(values: list[float]) -> list[float]:
    """Returns the 4 breakpoints (20th, 40th, 60th, 80th percentile) for quintile scoring."""
    if not values:
        return [0.0, 0.0, 0.0, 0.0]
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    breakpoints = []
    for pct in [0.2, 0.4, 0.6, 0.8]:
        idx = pct * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        bp = sorted_vals[lo] + (idx - lo) * (sorted_vals[hi] - sorted_vals[lo])
        breakpoints.append(bp)
    return breakpoints


def compute_rfm(customers: List[Customer], date_cutoff: datetime) -> List[RFMScore]:
    window_start = date_cutoff.replace(tzinfo=timezone.utc) - timedelta(days=RFM_WINDOW_DAYS)
    date_cutoff = date_cutoff.replace(tzinfo=timezone.utc)

    # --- compute raw RFM values per customer ---
    raw: list[dict] = []
    for customer in customers:
        windowed_txns = [t for t in customer.transactions if t.purchase_date >= window_start]

        if customer.last_purchase_date is None:
            continue

        recency_days = (date_cutoff - customer.last_purchase_date).days
        frequency = len(windowed_txns)
        monetary = sum(t.order_value for t in windowed_txns)

        raw.append({
            "customer": customer,
            "recency_days": recency_days,
            "frequency": frequency,
            "monetary": monetary,
        })

    if not raw:
        return []

    # --- compute quintile breakpoints across the population ---
    r_breakpoints = _quintile_breakpoints([r["recency_days"] for r in raw])
    f_breakpoints = _quintile_breakpoints([r["frequency"] for r in raw])
    m_breakpoints = _quintile_breakpoints([r["monetary"] for r in raw])

    # --- assign scores ---
    scores: list[RFMScore] = []
    for r in raw:
        r_score = _percentile_score(r["recency_days"], r_breakpoints, reverse=True)  # lower recency = better
        f_score = _percentile_score(r["frequency"], f_breakpoints, reverse=False)
        m_score = _percentile_score(r["monetary"], m_breakpoints, reverse=False)

        scores.append(RFMScore(
            customer_id=r["customer"].customer_id,
            recency_days=r["recency_days"],
            frequency=r["frequency"],
            monetary=r["monetary"],
            r_score=r_score,
            f_score=f_score,
            m_score=m_score,
            combined_score=r_score + f_score + m_score,
        ))

    return scores
