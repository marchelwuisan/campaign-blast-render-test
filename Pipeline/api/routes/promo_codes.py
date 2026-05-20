from fastapi import APIRouter, HTTPException
from datetime import datetime
from Pipeline.database.db import transaction

router = APIRouter()


@router.get("/validate/{code}")
def validate_promo_code(code: str):
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM promo_codes WHERE code = ?", (code,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="not_found")

        row = dict(row)

        if row["status"] == "pending":
            raise HTTPException(status_code=400, detail="pending")
        if row["status"] == "cancelled":
            raise HTTPException(status_code=400, detail="cancelled")
        if row["is_redeemed"]:
            raise HTTPException(status_code=400, detail="already_redeemed")
        if datetime.fromisoformat(row["expires_at"]) < datetime.now():
            raise HTTPException(status_code=400, detail="expired")

        return {
            "code": row["code"],
            "customer_id": row["customer_id"],
            "promo_type": row["promo_type"],
            "discount_percent": row["discount_percent"],
            "expires_at": row["expires_at"],
            "status": row["status"],
        }


@router.post("/redeem/{code}")
def redeem_promo_code(code: str):
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM promo_codes WHERE code = ?", (code,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="not_found")

        row = dict(row)

        if row["is_redeemed"]:
            raise HTTPException(status_code=400, detail="already_redeemed")
        if row["status"] != "active":
            raise HTTPException(status_code=400, detail=row["status"])
        if datetime.fromisoformat(row["expires_at"]) < datetime.now():
            raise HTTPException(status_code=400, detail="expired")

        conn.execute(
            """
            UPDATE promo_codes
            SET is_redeemed = 1, redeemed_at = ?, status = 'redeemed'
            WHERE code = ?
            """,
            (datetime.now().isoformat(), code),
        )

        return {
            "code": code,
            "status": "redeemed",
            "redeemed_at": datetime.now().isoformat(),
        }
