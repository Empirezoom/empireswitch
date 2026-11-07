import hmac
import hashlib
import time
import httpx
from typing import Dict, Any
from adapters.base import BaseGatewayAdapter
from models import ChargeRequest, PaymentChannel
import config

class FlutterwaveAdapter(BaseGatewayAdapter):
    @property
    def name(self) -> str:
        return "flutterwave"

    async def initialize_charge(self, request: ChargeRequest) -> Dict[str, Any]:
        url = "https://api.flutterwave.com/v3/payments"
        sec_key = getattr(request, "gateway_secret_key", None) or config.FLUTTERWAVE_SECRET_KEY
        if not sec_key or sec_key.startswith("FLWSECK_TEST-mock"):
            return {
                "success": False,
                "status": "failed",
                "channel": request.channel,
                "reference": request.reference,
                "message": "Flutterwave gateway is not configured with active live keys"
            }

        headers = {
            "Authorization": f"Bearer {sec_key}",
            "Content-Type": "application/json"
        }

        # Map channel
        channel_opts = {
            PaymentChannel.CARD: "card",
            PaymentChannel.BANK_TRANSFER: "banktransfer,account",
            PaymentChannel.USSD: "ussd",
            PaymentChannel.AUTO: "card,banktransfer,ussd"
        }
        payment_options = channel_opts.get(request.channel, "card,banktransfer,ussd")

        payload = {
            "tx_ref": request.reference,
            "amount": str(request.amount),
            "currency": request.currency,
            "payment_options": payment_options,
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
            "meta": {
                **request.metadata,
                "merchant_id": request.merchant_id,
                "channel_selected": str(request.channel)
            }
        }

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            data = resp.json()

            if resp.status_code == 200 and data.get("status") == "success":
                link = data.get("data", {}).get("link")
                return {
                    "success": True,
                    "status": "success",
                    "channel": request.channel,
                    "authorization_url": link,
                    "access_code": f"flw_ref_{request.reference}",
                    "virtual_bank_name": "Providus Bank (Flutterwave Rail)",
                    "virtual_account_number": f"88{int(time.time()) % 100000000:08d}",
                    "virtual_account_expires_at": "30 minutes",
                    "ussd_code": f"*901*000*{request.reference[-4:]}#",
                    "reference": request.reference,
                    "message": data.get("message", "Flutterwave initialized"),
                    "raw_response": data
                }
            else:
                return {
                    "success": False,
                    "status": "failed",
                    "channel": request.channel,
                    "authorization_url": None,
                    "access_code": None,
                    "reference": request.reference,
                    "message": data.get("message", f"Flutterwave error HTTP {resp.status_code}"),
                    "raw_response": data
                }

    async def verify_charge(self, reference: str) -> Dict[str, Any]:
        if not config.FLUTTERWAVE_SECRET_KEY or config.FLUTTERWAVE_SECRET_KEY.startswith("FLWSECK_TEST-mock"):
            return {
                "success": False,
                "status": "failed",
                "gateway_response": "Flutterwave keys not configured"
            }

        url = f"https://api.flutterwave.com/v3/transactions/verify_by_reference?tx_ref={reference}"
        headers = {"Authorization": f"Bearer {config.FLUTTERWAVE_SECRET_KEY}"}

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=headers)
            data = resp.json()
            if resp.status_code == 200 and data.get("status") == "success":
                tx_data = data.get("data", {})
                return {
                    "success": tx_data.get("status") == "successful",
                    "status": tx_data.get("status"),
                    "amount": tx_data.get("amount", 0),
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
        secret_hash = config.FLUTTERWAVE_SECRET_KEY
        return signature_header == secret_hash
