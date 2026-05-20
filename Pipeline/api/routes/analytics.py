from fastapi import APIRouter, HTTPException
from datetime import datetime
from Pipeline.database.db import transaction

router = APIRouter()


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

    promo_codes = [r["promo_code"] for r in rows if r["promo_code"]]

    redeemed = 0
    time_to_redeem_seconds = []

    if promo_codes:
        with transaction() as conn:
            placeholders = ",".join(["?"] * len(promo_codes))
            code_rows = conn.execute(
                f"SELECT * FROM promo_codes WHERE code IN ({placeholders})",
                promo_codes,
            ).fetchall()
            code_rows = [dict(r) for r in code_rows]

        redeemed = sum(1 for r in code_rows if r["is_redeemed"])

        for r in code_rows:
            if r["is_redeemed"] and r["redeemed_at"] and r["issued_at"]:
                delta = (
                    datetime.fromisoformat(r["redeemed_at"])
                    - datetime.fromisoformat(r["issued_at"])
                ).total_seconds()
                time_to_redeem_seconds.append(delta)

        avg_time_to_redeem = (
            round(sum(time_to_redeem_seconds) / len(time_to_redeem_seconds))
            if time_to_redeem_seconds
            else None
        )

        return {
            "blast_id": blast_id,
            "total_sent": sent,
            "total_failed": failed,
            "total": total,
            "redemption_rate": round(redeemed / sent * 100, 1) if sent else 0,
            "redeemed_count": redeemed,
            "avg_time_to_redeem_seconds": avg_time_to_redeem,
            "failures": [
                {"customer_id": r["customer_id"], "reason": r["error_reason"]}
                for r in rows
                if r["status"] == "failed"
            ],
        }
