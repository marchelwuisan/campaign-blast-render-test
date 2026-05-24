from fastapi import APIRouter, HTTPException
from collections import Counter
from Pipeline.database.db import transaction
from Pipeline.config import DATA_PATH
from Pipeline.data.loader import load_customers
from Pipeline.engine.analyzer import analyze

router = APIRouter()


@router.get("/engine")
def engine_analytics():
    customers, date_cutoff = load_customers(DATA_PATH)
    at_risk, ml_stats, _ = analyze(customers, date_cutoff, ml_enabled=False)

    risk_distribution = Counter(c.risk_level for c in at_risk)
    rule_counts = Counter(rule for c in at_risk for rule in c.triggered_rules)

    return {
        "total_at_risk": len(at_risk),
        "risk_distribution": dict(risk_distribution),
        "rule_counts": dict(rule_counts),
        "ml_stats": ml_stats,
    }


@router.get("/blast/{blast_id}")
def blast_analytics(blast_id: str):
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM blast_log WHERE blast_id = ?", (blast_id,)
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="blast_id not found")

    rows = [dict(r) for r in rows]

    total = len(rows)
    sent = sum(1 for r in rows if r["status"] in ("sent", "mocked"))
    failed = sum(1 for r in rows if r["status"] == "failed")

    promo_breakdown = Counter(r["promo_code"] for r in rows if r["promo_code"])

    return {
        "blast_id": blast_id,
        "total": total,
        "total_sent": sent,
        "total_failed": failed,
        "promo_breakdown": dict(promo_breakdown),
        "failures": [
            {"customer_id": r["customer_id"], "reason": r["error_reason"]}
            for r in rows
            if r["status"] == "failed"
        ],
    }
