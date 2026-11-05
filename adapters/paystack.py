import hmac
import hashlib
import time
import httpx
from typing import Dict, Any
from adapters.base import BaseGatewayAdapter
from models import ChargeRequest
import config

class PaystackAdapter(BaseGatewayAdapter):
    @property
    def name(self) -> str:
        return "paystack"

    async def initialize_charge(self, request: ChargeRequest) -> Dict[str, Any]:
        # Paystack expects amounts in Kobo (1 NGN = 100 Kobo)
        amount_kobo = int(request.amount * 100)
        url = "https://api.paystack.co/transaction/initialize"
        headers = {
            "Authorization": f"Bearer {config.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "email": request.customer_email,
            "amount": amount_kobo,
            "currency": request.currency,
            "reference": request.reference,
            "metadata": request.metadata
        }

        # Check for mock key vs live API
        if config.PAYSTACK_SECRET_KEY.startswith("sk_test_mock"):
            # Simulated high-speed Paystack sandbox
            time.sleep(0.08)
            return {
                "success": True,
                "status": "success",
                "authorization_url": f"https://checkout.paystack.com/{request.reference}",
                "access_code": f"pstk_acc_{request.reference[-8:]}",
                "reference": request.reference,
                "message": "Paystack checkout initialized successfully",
                "raw_response": {"status": True, "message": "Authorization URL created"}
            }

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            data = resp.json()

            if resp.status_code == 200 and data.get("status") is True:
                res_data = data.get("data", {})
                return {
                    "success": True,
                    "status": "success",
                    "authorization_url": res_data.get("authorization_url"),
                    "access_code": res_data.get("access_code"),
                    "reference": res_data.get("reference", request.reference),
                    "message": data.get("message", "Paystack initialized"),
                    "raw_response": data
                }
            else:
                return {
                    "success": False,
                    "status": "failed",
                    "authorization_url": None,
                    "access_code": None,
                    "reference": request.reference,
                    "message": data.get("message", f"Paystack error HTTP {resp.status_code}"),
                    "raw_response": data
                }

    async def verify_charge(self, reference: str) -> Dict[str, Any]:
        url = f"https://api.paystack.co/transaction/verify/{reference}"
        headers = {"Authorization": f"Bearer {config.PAYSTACK_SECRET_KEY}"}

        if config.PAYSTACK_SECRET_KEY.startswith("sk_test_mock"):
            return {
                "success": True,
                "status": "success",
                "amount": 5000.0,
                "currency": "NGN",
                "gateway_response": "Successful (Mock)",
                "channel": "card",
                "customer_email": "customer@example.com"
            }

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=headers)
            data = resp.json()
            if resp.status_code == 200 and data.get("status") is True:
                tx_data = data.get("data", {})
                return {
                    "success": tx_data.get("status") == "success",
                    "status": tx_data.get("status"),
                    "amount": tx_data.get("amount", 0) / 100.0,
                    "currency": tx_data.get("currency", "NGN"),
                    "gateway_response": tx_data.get("gateway_response", "Approved"),
                    "channel": tx_data.get("channel", "card"),
                    "customer_email": tx_data.get("customer", {}).get("email", "")
                }
            return {
                "success": False,
                "status": "failed",
                "gateway_response": data.get("message", "Verification failed")
            }

    def verify_webhook_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        if not signature_header:
            return False
        computed_hash = hmac.new(
            config.PAYSTACK_SECRET_KEY.encode('utf-8'),
            payload_bytes,
            hashlib.sha512
        ).hexdigest()
        return hmac.compare_digest(computed_hash, signature_header)
