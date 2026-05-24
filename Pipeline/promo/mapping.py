from Pipeline.engine.analyzer import AtRiskCustomer
from Pipeline.promo.schema import PromoOffer
from Pipeline.config import HIGH_VALUE_SPEND_THRESHOLD, PROMO_EXPIRY_DAYS


def assign_promo(customer: AtRiskCustomer) -> PromoOffer:
    risk = customer.risk_level
    spend = customer.spend_summary.total_spend

    if risk == "HIGH" and spend >= HIGH_VALUE_SPEND_THRESHOLD:
        return PromoOffer(
            "discount_20", "20% off your next purchase", "DISC20", PROMO_EXPIRY_DAYS
        )

    if risk == "HIGH":
        return PromoOffer(
            "discount_15", "15% off your next purchase", "DISC15", PROMO_EXPIRY_DAYS
        )

    if risk == "MEDIUM":
        return PromoOffer(
            "discount_10", "10% off your next purchase", "DISC10", PROMO_EXPIRY_DAYS
        )

    return PromoOffer(
        "discount_5", "5% off your next purchase", "DISC5", PROMO_EXPIRY_DAYS
    )
