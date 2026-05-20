import time
import requests

from Pipeline.config import WA_ACCESS_TOKEN, WA_PHONE_NUMBER_ID, BLAST_RATE_LIMIT, RATE_LIMIT_WAIT_SECONDS
from Pipeline.messaging.constructor import WhatsAppMessage

_URL = f"https://graph.facebook.com/v25.0/{WA_PHONE_NUMBER_ID}/messages"
_HEADERS = {
    "Authorization": f"Bearer {WA_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}
_INTERVAL = 1.0 / max(BLAST_RATE_LIMIT, 1)


def _build_payload(msg: WhatsAppMessage) -> dict:
    template: dict = {
        "name": msg.template_name,
        "language": {"code": msg.language_code},
    }
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
    return requests.post(_URL, headers=_HEADERS, json=payload, timeout=10)


def send_meta(msg: WhatsAppMessage) -> dict:
    payload = _build_payload(msg)

    try:
        response = _post(payload)
    except requests.Timeout:
        return {"status": "failed", "customer_id": msg.customer_id, "phone": msg.to, "promo_code": msg.promo_code,
                "error_code": "timeout", "error_reason": "request timed out"}

    if response.status_code == 429:
        time.sleep(RATE_LIMIT_WAIT_SECONDS)
        try:
            response = _post(payload)
        except requests.Timeout:
            return {"status": "failed", "customer_id": msg.customer_id, "phone": msg.to, "promo_code": msg.promo_code,
                    "error_code": "429", "error_reason": "rate limit hit, retry timed out"}

    if response.status_code == 200:
        message_id = response.json().get("messages", [{}])[0].get("id")
        return {"status": "sent", "customer_id": msg.customer_id, "phone": msg.to,
                "promo_code": msg.promo_code, "message_id": message_id}

    try:
        error_obj = response.json().get("error", {})
        error_reason = error_obj.get("message", response.text)
        print(f"[debug] full error: {error_obj}")
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
