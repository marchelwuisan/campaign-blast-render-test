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
from Pipeline.promo.schema import CustomerMessage
from Pipeline.messaging.constructor import construct_message, validate_message
from Pipeline.messaging.base import BaseSender
from Pipeline.messaging.mock_sender import MockSender
from Pipeline.messaging.meta_sender import MetaSender
from Pipeline.messaging import template_service
from Pipeline.database.db import transaction

router = APIRouter()


def _get_sender() -> BaseSender:
    if SENDER_MODE == "meta":
        return MetaSender()
    return MockSender()


def _run_engine(ml_enabled: bool = False):
    customers, date_cutoff = load_customers(DATA_PATH)
    at_risk, _, _ = analyze(customers, date_cutoff, ml_enabled=ml_enabled)
    return at_risk


def _apply_cooldown(at_risk):
    cutoff = (datetime.now() - timedelta(days=BLAST_COOLDOWN_DAYS)).isoformat()
    with transaction() as conn:
        rows = conn.execute(
            "SELECT customer_id FROM customer WHERE last_sent_at >= ?",
            (cutoff,),
        ).fetchall()
    on_cooldown = {r["customer_id"] for r in rows}
    return [c for c in at_risk if c.customer_id not in on_cooldown]


def _filter_unsubscribed(at_risk):
    with transaction() as conn:
        rows = conn.execute(
            "SELECT customer_id FROM customer WHERE is_unsubscribe = 1"
        ).fetchall()
    unsubscribed = {r["customer_id"] for r in rows}
    return [c for c in at_risk if c.customer_id not in unsubscribed]


def assign_promos(at_risk):
    return [CustomerMessage(customer=c, promo=assign_promo(c)) for c in at_risk]


def construct_messages(customer_messages):
    for cm in customer_messages:
        cm.message = construct_message(cm.customer, cm.promo)
    return customer_messages


def validate_messages(customer_messages):
    errors = {}
    for cm in customer_messages:
        err = validate_message(cm.message)
        if err:
            errors[cm.customer.customer_id] = err
    return errors


def send_blast(customer_messages, blast_id):
    sender = _get_sender()
    results = []
    for cm in customer_messages:
        result = sender.send(cm.message, cm.customer.customer_id, blast_id)
        results.append(result)

        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO blast_log
                    (blast_id, customer_id, phone, template_name, promo_code, status, sent_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    blast_id,
                    cm.customer.customer_id,
                    cm.message.to,
                    cm.message.template_name,
                    cm.promo.promo_code,
                    result.status,
                    datetime.now().isoformat(),
                ),
            )
            conn.execute(
                """
                INSERT INTO customer (customer_id, phone_number, last_sent_at, sent_promo_types)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(customer_id) DO UPDATE SET
                    phone_number = excluded.phone_number,
                    last_sent_at = excluded.last_sent_at,
                    sent_promo_types = CASE
                        WHEN sent_promo_types = '' THEN excluded.sent_promo_types
                        ELSE sent_promo_types || ',' || excluded.sent_promo_types
                    END
                """,
                (
                    cm.customer.customer_id,
                    cm.message.to,
                    datetime.now().isoformat(),
                    cm.promo.promo_type,
                ),
            )
    return results


def _generate_code() -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # excludes 0/O, 1/I
    return "WA-" + "".join(random.choices(chars, k=6))


class BlastRequest(BaseModel):
    ml_enabled: bool = False


@router.post("/send")
def blast_send(body: BlastRequest):
    
    if SENDER_MODE == "meta":
        template_service.sync_quietly()

    at_risk = _run_engine(body.ml_enabled)
    at_risk = _apply_cooldown(at_risk)
    at_risk = _filter_unsubscribed(at_risk)
    customer_messages = assign_promos(at_risk)
    customer_messages = construct_messages(customer_messages)

    errors = validate_messages(customer_messages)
    if errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "Pre-flight validation failed", "errors": errors},
        )

    if SENDER_MODE == "meta":
        template_errors = template_service.validate_sendable(
            {(cm.message.template_name, cm.message.language_code) for cm in customer_messages}
        )
        if template_errors:
            raise HTTPException(
                status_code=400,
                detail={"message": "Template validation failed", "errors": template_errors},
            )

    blast_id = str(uuid.uuid4())
    results = send_blast(customer_messages, blast_id)

    sent = sum(1 for r in results if r.status in ("mocked", "sent"))
    failed = sum(1 for r in results if r.status == "failed")

    return {
        "blast_id": blast_id,
        "total": len(results),
        "total_sent": sent,
        "total_failed": failed,
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
