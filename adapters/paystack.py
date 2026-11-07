import hmac
import hashlib
import time
import httpx
from typing import Dict, Any
from adapters.base import BaseGatewayAdapter
from models import ChargeRequest, PaymentChannel
import config

class PaystackAdapter(BaseGatewayAdapter):
    @property
    def name(self) -> str:
        return "paystack"

    async def initialize_charge(self, request: ChargeRequest) -> Dict[str, Any]:
        amount_kobo = int(request.amount * 100)

        sec_key = getattr(request, "gateway_secret_key", None) or config.PAYSTACK_SECRET_KEY
        if not sec_key or sec_key.startswith("sk_test_mock"):
            return {
                "success": False,
                "status": "failed",
                "channel": request.channel,
                "reference": request.reference,
                "message": "Paystack gateway is not configured with active live keys"
            }

        headers = {
            "Authorization": f"Bearer {sec_key}",
            "Content-Type": "application/json"
        }

        # If customer explicitly requested Bank Transfer, attempt Paystack Direct Charge for immediate Virtual Account
        if request.channel == PaymentChannel.BANK_TRANSFER:
            charge_url = "https://api.paystack.co/charge"
            charge_payload = {
                "email": request.customer_email,
                "amount": amount_kobo,
                "currency": request.currency,
                "reference": request.reference,
                "bank_transfer": {},
                "metadata": {
                    **request.metadata,
                    "customer_name": request.customer_name,
                    "merchant_id": request.merchant_id,
                    "channel_selected": "bank_transfer"
                }
            }
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(charge_url, json=charge_payload, headers=headers)
                    data = resp.json()
                    if resp.status_code == 200 and data.get("status") is True:
                        res_data = data.get("data", {})
                        bank_info = res_data.get("bank", {})
                        acc_num = res_data.get("account_number")
                        bank_name = bank_info.get("name") if isinstance(bank_info, dict) else "Titan / Wema Bank"
                        
                        return {
                            "success": True,
                            "status": "success",
                            "channel": "bank_transfer",
                            "authorization_url": f"https://checkout.paystack.com/{request.reference}",
                            "access_code": res_data.get("access_code"),
                            "virtual_bank_name": bank_name,
                            "virtual_account_number": acc_num,
                            "virtual_account_expires_at": "30 minutes",
                            "ussd_code": f"*737*000*{request.reference[-4:]}#",
                            "reference": request.reference,
                            "message": data.get("message", "Paystack virtual account generated"),
                            "raw_response": data
                        }
            except Exception as e:
                print(f"[Paystack Direct Charge Fallback]: {e}")

        # Standard Hosted Transaction Initialize
        url = "https://api.paystack.co/transaction/initialize"
        channels_map = {
            PaymentChannel.CARD: ["card"],
            PaymentChannel.BANK_TRANSFER: ["bank_transfer", "bank"],
            PaymentChannel.USSD: ["ussd"],
            PaymentChannel.AUTO: ["card", "bank", "ussd", "bank_transfer"]
        }
        selected_channels = channels_map.get(request.channel, ["card", "bank", "ussd", "bank_transfer"])

        payload = {
            "email": request.customer_email,
            "amount": amount_kobo,
            "currency": request.currency,
            "reference": request.reference,
            "channels": selected_channels,
            "metadata": {
                **request.metadata,
                "customer_name": request.customer_name,
                "merchant_id": request.merchant_id,
                "channel_selected": request.channel
            }
        }

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            data = resp.json()

            if resp.status_code == 200 and data.get("status") is True:
                res_data = data.get("data", {})
                auth_url = res_data.get("authorization_url")
                
                return {
                    "success": True,
                    "status": "success",
                    "channel": request.channel,
                    "authorization_url": auth_url,
                    "access_code": res_data.get("access_code"),
                    "virtual_bank_name": "Titan Trust Bank / Wema Bank",
                    "virtual_account_number": "Click checkout link for live account",
                    "virtual_account_expires_at": "30 minutes",
                    "ussd_code": f"*737*000*{request.reference[-4:]}#",
                    "reference": res_data.get("reference", request.reference),
                    "message": data.get("message", "Paystack initialized"),
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
                    "message": data.get("message", f"Paystack error HTTP {resp.status_code}"),
                    "raw_response": data
                }

    async def verify_charge(self, reference: str) -> Dict[str, Any]:
        if not config.PAYSTACK_SECRET_KEY or config.PAYSTACK_SECRET_KEY.startswith("sk_test_mock"):
            return {
                "success": False,
                "status": "failed",
                "gateway_response": "Paystack API keys not configured"
            }

        url = f"https://api.paystack.co/transaction/verify/{reference}"
        headers = {"Authorization": f"Bearer {config.PAYSTACK_SECRET_KEY}"}

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
