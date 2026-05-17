from dataclasses import dataclass
from Pipeline.engine.analyzer import AtRiskCustomer
from Pipeline.promo.schema import PromoOffer


TEMPLATE = """Hi {name}, we miss you!

It's been a while since your last visit.
Here's a personal offer just for you: {promo_value}.

Use code {promo_code} - valid for {expiry_days} days.

See you soon!"""

@dataclass
class WhatsAppMessage:
    to: str
    body: str

def construct_message(customer: AtRiskCustomer, promo: PromoOffer) -> WhatsAppMessage:
    body = TEMPLATE.format(
        name=customer.name,
        promo_value=promo.promo_value,
        promo_code=promo.promo_code,
        expiry_days=promo.expiry_days,
    )
    return WhatsAppMessage(to=customer.phone, body=body)