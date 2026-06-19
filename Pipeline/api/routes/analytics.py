from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from collections import Counter
from Pipeline.database.db import transaction
from Pipeline.config import DATA_PATH
from Pipeline.data.loader import load_customers
from Pipeline.engine.analyzer import analyze

router = APIRouter()

_WINDOW_DAYS = {"7d": 7, "30d": 30, "90d": 90}


def _window_cutoff(window: str) -> str | None:
    """ISO cutoff for a window key, or None for 'all'."""
    days = _WINDOW_DAYS.get(window)
    if days is None:
        return None
    return (datetime.now() - timedelta(days=days)).isoformat()


@router.get("/summary", summary="Headline KPIs, per-blast breakdown, daily volume, failures")
def analytics_summary(
    window: Annotated[str, Query(description="7d | 30d | 90d | all")] = "30d",
):
    cutoff = _window_cutoff(window)
    where = "WHERE sent_at >= ?" if cutoff else ""
    params = [cutoff] if cutoff else []

    with transaction() as conn:
        totals = conn.execute(
            f"""
            SELECT SUM(CASE WHEN status IN ('sent','mocked') THEN 1 ELSE 0 END) AS sent,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)           AS failed
            FROM blast_log {where}
            """,
            params,
        ).fetchone()
        blasts = conn.execute(
            f"""
            SELECT blast_id,
                   MIN(sent_at)        AS started,
                   MAX(mode)           AS mode,
                   MAX(template_name)  AS template,
                   COUNT(*)            AS total,
                   SUM(CASE WHEN status IN ('sent','mocked') THEN 1 ELSE 0 END) AS sent,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)           AS failed
            FROM blast_log {where}
            GROUP BY blast_id
            ORDER BY started DESC
            """,
            params,
        ).fetchall()
        by_day = conn.execute(
            f"""
            SELECT date(sent_at) AS date,
                   SUM(CASE WHEN status IN ('sent','mocked') THEN 1 ELSE 0 END) AS sent,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)           AS failed
            FROM blast_log {where}
            GROUP BY date(sent_at)
            ORDER BY date(sent_at)
            """,
            params,
        ).fetchall()
        fail_where = "WHERE status = 'failed'" + (" AND sent_at >= ?" if cutoff else "")
        failures = conn.execute(
            f"""
            SELECT COALESCE(error_reason, 'Unknown') AS reason, COUNT(*) AS count
            FROM blast_log {fail_where}
            GROUP BY reason ORDER BY count DESC LIMIT 10
            """,
            params,
        ).fetchall()

    total_sent = totals["sent"] or 0
    total_failed = totals["failed"] or 0
    grand = total_sent + total_failed

    return {
        "window": window,
        "totalSent": total_sent,
        "totalFailed": total_failed,
        "failureRate": round(total_failed / grand * 100, 1) if grand else 0,
        "blasts": [
            {
                "id": b["blast_id"],
                "started": b["started"],
                "mode": b["mode"] or "meta",
                "template": b["template"],
                "total": b["total"],
                "sent": b["sent"],
                "failed": b["failed"],
            }
            for b in blasts
        ],
        "sendsByDay": [
            {"date": d["date"], "sent": d["sent"], "failed": d["failed"]} for d in by_day
        ],
        "topFailureReasons": [
            {"reason": f["reason"], "count": f["count"]} for f in failures
        ],
    }


@router.get("/promo-performance", summary="Messages sent (and redeemed) per promo code")
def promo_performance():
    with transaction() as conn:
        sent = conn.execute(
            """
            SELECT promo_code AS code,
                   SUM(CASE WHEN status IN ('sent','mocked') THEN 1 ELSE 0 END) AS sent
            FROM blast_log
            WHERE promo_code IS NOT NULL
            GROUP BY promo_code
            ORDER BY sent DESC
            """
        ).fetchall()
        redeemed = dict(
            conn.execute(
                "SELECT promo_type, COUNT(*) FROM promo_codes WHERE status = 'redeemed' GROUP BY promo_type"
            ).fetchall()
        )

    return [
        {"promoCode": r["code"], "sent": r["sent"], "redeemed": redeemed.get(r["code"], 0)}
        for r in sent
    ]


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
