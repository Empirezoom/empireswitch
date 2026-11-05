import hmac
import hashlib
import time
import httpx
from typing import Dict, Any
from adapters.base import BaseGatewayAdapter
from models import ChargeRequest
import config

class FlutterwaveAdapter(BaseGatewayAdapter):
    @property
    def name(self) -> str:
        return "flutterwave"

    async def initialize_charge(self, request: ChargeRequest) -> Dict[str, Any]:
        url = "https://api.flutterwave.com/v3/payments"
        headers = {
            "Authorization": f"Bearer {config.FLUTTERWAVE_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "tx_ref": request.reference,
            "amount": str(request.amount),
            "currency": request.currency,
            "redirect_url": f"https://empirecodes.com.ng/payment/callback?ref={request.reference}",
            "customer": {
                "email": request.customer_email,
                "name": request.customer_name or "Valued Client",
                "phonenumber": request.customer_phone or ""
            },
            "customizations": {
                "title": "EmpireCodes Platform Checkout",
                "logo": "https://empirecodes.com.ng/logo.png"
            },
            "meta": request.metadata
        }

        # Check for mock key vs live API
        if config.FLUTTERWAVE_SECRET_KEY.startswith("FLWSECK_TEST-mock"):
            time.sleep(0.09)
            return {
                "success": True,
                "status": "success",
                "authorization_url": f"https://ravemodal-dev.herokuapp.com/v3/hosted/pay/{request.reference}",
                "access_code": f"flw_link_{request.reference[-8:]}",
                "reference": request.reference,
                "message": "Flutterwave checkout initialized successfully",
                "raw_response": {"status": "success", "message": "Hosted link created"}
            }

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            data = resp.json()

            if resp.status_code == 200 and data.get("status") == "success":
                link = data.get("data", {}).get("link")
                return {
                    "success": True,
                    "status": "success",
                    "authorization_url": link,
                    "access_code": f"flw_ref_{request.reference}",
                    "reference": request.reference,
                    "message": data.get("message", "Flutterwave initialized"),
                    "raw_response": data
                }
            else:
                return {
                    "success": False,
                    "status": "failed",
                    "authorization_url": None,
                    "access_code": None,
                    "reference": request.reference,
                    "message": data.get("message", f"Flutterwave error HTTP {resp.status_code}"),
                    "raw_response": data
                }

    async def verify_charge(self, reference: str) -> Dict[str, Any]:
        url = f"https://api.flutterwave.com/v3/transactions/verify_by_reference?tx_ref={reference}"
        headers = {"Authorization": f"Bearer {config.FLUTTERWAVE_SECRET_KEY}"}

        if config.FLUTTERWAVE_SECRET_KEY.startswith("FLWSECK_TEST-mock"):
            return {
                "success": True,
                "status": "successful",
                "amount": 5000.0,
                "currency": "NGN",
                "gateway_response": "Approved (Mock Flutterwave)",
                "channel": "bank_transfer",
                "customer_email": "customer@example.com"
            }

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=headers)
            data = resp.json()
            if resp.status_code == 200 and data.get("status") == "success":
                tx_data = data.get("data", {})
                return {
                    "success": tx_data.get("status") == "successful",
                    "status": tx_data.get("status"),
                    "amount": float(tx_data.get("amount", 0)),
                    "currency": tx_data.get("currency", "NGN"),
                    "gateway_response": tx_data.get("processor_response", "Approved"),
                    "channel": tx_data.get("payment_type", "card"),
                    "customer_email": tx_data.get("customer", {}).get("email", "")
                }
            return {
                "success": False,
                "status": "failed",
                "gateway_response": data.get("message", "Verification failed")
            }

    def verify_webhook_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        # Flutterwave uses Secret Hash comparison
        expected_hash = config.FLUTTERWAVE_SECRET_KEY
        if not signature_header:
            return False
        return hmac.compare_digest(expected_hash, signature_header)
