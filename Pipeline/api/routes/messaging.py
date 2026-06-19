import random
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Tuple

from Pipeline.database.db import transaction
from Pipeline.messaging.constructor import WhatsAppMessage
from Pipeline.messaging.meta_sender import send_meta, send_batch

router = APIRouter()


def _generate_code() -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # excludes 0/O, 1/I
    return "WA-" + "".join(random.choices(chars, k=6))


def _param(params, name: str):
    """Pull a template param value by name (params is a list of TemplateParam)."""
    for p in params or []:
        if p.name == name:
            return p.value
    return None


def _log_dispatch(blast_id: str, mode: str, messages, results) -> None:
    now = datetime.now()
    try:
        with transaction() as conn:
            for item, result in zip(messages, results):
                status = result.get("status")
                try:
                    days = int(_param(item.template_params, "expiry_days") or 7)
                except (TypeError, ValueError):
                    days = 7

                conn.execute(
                    """
                    INSERT INTO blast_log
                        (blast_id, customer_id, phone, template_name, promo_code,
                         status, error_code, error_reason, mode, sent_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        blast_id,
                        item.customer_id,
                        item.to,
                        item.template_name,
                        item.promo_code,
                        status,
                        result.get("error_code"),
                        result.get("error_reason"),
                        mode,
                        now.isoformat(),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO promo_codes
                        (code, customer_id, name, phone, promo_type, promo_value,
                         status, blast_id, issued_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _generate_code(),
                        item.customer_id,
                        _param(item.template_params, "name"),
                        item.to,
                        item.promo_code,
                        _param(item.template_params, "promo_value"),
                        "active" if status in ("sent", "mocked") else "cancelled",
                        blast_id,
                        now.isoformat(),
                        (now + timedelta(days=days)).isoformat(),
                    ),
                )
    except Exception as exc:  # noqa: BLE001
        print(f"[messaging] failed to log dispatch: {exc}")


class TemplateParam(BaseModel):
    name: str
    value: str


class SendMessageRequest(BaseModel):
    to: str
    customer_id: str
    promo_code: str
    template_name: str = "reengagement_promo"
    language_code: str = "en"
    template_params: Optional[List[TemplateParam]] = None
    parameter_format: str = "NAMED"
    header_param: Optional[dict] = None  # {"name": <param_name>, "value": <text>}
    header_media: Optional[dict] = None


class BulkSendRequest(BaseModel):
    messages: List[SendMessageRequest]
    sender_mode: str = "meta"


@router.post("/send")
def send_message(body: SendMessageRequest):
    params: List[Tuple[str, str]] = (
        [(p.name, p.value) for p in body.template_params]
        if body.template_params
        else []
    )

    msg = WhatsAppMessage(
        to=body.to,
        body="",
        customer_id=body.customer_id,
        promo_code=body.promo_code,
        template_name=body.template_name,
        language_code=body.language_code,
        template_params=params,
        parameter_format=body.parameter_format,
        header_param=body.header_param,
        header_media=body.header_media,
    )

    result = send_meta(msg)

    if result["status"] == "failed":
        raise HTTPException(status_code=502, detail=result)

    return result


@router.post("/send-bulk")
def send_bulk_message(body: BulkSendRequest):
    if not body.messages:
        raise HTTPException(status_code=400, detail="messages list is empty")

    wa_messages = []
    for item in body.messages:
        params = (
            [(p.name, p.value) for p in item.template_params]
            if item.template_params
            else []
        )
        wa_messages.append(
            WhatsAppMessage(
                to=item.to,
                body="",
                customer_id=item.customer_id,
                promo_code=item.promo_code,
                template_name=item.template_name,
                language_code=item.language_code,
                template_params=params,
                parameter_format=item.parameter_format,
                header_param=item.header_param,
                header_media=item.header_media,
            )
        )

    results = send_batch(wa_messages)

    blast_id = str(uuid.uuid4())
    _log_dispatch(blast_id, body.sender_mode, body.messages, results)

    sent = sum(1 for r in results if r["status"] == "sent")
    failed = sum(1 for r in results if r["status"] == "failed")

    return {
        "blast_id": blast_id,
        "total": len(results),
        "sent": sent,
        "failed": failed,
        "results": results,
    }
