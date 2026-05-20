import uuid
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime, timedelta
import random
import string

from Pipeline.config import DATA_PATH, SENDER_MODE, BLAST_COOLDOWN_DAYS
from Pipeline.data.loader import load_customers
from Pipeline.engine.analyzer import analyze
from Pipeline.promo.mapping import assign_promo
from Pipeline.messaging.constructor import construct_message, validate_message
from Pipeline.messaging.mock_sender import MockSender
from Pipeline.database.db import transaction

router = APIRouter()


def _generate_code() -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # excludes 0/O, 1/I
    return "WA-" + "".join(random.choices(chars, k=6))


class BlastRequest(BaseModel):
    customer_ids: Optional[List[str]] = None
    ml_enabled: bool = False


def _run_pipeline(ml_enabled: bool = False):
    customers, date_cutoff = load_customers(DATA_PATH)
    at_risk, _, _ = analyze(customers, date_cutoff, ml_enabled=ml_enabled)
    promos = {c.customer_id: assign_promo(c) for c in at_risk}
    messages = {
        c.customer_id: construct_message(c, promos[c.customer_id]) for c in at_risk
    }
    return at_risk, promos, messages


def _apply_cooldown(at_risk: list) -> list:
    cutoff = (datetime.now() - timedelta(days=BLAST_COOLDOWN_DAYS)).isoformat()
    with transaction() as conn:
        rows = conn.execute(
            "SELECT customer_id FROM customer_blast_status WHERE last_sent_at >= ?",
            (cutoff,),
        ).fetchall()
    on_cooldown = {r["customer_id"] for r in rows}
    return [c for c in at_risk if c.customer_id not in on_cooldown]


@router.post("/preview")
def blast_preview(body: BlastRequest):
    at_risk, promos, messages = _run_pipeline(body.ml_enabled)

    if body.customer_ids:
        at_risk = [c for c in at_risk if c.customer_id in body.customer_ids]

    errors = {}
    for c in at_risk:
        err = validate_message(messages[c.customer_id])
        if err:
            errors[c.customer_id] = err

    return {
        "total": len(at_risk),
        "validation_errors": errors,
        "messages": [
            {
                "customer_id": c.customer_id,
                "phone": c.phone,
                "promo_code": promos[c.customer_id].promo_code,
                "body_preview": messages[c.customer_id].body,
                "sent": False,
            }
            for c in at_risk
        ],
    }


@router.post("/send")
def blast_send(body: BlastRequest):
    at_risk, promos, messages = _run_pipeline(body.ml_enabled)
    at_risk = _apply_cooldown(at_risk)

    if body.customer_ids:
        at_risk = [c for c in at_risk if c.customer_id in body.customer_ids]

    errors = {}
    for c in at_risk:
        err = validate_message(messages[c.customer_id])
        if err:
            errors[c.customer_id] = err

    if errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "Pre-flight validation failed", "errors": errors},
        )

    blast_id = str(uuid.uuid4())
    sender = MockSender()
    results = []
    now = datetime.now().isoformat()
    unique_codes = {}

    with transaction() as conn:
        for customer in at_risk:
            promo = promos[customer.customer_id]
            unique_code = _generate_code()
            unique_codes[customer.customer_id] = unique_code
            msg = messages[customer.customer_id]

            # write at-risk snapshot
            conn.execute(
                """
                INSERT INTO at_risk_customers
                    (blast_id, customer_id, name, phone, risk_level, days_inactive,
                     r_score, f_score, m_score, combined_score, triggered_rules, scored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    blast_id,
                    customer.customer_id,
                    customer.name,
                    customer.phone,
                    customer.risk_level,
                    customer.days_since_last_purchase,
                    customer.rfm.r_score,
                    customer.rfm.f_score,
                    customer.rfm.m_score,
                    customer.rfm.combined_score,
                    ",".join(customer.triggered_rules),
                    now,
                ),
            )

            # write promo assignment
            conn.execute(
                """
                INSERT INTO promo_assignments
                    (blast_id, customer_id, promo_type, promo_value, promo_code, expiry_days)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    blast_id,
                    customer.customer_id,
                    promo.promo_type,
                    promo.promo_value,
                    unique_code,
                    promo.expiry_days,
                ),
            )

            conn.execute(
                """
                INSERT INTO promo_codes
                    (code, customer_id, promo_type, discount_percent, issued_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    unique_code,
                    customer.customer_id,
                    promo.promo_type,
                    None,  # discount_percent — extend later if needed
                    now,
                    (
                        datetime.now()
                        + __import__("datetime").timedelta(days=promo.expiry_days)
                    ).isoformat(),
                ),
            )

            conn.execute(
                """
                INSERT INTO blast_log
                    (blast_id, customer_id, phone, template_name, promo_code, status, sent_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    blast_id,
                    customer.customer_id,
                    msg.to,
                    msg.template_name,
                    unique_code,
                    "pending",
                    datetime.now().isoformat(),
                ),
            )

    # send after all DB writes succeed
    for customer in at_risk:
        result = sender.send(
            messages[customer.customer_id], customer.customer_id, blast_id
        )
        results.append(result)

        with transaction() as conn:
            conn.execute(
                """
                UPDATE blast_log SET status = ?
                WHERE blast_id = ? AND customer_id = ?          
            """,
                (result.status, blast_id, customer.customer_id),
            )

        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO customer_blast_status (customer_id, last_sent_at, sent_promo_types)
                VALUES (?, ?, ?)
                ON CONFLICT(customer_id) DO UPDATE SET
                    last_sent_at = excluded.last_sent_at,
                    sent_promo_types = CASE
                        WHEN sent_promo_types = '' THEN excluded.sent_promo_types
                        ELSE sent_promo_types || ',' || excluded.sent_promo_types
                    END
            """,
                (
                    customer.customer_id,
                    datetime.now().isoformat(),
                    promos[customer.customer_id].promo_type,
                ),
            )

    sent = sum(1 for r in results if r.status in ("mocked", "sent"))
    failed = sum(1 for r in results if r.status == "failed")

    return {
        "blast_id": blast_id,
        "total": len(results),
        "sent": sent,
        "failed": failed,
        "sender_mode": SENDER_MODE,
    }


@router.get("/logs")
def blast_logs(
    limit: int = Query(50),
    offset: int = Query(0),
    since: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query("sent_at"),
    order: str = Query("desc"),
):
    direction = "DESC" if order == "desc" else "ASC"
    filters = []
    params = []

    if since:
        filters.append("sent_at >= ?")
        params.append(since)
    if search:
        filters.append("(customer_id LIKE ? OR phone LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    allowed_sort = {"sent_at", "customer_id", "status", "blast_id"}
    if sort_by not in allowed_sort:
        sort_by = "sent_at"

    query = f"""
        SELECT * FROM blast_log
        {where}
        ORDER BY {sort_by} {direction}
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    with transaction() as conn:
        rows = conn.execute(query, params).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM blast_log {where}", params[:-2]
        ).fetchone()[0]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": [dict(row) for row in rows],
    }
