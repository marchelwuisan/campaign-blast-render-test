from dataclasses import dataclass

@dataclass
class PromoOffer:
    promo_type: str     # e.g. "discount_30"
    promo_value: str    # e.g. "30% off your next purchase"
    promo_code: str     # e.g. "BACK30"
    expiry_days: int    # days until offer expires

