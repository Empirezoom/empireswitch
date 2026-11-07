from abc import ABC, abstractmethod
from typing import Dict, Any
from models import ChargeRequest

class BaseGatewayAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def initialize_charge(self, request: ChargeRequest) -> Dict[str, Any]:
        """
        Initiates a charge transaction with the gateway.
        Returns:
            {
                "success": bool,
                "status": "success" | "failed",
                "authorization_url": str,
                "access_code": str,
                "reference": str,
                "message": str,
                "raw_response": dict
            }
        """
        pass

    @abstractmethod
    async def verify_charge(self, reference: str) -> Dict[str, Any]:
        """
        Queries gateway to verify payment status.
        """
        pass

    @abstractmethod
    def verify_webhook_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        """
        Cryptographically verifies incoming webhook payload HMAC signature.
        """
        pass

