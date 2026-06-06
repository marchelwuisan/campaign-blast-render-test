from fastapi import APIRouter, Query, HTTPException
from typing import Optional
import json
import os

from Pipeline.config import DATA_PATH
from Pipeline.database.db import transaction

router = APIRouter()

_RFM_BAND_SQL = {
    "high": "rfm_combined_score >= 10",
    "medium": "rfm_combined_score BETWEEN 6 AND 9",
    "low": "rfm_combined_score <= 5",
}

_SORT_SQL = {
    "risk": "CASE risk_level WHEN 'HIGH' THEN 3 WHEN 'MEDIUM' THEN 2 ELSE 1 END DESC, days_since_last_purchase DESC",
    "score": "rfm_combined_score ASC",
    "recency": "days_since_last_purchase DESC",
    "spend": "total_spend DESC",
}


@router.get("/at-risk")
def get_at_risk_customers(
    risk_level: Optional[str] = Query(None),
    rfm_band: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    sort_by: str = Query("risk"),
    search: Optional[str] = Query(None),
):
    if not os.path.exists(DATA_PATH):
        raise HTTPException(
            status_code=404,
            detail="No transaction dataset found. Please upload a transactions.csv first.",
        )

    with transaction() as conn:
        total_analyzed = conn.execute(
            "SELECT COUNT(*) FROM analyzed_customers"
        ).fetchone()[0]

        if total_analyzed == 0:
            raise HTTPException(
                status_code=404,
                detail="Dataset has not been analyzed yet. Run POST /dataset/analyze first.",
            )

        conditions: list[str] = []
        params: list = []

        if risk_level:
            conditions.append("risk_level = ?")
            params.append(risk_level.upper())

        if rfm_band and rfm_band.lower() in _RFM_BAND_SQL:
            conditions.append(_RFM_BAND_SQL[rfm_band.lower()])

        if search:
            conditions.append("(LOWER(name) LIKE ? OR LOWER(customer_id) LIKE ?)")
            params.extend([f"%{search.lower()}%", f"%{search.lower()}%"])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order = _SORT_SQL.get(sort_by, _SORT_SQL["risk"])

        total = conn.execute(
            f"SELECT COUNT(*) FROM analyzed_customers {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM analyzed_customers {where} ORDER BY {order} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        breakdown_rows = conn.execute(
            "SELECT risk_level, COUNT(*) FROM analyzed_customers GROUP BY risk_level"
        ).fetchall()

    risk_breakdown = {"high": 0, "medium": 0, "low": 0}
    for row in breakdown_rows:
        risk_breakdown[row[0].lower()] = row[1]

    results = []
    for r in rows:
        d = dict(r)
        results.append({
            "customer_id": d["customer_id"],
            "name": d["name"],
            "phone": d["phone"],
            "gender": d["gender"],
            "age": d["age"],
            "risk_level": d["risk_level"],
            "triggered_rules": json.loads(d["triggered_rules"] or "[]"),
            "days_since_last_purchase": d["days_since_last_purchase"],
            "churn_probability": d["churn_probability"],
            "rfm": {
                "r_score": d["rfm_r_score"],
                "f_score": d["rfm_f_score"],
                "m_score": d["rfm_m_score"],
                "combined_score": d["rfm_combined_score"],
            },
            "spend_summary": {
                "total_spend": d["total_spend"],
                "avg_order_value": d["avg_order_value"],
                "top_category": d["top_category"],
            },
        })

    return {
        "total": total,
        "total_scored": total_analyzed,
        "risk_breakdown": risk_breakdown,
        "limit": limit,
        "offset": offset,
        "results": results,
    }
