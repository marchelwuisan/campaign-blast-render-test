from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from Pipeline.database.db import transaction

router = APIRouter()


def _latest_blast_id(conn) -> str | None:
    row = conn.execute(
        "SELECT blast_id FROM at_risk_customers ORDER BY scored_at DESC LIMIT 1"
    ).fetchone()
    return row["blast_id"] if row else None


@router.get("/at-risk")
def get_at_risk_customers(
    risk_level: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    sort_by: str = Query("combined_score"),
    order: str = Query("desc"),
    search: Optional[str] = Query(None),
):
    direction = "DESC" if order == "desc" else "ASC"
    allowed_sort = {"combined_score", "days_inactive", "risk_level", "name"}
    if sort_by not in allowed_sort:
        sort_by = "combined_score"

    filters = []
    params = []

    with transaction() as conn:
        blast_id = _latest_blast_id(conn)
        if not blast_id:
            return {"total": 0, "limit": limit, "offset": offset, "results": []}

        filters.append("blast_id = ?")
        params.append(blast_id)

        if risk_level:
            filters.append("risk_level = ?")
            params.append(risk_level.upper())

        if search:
            filters.append("(name LIKE ? OR customer_id LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        where = f"WHERE {' AND '.join(filters)}"

        total = conn.execute(
            f"SELECT COUNT(*) FROM at_risk_customers {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""
            SELECT * FROM at_risk_customers {where}
            ORDER BY {sort_by} {direction}
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": [
            {
                "customer_id": r["customer_id"],
                "name": r["name"],
                "phone": r["phone"],
                "risk_level": r["risk_level"],
                "days_inactive": r["days_inactive"],
                "rfm": {
                    "r_score": r["r_score"],
                    "f_score": r["f_score"],
                    "m_score": r["m_score"],
                    "combined_score": r["combined_score"],
                },
                "triggered_rules": (
                    r["triggered_rules"].split(",") if r["triggered_rules"] else []
                ),
            }
            for r in rows
        ],
    }


@router.get("/{customer_id}/promo")
def get_customer_promo(customer_id: str):
    with transaction() as conn:
        blast_id = _latest_blast_id(conn)
        if not blast_id:
            raise HTTPException(status_code=404, detail="No blast has been run yet")

        row = conn.execute(
            """
            SELECT * FROM promo_assignments
            WHERE blast_id = ? AND customer_id = ?
            """,
            (blast_id, customer_id),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Customer not found or not at risk")

    return {
        "customer_id": customer_id,
        "promo_type": row["promo_type"],
        "promo_value": row["promo_value"],
        "promo_code": row["promo_code"],
        "expiry_days": row["expiry_days"],
    }
