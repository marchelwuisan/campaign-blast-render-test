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
    template: dict = {
        "name": msg.template_name,
        "language": {"code": msg.language_code},
    }
    if msg.components is not None:
        template["components"] = msg.components
    else:
        components: list = []

        if msg.header_media:
            media_type = msg.header_media.get("type", "image")
            media_obj = {}
            if msg.header_media.get("link"):
                media_obj["link"] = msg.header_media["link"]
            elif msg.header_media.get("id"):
                media_obj["id"] = msg.header_media["id"]
            components.append({
                "type": "header",
                "parameters": [{"type": media_type, media_type: media_obj}],
            })
        elif msg.header_param:
            header_text = {"type": "text", "text": msg.header_param.get("value", "")}
            if msg.parameter_format != "POSITIONAL" and msg.header_param.get("name"):
                header_text["parameter_name"] = msg.header_param["name"]
            components.append({"type": "header", "parameters": [header_text]})

        if msg.template_params:
            if msg.parameter_format == "POSITIONAL":
                body_params = [
                    {"type": "text", "text": value}
                    for _, value in msg.template_params
                ]
            else:
                body_params = [
                    {"type": "text", "parameter_name": name, "text": value}
                    for name, value in msg.template_params
                ]
            components.append({"type": "body", "parameters": body_params})

        if components:
            template["components"] = components

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": msg.to,
        "type": "template",
        "template": template,
    }


def _post(payload: dict) -> requests.Response:
    return requests.post(_URL, headers=_HEADERS, json=payload, timeout=10)


def send_meta(msg: WhatsAppMessage) -> dict:
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
    except Exception:
        error_reason = response.text

    return {"status": "failed", "customer_id": msg.customer_id, "phone": msg.to, "promo_code": msg.promo_code,
            "error_code": str(response.status_code), "error_reason": error_reason}


def send_batch(messages: list) -> list:
    results = []
    for msg in messages:
        results.append(send_meta(msg))
        time.sleep(_INTERVAL)
    return results


class MetaSender(BaseSender):

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
