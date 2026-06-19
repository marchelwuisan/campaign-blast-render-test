from typing import Annotated, Optional

from fastapi import APIRouter, Query

from Pipeline.database.db import transaction

router = APIRouter()


def _dispatch_row(r) -> dict:
    return {
        "id": r["id"],
        "sentAt": r["sent_at"],
        "name": r["name"],
        "customerId": r["customer_id"],
        "phone": r["phone"],
        "code": r["promo_code"],
        "status": r["status"],
        "errorCode": r["error_code"],
        "errorReason": r["error_reason"],
        "blastId": r["blast_id"],
    }


@router.get("", summary="Blast history (aggregated by blast_id)")
def blast_history():
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT blast_id,
                   MIN(sent_at)                                          AS started,
                   MAX(mode)                                             AS mode,
                   MAX(template_name)                                    AS template,
                   COUNT(*)                                              AS total,
                   SUM(CASE WHEN status IN ('sent','mocked') THEN 1 ELSE 0 END) AS sent,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)    AS failed
            FROM blast_log
            GROUP BY blast_id
            ORDER BY started DESC
            """
        ).fetchall()
        redeemed = dict(
            conn.execute(
                "SELECT blast_id, COUNT(*) FROM promo_codes WHERE status = 'redeemed' GROUP BY blast_id"
            ).fetchall()
        )

    return [
        {
            "id": r["blast_id"],
            "started": r["started"],
            "mode": r["mode"] or "meta",
            "template": r["template"],
            "total": r["total"],
            "sent": r["sent"],
            "failed": r["failed"],
            "redeemed": redeemed.get(r["blast_id"], 0),
        }
        for r in rows
    ]


def _dispatch_query(blast_id: Optional[str]):
    sql = """
        SELECT b.*, a.name AS name
        FROM blast_log b
        LEFT JOIN analyzed_customers a ON a.customer_id = b.customer_id
    """
    params = []
    if blast_id:
        sql += " WHERE b.blast_id = ?"
        params.append(blast_id)
    sql += " ORDER BY b.sent_at DESC"
    with transaction() as conn:
        return conn.execute(sql, params).fetchall()


@router.get("/dispatch", summary="Per-recipient dispatch rows")
def dispatch_log(blast_id: Annotated[Optional[str], Query()] = None):
    return [_dispatch_row(r) for r in _dispatch_query(blast_id)]


@router.get("/{blast_id}/dispatch", summary="Dispatch rows for one blast")
def dispatch_log_for_blast(blast_id: str):
    return [_dispatch_row(r) for r in _dispatch_query(blast_id)]
