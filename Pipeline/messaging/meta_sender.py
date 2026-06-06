"""Live WhatsApp sender backed by the Meta (Facebook) Graph API.

Business-initiated messages must use a pre-approved template, so every send
posts a `type: template` payload to the Cloud API. Used when SENDER_MODE="meta";
otherwise the MockSender is used instead.
"""

import time
import requests

from Pipeline.config import WA_ACCESS_TOKEN, WA_PHONE_NUMBER_ID, BLAST_RATE_LIMIT, RATE_LIMIT_WAIT_SECONDS
from Pipeline.messaging.constructor import WhatsAppMessage
from Pipeline.messaging.base import BaseSender, SendResult

# Cloud API "send message" endpoint for our registered business phone number.
_URL = f"https://graph.facebook.com/v25.0/{WA_PHONE_NUMBER_ID}/messages"
_HEADERS = {
    "Authorization": f"Bearer {WA_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}
# Minimum seconds between sends to stay under BLAST_RATE_LIMIT msgs/sec.
_INTERVAL = 1.0 / max(BLAST_RATE_LIMIT, 1)


def _build_payload(msg: WhatsAppMessage) -> dict:
    """Translate a WhatsAppMessage into the Graph API template payload."""
    template: dict = {
        "name": msg.template_name,
        "language": {"code": msg.language_code},
    }
    # Fill the template's {{placeholders}} with named body parameters.
    if msg.template_params:
        template["components"] = [{
            "type": "body",
            "parameters": [
                {"type": "text", "parameter_name": name, "text": value}
                for name, value in msg.template_params
            ],
        }]
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": msg.to,
        "type": "template",
        "template": template,
    }


def _post(payload: dict) -> requests.Response:
    """Single POST to the Graph API; 10s timeout to avoid hanging the blast."""
    return requests.post(_URL, headers=_HEADERS, json=payload, timeout=10)


def send_meta(msg: WhatsAppMessage) -> dict:
    """Send one message and return a result dict (never raises).

    Outcomes are normalized to {"status": "sent" | "failed", ...} so callers
    can aggregate results without handling HTTP/exception details.
    """
    payload = _build_payload(msg)

    # First attempt; a timeout is treated as a (retryable) failure, not a crash.
    try:
        response = _post(payload)
    except requests.Timeout:
        return {"status": "failed", "customer_id": msg.customer_id, "phone": msg.to, "promo_code": msg.promo_code,
                "error_code": "timeout", "error_reason": "request timed out"}

    # 429 = rate limited. Back off once and retry a single time.
    if response.status_code == 429:
        time.sleep(RATE_LIMIT_WAIT_SECONDS)
        try:
            response = _post(payload)
        except requests.Timeout:
            return {"status": "failed", "customer_id": msg.customer_id, "phone": msg.to, "promo_code": msg.promo_code,
                    "error_code": "429", "error_reason": "rate limit hit, retry timed out"}

    # Success: pull the Meta-assigned message id for later status/webhook matching.
    if response.status_code == 200:
        message_id = response.json().get("messages", [{}])[0].get("id")
        return {"status": "sent", "customer_id": msg.customer_id, "phone": msg.to,
                "promo_code": msg.promo_code, "message_id": message_id}

    # Any other status: surface Meta's error message (falling back to raw text).
    try:
        error_obj = response.json().get("error", {})
        error_reason = error_obj.get("message", response.text)
        print(f"[debug] full error: {error_obj}")
    except Exception:
        error_reason = response.text

    return {"status": "failed", "customer_id": msg.customer_id, "phone": msg.to, "promo_code": msg.promo_code,
            "error_code": str(response.status_code), "error_reason": error_reason}


def send_batch(messages: list) -> list:
    """Send messages sequentially, pausing _INTERVAL between each to respect rate limits."""
    results = []
    for msg in messages:
        results.append(send_meta(msg))
        time.sleep(_INTERVAL)
    return results


class MetaSender(BaseSender):
    """BaseSender adapter so the blast pipeline can use Meta interchangeably with MockSender."""

    def send(
        self, message: WhatsAppMessage, customer_id: str, blast_id: str
    ) -> SendResult:
        # Delegate to the function-based sender, then map its dict to a SendResult.
        result = send_meta(message)
        return SendResult(
            status=result["status"],
            customer_id=result.get("customer_id", customer_id),
            phone=result.get("phone", message.to),
            error_reason=result.get("error_reason", ""),
        )
