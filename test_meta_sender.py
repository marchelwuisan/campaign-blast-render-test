"""
Dev script to validate MetaSender end-to-end using test_transactions.csv.
Not part of the production pipeline.
"""

from Pipeline.data.loader import load_customers
from Pipeline.engine.analyzer import analyze
from Pipeline.messaging.constructor import WhatsAppMessage
from Pipeline.messaging.meta_sender import send_meta


def main():
    customers, date_cutoff = load_customers("Pipeline/test_transactions.csv")
    at_risk, _, _ = analyze(customers, date_cutoff)

    if not at_risk:
        print("[test] no at-risk customers found — check test_transactions.csv")
        return

    customer = at_risk[0]
    print(f"[test] customer : {customer.customer_id} — {customer.name}")
    print(f"[test] phone    : {customer.phone}")
    print(f"[test] risk     : {customer.risk_level} (rules: {customer.triggered_rules})")

    from Pipeline.promo.mapping import assign_promo
    from Pipeline.messaging.constructor import construct_message, validate_message
    promo = assign_promo(customer)
    print(f"[test] promo    : {promo.promo_type} — {promo.promo_value} ({promo.promo_code})")
    msg = construct_message(customer, promo)
    err = validate_message(msg)
    if err:
        print(f"[test] VALIDATION FAILED: {err}")
        return
    print(f"\n[test] message preview:\n{msg.body}\n")

    print(f"\n[test] sending {msg.template_name} to {msg.to}...")
    result = send_meta(msg)

    print(f"[test] status    : {result['status']}")
    if result["status"] == "sent":
        print(f"[test] message_id: {result.get('message_id')}")
    else:
        print(f"[test] error     : [{result.get('error_code')}] {result.get('error_reason')}")


if __name__ == "__main__":
    main()
