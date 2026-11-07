import time
import asyncio
from typing import Dict, Any
from adapters.base import BaseGatewayAdapter
from models import ChargeRequest

class InterswitchSimulatorAdapter(BaseGatewayAdapter):
    def __init__(self):
        self.is_outage_simulated = False
        self.artificial_delay_ms = 45  # Blazing fast default

    @property
    def name(self) -> str:
        return "interswitch_sim"

    def set_simulation_state(self, outage: bool, delay_ms: int = 45):
        self.is_outage_simulated = outage
        self.artificial_delay_ms = delay_ms

    async def initialize_charge(self, request: ChargeRequest) -> Dict[str, Any]:
        if self.artificial_delay_ms > 0:
            await asyncio.sleep(self.artificial_delay_ms / 1000.0)

        if self.is_outage_simulated:
            return {
                "success": False,
                "status": "failed",
                "authorization_url": None,
                "access_code": None,
                "reference": request.reference,
                "message": "Gateway Timeout: 504 Gateway Unavailable (Fault Injection)",
                "raw_response": {"code": "GW_TIMEOUT", "error": "Simulated Gateway Failure"}
            }

        return {
            "success": True,
            "status": "success",
            "authorization_url": f"https://quickteller.com/pay/{request.reference}",
            "access_code": f"isw_ref_{request.reference[-6:]}",
            "reference": request.reference,
            "message": "Interswitch WebPay checkout initialized",
            "raw_response": {"response_code": "00", "description": "Transaction Approved"}
        }

    async def verify_charge(self, reference: str) -> Dict[str, Any]:
        return {
            "success": True,
            "status": "successful",
            "amount": 5000.0,
            "currency": "NGN",
            "gateway_response": "Approved by Interswitch Switch (00)",
            "channel": "direct_debit",
            "customer_email": "customer@example.com"
        }

    def verify_webhook_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        return True

