# POC: static promo mapping only.
# Production spec (unique codes, SQLite lifecycle, cooldown, AI toggle): see FLOW.md Stage 3

from Pipeline.engine.analyzer import AtRiskCustomer
from Pipeline.promo.schema import PromoOffer
from Pipeline.config import HIGH_VALUE_SPEND_THRESHOLD, PROMO_EXPIRY_DAYS

def assign_promo(customer: AtRiskCustomer) -> PromoOffer:
    risk = customer.risk_level
    rules = customer.triggered_rules
    spend = customer.spend_summary.total_spend

    if risk == "HIGH" and spend >= HIGH_VALUE_SPEND_THRESHOLD:
        return PromoOffer("discount_30", "30% off your next purchase", "BACK30", PROMO_EXPIRY_DAYS)

    if risk == "HIGH":
        return PromoOffer("discount_20", "20% off your next purchase", "BACK20", PROMO_EXPIRY_DAYS)

    if risk == "MEDIUM" and "R02" in rules:
        return PromoOffer("ship_discount_15", "Free shipping + 15% off", "SHIP15", PROMO_EXPIRY_DAYS)
    
    if risk == "MEDIUM" and "R04" in rules:
        return PromoOffer("bogo", "Buy 1 Get 1 on any item", "BOGO1", PROMO_EXPIRY_DAYS)

    return PromoOffer("points_2x", "2x loyalty points on your next purchase", "POINTS2X", PROMO_EXPIRY_DAYS)
