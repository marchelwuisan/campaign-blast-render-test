from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from Pipeline.database.db import transaction

router = APIRouter()


def _digits(phone: str) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def _phone_matches(stored: str, entered: str) -> bool:
    a, b = _digits(stored), _digits(entered)
    if not a or not b:
        return False
    return a[-9:] == b[-9:]


def _row_to_dict(row) -> dict:
    return {
        "code": row["code"],
        "customerId": row["customer_id"],
        "name": row["name"],
        "phone": row["phone"],
        "promoCode": row["promo_type"],
        "promoValue": row["promo_value"],
        "status": row["status"],
        "issuedAt": row["issued_at"],
        "expiresAt": row["expires_at"],
        "redeemedAt": row["redeemed_at"],
    }


def _is_expired(row) -> bool:
    if not row["expires_at"]:
        return False
    try:
        return datetime.fromisoformat(row["expires_at"]) < datetime.now()
    except ValueError:
        return False


@router.get("", summary="List issued promo codes")
def list_promo_codes(
    status: Annotated[Optional[str], Query(description="active | pending | redeemed | cancelled")] = None,
    search: Annotated[Optional[str], Query(description="Match phone or customer name")] = None,
):
    filters, params = [], []
    if status:
        filters.append("status = ?")
        params.append(status)
    if search:
        filters.append("(phone LIKE ? OR name LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    with transaction() as conn:
        rows = conn.execute(
            f"SELECT * FROM promo_codes {where} ORDER BY issued_at DESC", params
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _find_issuance(phone: str, promo_code: str):
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM promo_codes WHERE promo_type = ? ORDER BY issued_at DESC",
            (promo_code,),
        ).fetchall()
    for r in rows:
        if _phone_matches(r["phone"], phone):
            return r
    return None


@router.get("/validate", summary="Validate a code without consuming it (cashier check)")
def validate_promo_code(
    phone: Annotated[str, Query(description="Customer phone number")],
    promo_code: Annotated[str, Query(description="Generic promo code, e.g. DISC20")],
):
    row = _find_issuance(phone, promo_code.strip().upper())
    if not row:
        return {"ok": False, "reason": "not_found", "detail": "No matching promo for this phone and code."}

    code = _row_to_dict(row)
    status = row["status"]
    if status == "cancelled":
        return {"ok": False, "reason": "cancelled", "detail": "Code was cancelled (send failed).", "code": code}
    if status == "pending":
        return {"ok": False, "reason": "pending", "detail": "Code not yet activated by dispatch.", "code": code}
    if status == "redeemed":
        return {"ok": False, "reason": "already_redeemed", "detail": f"Already redeemed on {row['redeemed_at']}.", "code": code}
    if _is_expired(row):
        return {"ok": False, "reason": "expired", "detail": f"Expired on {row['expires_at']}.", "code": code}
    return {"ok": True, "code": code}


@router.post("/extend", summary="Extend a code's expiry by N days")
def extend_promo_code(payload: Annotated[dict, Body()]):
    code = str(payload.get("code", "")).strip()
    try:
        days = int(payload.get("days"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="`days` must be an integer")
    if days <= 0:
        raise HTTPException(status_code=400, detail="`days` must be positive")

    with transaction() as conn:
        row = conn.execute("SELECT * FROM promo_codes WHERE code = ?", (code,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"No promo code {code}")
        try:
            base = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else datetime.now()
        except ValueError:
            base = datetime.now()
        new_expires = (base + timedelta(days=days)).isoformat()
        conn.execute(
            "UPDATE promo_codes SET expires_at = ? WHERE code = ?", (new_expires, code)
        )
        updated = conn.execute("SELECT * FROM promo_codes WHERE code = ?", (code,)).fetchone()
    return _row_to_dict(updated)


@router.post("/redeem", summary="Redeem (consume) a code at point of sale")
def redeem_promo_code(payload: Annotated[dict, Body()]):
    phone = str(payload.get("phone", ""))
    promo_code = str(payload.get("promo_code", "")).strip().upper()

    row = _find_issuance(phone, promo_code)
    if not row:
        return {"ok": False, "reason": "not_found", "detail": "No matching promo for this phone and code."}
    if row["status"] != "active" or _is_expired(row):
        # Re-run validation logic so the caller gets a precise reason.
        return validate_promo_code(phone=phone, promo_code=promo_code)

    redeemed_at = datetime.now(timezone.utc).isoformat()
    with transaction() as conn:
        conn.execute(
            "UPDATE promo_codes SET status = 'redeemed', redeemed_at = ? WHERE code = ?",
            (redeemed_at, row["code"]),
        )
        updated = conn.execute(
            "SELECT * FROM promo_codes WHERE code = ?", (row["code"],)
        ).fetchone()
    return _row_to_dict(updated)
