from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Tuple

from Pipeline.messaging.constructor import WhatsAppMessage
from Pipeline.messaging.meta_sender import send_meta, send_batch

router = APIRouter()


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


class BulkSendRequest(BaseModel):
    messages: List[SendMessageRequest]


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
            )
        )

    results = send_batch(wa_messages)

    sent = sum(1 for r in results if r["status"] == "sent")
    failed = sum(1 for r in results if r["status"] == "failed")

    return {
        "total": len(results),
        "sent": sent,
        "failed": failed,
        "results": results,
    }
