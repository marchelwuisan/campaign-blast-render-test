from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from Pipeline.engine.analyzer import AtRiskCustomer
    from Pipeline.messaging.constructor import WhatsAppMessage


@dataclass
class PromoOffer:
    promo_type: str  # e.g. "discount_30"
    promo_value: str  # e.g. "30% off your next purchase"
    promo_code: str  # e.g. "DISC30"
    expiry_days: int  # days until offer expires


@dataclass
class CustomerMessage:
    customer: "AtRiskCustomer"
    promo: PromoOffer
    message: Optional["WhatsAppMessage"] = None
