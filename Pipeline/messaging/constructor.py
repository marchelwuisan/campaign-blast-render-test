from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from Pipeline.engine.analyzer import AtRiskCustomer
from Pipeline.promo.schema import PromoOffer

TEMPLATE_NAME = "reengagement_promo"
LANGUAGE_CODE = "en"

TEMPLATE = """Hi {name}, we miss you!

It's been a while since your last visit.
Here's a personal offer just for you: {promo_value}.

Use code {promo_code} - valid for {expiry_days} days.

See you soon!"""


@dataclass
class WhatsAppMessage:
    to: str
    body: str
    customer_id: str
    promo_code: str
    template_name: str = TEMPLATE_NAME
    language_code: str = LANGUAGE_CODE
    template_params: List[Tuple[str, str]] = field(default_factory=list)
    # Fully-formed Graph API `components` array. When set, it is sent verbatim
    # (lets callers send any template shape — buttons, limited-time offer, media
    # header, etc.). When None, a body component is built from template_params.
    components: Optional[List[Dict[str, Any]]] = None


def construct_message(customer: AtRiskCustomer, promo: PromoOffer) -> WhatsAppMessage:
    body = TEMPLATE.format(
        name=customer.name,
        promo_value=promo.promo_value,
        promo_code=promo.promo_code,
        expiry_days=promo.expiry_days,
    )
    return WhatsAppMessage(
        to=customer.phone,
        body=body,
        customer_id=customer.customer_id,
        promo_code=promo.promo_code,
        template_params=[
            ("name", customer.name),
            ("promo_value", promo.promo_value),
            ("promo_code", promo.promo_code),
            ("expiry_days", str(promo.expiry_days)),
        ],
    )


def validate_message(msg: WhatsAppMessage) -> str | None:
    """Returns error string if invalid, None if ok."""
    for name, value in msg.template_params:
        if not value or not value.strip():
            return f"empty template param '{name}'"
    if len(msg.body) > 1024:
        return f"message body exceeds 1024 chars ({len(msg.body)})"
    return None
