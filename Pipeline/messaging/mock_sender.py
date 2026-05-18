from datetime import datetime
from Pipeline.database.db import transaction
from Pipeline.messaging.constructor import WhatsAppMessage
from Pipeline.messaging.base import BaseSender, SendResult


def send_mock(msg: WhatsAppMessage) -> dict:
    print(f"\n[MockSender] → {msg.to}")
    print(f"  Preview : {msg.body}")
    return {
        "status": "mocked",
        "customer_id": msg.customer_id,
        "phone": msg.to,
        "promo_code": msg.promo_code,
    }


class MockSender(BaseSender):
    def send(
        self, message: WhatsAppMessage, customer_id: str, blast_id: str
    ) -> SendResult:
        print(f"\n{'='*50}")
        print(f"TO      : {message.to}")
        print(f"BODY    :\n{message.body}")
        print(f"{'='*50}")

        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO blast_log
                    (blast_id, customer_id, phone, template_name, promo_code, status, sent_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    blast_id,
                    customer_id,
                    message.to,
                    message.template_name,
                    message.promo_code,
                    "mocked",
                    datetime.now().isoformat(),
                ),
            )

        return SendResult(status="mocked", customer_id=customer_id, phone=message.to)
