from abc import ABC, abstractmethod
from dataclasses import dataclass
from Pipeline.messaging.constructor import WhatsAppMessage


@dataclass
class SendResult:
    status: str  # "mocked" | "sent" | "failed"
    customer_id: str
    phone: str
    error_reason: str = ""


class BaseSender(ABC):
    @abstractmethod
    def send(
        self, message: WhatsAppMessage, customer_id: str, blast_id: str
    ) -> SendResult:
        pass
