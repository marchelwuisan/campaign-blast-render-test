from Pipeline.messaging.constructor import WhatsAppMessage


def send_mock(msg: WhatsAppMessage) -> dict:
    print(f"\n[MockSender] → {msg.to}")
    print(f"  Preview : {msg.body}")
    return {"status": "mocked", "customer_id": msg.customer_id, "phone": msg.to, "promo_code": msg.promo_code}
