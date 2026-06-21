from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse

from Pipeline.config import WA_VERIFY_TOKEN
from Pipeline.database.db import transaction

router = APIRouter()

OPT_OUT_KEYWORD = "STOP"


def _is_opt_out(content: str) -> bool:
    return (content or "").strip().upper() == OPT_OUT_KEYWORD


def _flag_unsubscribe(sender: str) -> int:
    # Meta sends `sender` without a "+" (e.g. "6282123501897") while
    # customer.phone_number is stored with it, so compare digits only.
    digits = sender.lstrip("+")
    with transaction() as conn:
        cursor = conn.execute(
            "UPDATE customer SET is_unsubscribe = 1 WHERE REPLACE(phone_number, '+', '') = ?",
            (digits,),
        )
        return cursor.rowcount


@router.get("/webhook", summary="Meta webhook verification handshake")
def verify(
    mode: Annotated[Optional[str], Query(alias="hub.mode")] = None,
    token: Annotated[Optional[str], Query(alias="hub.verify_token")] = None,
    challenge: Annotated[Optional[str], Query(alias="hub.challenge")] = None,
):
    if mode == "subscribe" and token == WA_VERIFY_TOKEN:
        return PlainTextResponse(challenge or "")  # echo the challenge back
    return PlainTextResponse("Forbidden", status_code=403)


@router.post("/webhook", summary="Receive inbound messages and delivery statuses")
async def receive(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    try:
        value = data["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        print("[webhook] unrecognized payload:", data)
        return PlainTextResponse("OK")

    for msg in value.get("messages", []):
        sender = msg.get("from")
        msg_type = msg.get("type")
        text = msg.get("text", {}).get("body", "")

        ts = msg.get("timestamp")
        received_at = (
            datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
            if ts else datetime.now(timezone.utc).isoformat()
        )

        with transaction() as conn:
            conn.execute(
                "INSERT INTO incoming_messages (sender, content, received_at) VALUES (?, ?, ?)",
                (sender, text, received_at),
            )
        print(f"[webhook] message from {sender} ({msg_type}) at {received_at}: {text}")

        if msg_type == "text" and _is_opt_out(text):
            updated = _flag_unsubscribe(sender)
            print(f"[webhook] opt-out from {sender}: flagged {updated} customer row(s)")

    for status in value.get("statuses", []):
        status_val = status.get("status")
        print(f"[webhook] status {status.get('id')}: {status_val}")

        if status_val == "sent":
            recipient = status.get("recipient_id", "")
            ts = status.get("timestamp")
            sent_at = (
                datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
                if ts else datetime.now(timezone.utc).isoformat()
            )
            with transaction() as conn:
                conn.execute(
                    "INSERT INTO outgoing_messages (recipient, sent_at) VALUES (?, ?)",
                    (recipient, sent_at),
                )
            print(f"[webhook] logged outgoing to {recipient} at {sent_at}")

    return PlainTextResponse("OK")
