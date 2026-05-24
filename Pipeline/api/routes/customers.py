from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from Pipeline.config import DATA_PATH
from Pipeline.data.loader import load_customers
from Pipeline.engine.analyzer import analyze

router = APIRouter()


def _load_at_risk(ml_enabled: bool = False):
    customers, date_cutoff = load_customers(DATA_PATH)
    at_risk, _, _ = analyze(customers, date_cutoff, ml_enabled=ml_enabled)
    return at_risk


@router.get("/at-risk")
def get_at_risk_customers(
    risk_level: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    sort_by: str = Query("combined_score"),
    order: str = Query("desc"),
    search: Optional[str] = Query(None),
):
    at_risk = _load_at_risk()

    if risk_level:
        at_risk = [c for c in at_risk if c.risk_level == risk_level.upper()]

    if search:
        at_risk = [
            c
            for c in at_risk
            if search.lower() in c.name.lower()
            or search.lower() in c.customer_id.lower()
        ]

    reverse = order == "desc"
    if sort_by == "combined_score":
        at_risk.sort(key=lambda c: c.rfm.combined_score, reverse=reverse)
    elif sort_by == "days_inactive":
        at_risk.srt(key=lambda c: c.days_since_last_purchase, reverse=reverse)

    paginated = at_risk[offset : offset + limit]

    return {
        "total": len(at_risk),
        "limit": limit,
        "offset": offset,
        "results": paginated,
    }
