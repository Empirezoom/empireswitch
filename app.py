import os
import json
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Header, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import config
import storage
from models import ChargeRequest, ChargeResponse, GatewayHealth, MerchantGatewayConfig
from router import router_engine

app = FastAPI(
    title="EmpireSwitch FinTech Engine",
    description="Fault-Tolerant Multi-Gateway Smart Router, Virtual Accounts & Circuit Breaker",
    version="2.0.0"
)

# Enable CORS for cross-origin frontend integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_FILE = BASE_DIR / "dashboard.html"
CHECKOUT_FILE = BASE_DIR / "checkout.html"
CHECKOUT_JS_FILE = BASE_DIR / "checkout.js"

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    if not DASHBOARD_FILE.exists():
        raise HTTPException(status_code=404, detail="Dashboard file not found")
    with open(DASHBOARD_FILE, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/checkout.html", response_class=HTMLResponse)
async def serve_checkout():
    if not CHECKOUT_FILE.exists():
        raise HTTPException(status_code=404, detail="Checkout file not found")
    with open(CHECKOUT_FILE, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/checkout.js")
async def serve_checkout_js():
    if not CHECKOUT_JS_FILE.exists():
        raise HTTPException(status_code=404, detail="Checkout SDK not found")
    with open(CHECKOUT_JS_FILE, "r", encoding="utf-8") as f:
        return Response(content=f.read(), media_type="application/javascript")

@app.post("/api/v1/charge", response_model=ChargeResponse)
async def route_charge(request: ChargeRequest):
    """
    Intelligent entrypoint for all payment initiations (Cards, Bank Transfer, USSD).
    Evaluates gateway QoS scores and auto-routes with sub-second failover.
    """
    response = await router_engine.route_charge(request)
    return response

@app.get("/api/v1/verify/{reference}")
async def verify_transaction(reference: str):
    """
    Verifies a transaction across the gateway it was routed to.
    """
    tx = storage.get_transaction_by_reference(reference)
    if not tx:
        raise HTTPException(status_code=404, detail=f"Transaction reference {reference} not found in ledger")

    gateway_name = tx["gateway_used"]
    adapter = router_engine.adapters.get(gateway_name)
    if not adapter:
        # If simulated or mock
        return {
            "status": tx["status"],
            "reference": reference,
            "gateway": gateway_name,
            "amount": tx["amount"],
            "currency": tx["currency"],
            "ledger_record": tx
        }

    verification = await adapter.verify_charge(reference)
    current_status = "success" if verification.get("success") else tx["status"]
    if current_status != tx["status"]:
        storage.update_transaction_status(reference, current_status)

    return {
        "status": current_status,
        "reference": reference,
        "gateway": gateway_name,
        "amount": tx["amount"],
        "currency": tx["currency"],
        "ledger_record": tx,
        "verification_result": verification
    }

@app.get("/api/v1/health")
async def get_gateway_health():
    """
    Returns real-time Circuit Breaker states, success rates, and latencies.
    """
    return router_engine.get_all_health()

@app.get("/api/v1/transactions")
async def get_transactions(limit: int = 25):
    """
    Returns latest transaction records from the ledger.
    """
    return storage.get_recent_transactions(limit=limit)

@app.get("/api/v1/merchants/gateways")
async def get_merchant_gateways(merchant_id: str = "mer_empirecodes_master"):
    """
    Fetches active payment gateway configurations for a merchant.
    """
    return storage.get_merchant_gateways(merchant_id)

@app.post("/api/v1/merchants/gateways")
async def update_merchant_gateway(config_req: MerchantGatewayConfig, merchant_id: str = "mer_empirecodes_master"):
    """
    Allows merchants to update their own Paystack/Flutterwave API keys.
    """
    storage.save_merchant_gateway(
        merchant_id=merchant_id,
        gateway=config_req.gateway,
        pub_key=config_req.public_key,
        sec_key=config_req.secret_key,
        priority=config_req.priority
    )
    return {"status": "success", "message": f"{config_req.gateway.upper()} credentials updated successfully"}

@app.post("/api/v1/simulate/outage")
async def simulate_outage(payload: dict):
    """
    Live Demo Hook: Trips or restores a gateway's circuit breaker to test automatic failover.
    Payload: {"gateway": "paystack", "outage": true}
    """
    gateway = payload.get("gateway")
    outage = bool(payload.get("outage"))

    if gateway not in router_engine.adapters:
        raise HTTPException(status_code=400, detail=f"Unknown gateway: {gateway}")

    router_engine.set_manual_outage(gateway, outage)
    return {
        "success": True,
        "gateway": gateway,
        "outage_simulated": outage,
        "circuit_status": router_engine.circuits[gateway].status
    }

@app.post("/api/v1/webhooks/{gateway}")
async def receive_webhook(gateway: str, request: Request):
    """
    Cryptographic webhook ingestion point.
    Validates HMAC signatures and prevents replay/duplicate credit attacks.
    """
    if gateway not in router_engine.adapters:
        raise HTTPException(status_code=404, detail=f"Unsupported webhook gateway: {gateway}")

    adapter = router_engine.adapters[gateway]
    body_bytes = await request.body()

    signature = (
        request.headers.get("x-paystack-signature") or
        request.headers.get("verif-hash") or
        ""
    )

    verified = adapter.verify_webhook_signature(body_bytes, signature)
    
    # Parse payload and update transaction status in ledger
    ref = None
    status = "pending"
    event_type = "unknown"
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
        if gateway == "paystack":
            data = payload.get("data", {})
            ref = data.get("reference")
            event_type = payload.get("event", "charge.success")
            if event_type == "charge.success":
                status = "success"
            elif event_type in ["charge.failed", "transfer.failed"]:
                status = "failed"
        elif gateway == "flutterwave":
            data = payload.get("data", {})
            ref = data.get("tx_ref")
            event_type = payload.get("event", "charge.completed")
            if data.get("status") == "successful":
                status = "success"
            else:
                status = data.get("status", "failed")

        storage.log_webhook_event(gateway, event_type, ref or "unknown", payload, verified)

        if verified and ref:
            storage.update_transaction_status(ref, status)
            print(f"[WEBHOOK] Reconciled Ref={ref} -> Status={status}")
    except Exception as e:
        print(f"[WEBHOOK WARNING] Failed to parse payload: {e}")

    if not verified:
        raise HTTPException(status_code=401, detail="Cryptographic webhook signature verification failed")

    return {"status": "success", "message": f"{gateway.upper()} webhook cryptographically verified and processed"}

if __name__ == "__main__":
    print(f"[EMPIRESWITCH] Engine running at http://{config.SERVER_HOST}:{config.SERVER_PORT}")
    uvicorn.run("app:app", host=config.SERVER_HOST, port=config.SERVER_PORT, reload=True)
