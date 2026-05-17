from dataclasses import dataclass, field
from typing import List

from Pipeline.engine.analyzer import AtRiskCustomer
from Pipeline.promo.schema import PromoOffer

TEMPLATE_NAME = "reengagement_promo"
LANGUAGE_CODE = "en_US"

TEMPLATE = """Hi {customer_name}, we miss you!

It's been a while since your last visit.
Here's a personal offer just for you: {offer}.

Use code {code_id} - valid for {days_valid} days.

See you soon!"""

@dataclass
class WhatsAppMessage:
    to: str
    body: str
    customer_id: str
    promo_code: str
    template_name: str = TEMPLATE_NAME
    language_code: str = LANGUAGE_CODE
    template_params: List[str] = field(default_factory=list)


def construct_message(customer: AtRiskCustomer, promo: PromoOffer) -> WhatsAppMessage:
    body = TEMPLATE.format(
        customer_name=customer.name,
        offer=promo.promo_value,
        code_id=promo.promo_code,
        days_valid=promo.expiry_days,
    )
    return WhatsAppMessage(
        to=customer.phone,
        body=body,
        customer_id=customer.customer_id,
        promo_code=promo.promo_code,
        template_params=[
            customer.name,
            promo.promo_value,
            promo.promo_code,
            str(promo.expiry_days),
        ],
    )


def validate_message(msg: WhatsAppMessage) -> str | None:
    """Returns error string if invalid, None if ok."""
    for i, param in enumerate(msg.template_params):
        if not param or not param.strip():
            return f"empty template param at position {i + 1}"
    if len(msg.body) > 1024:
        return f"message body exceeds 1024 chars ({len(msg.body)})"
    return None
