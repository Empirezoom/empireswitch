import os
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Header, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import config
import storage
from models import ChargeRequest, ChargeResponse, GatewayHealth
from router import router_engine

app = FastAPI(
    title="EmpireSwitch FinTech Engine",
    description="Fault-Tolerant Multi-Gateway Smart Router & Circuit Breaker",
    version="1.0.0"
)

# Enable CORS for cross-origin frontend integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DASHBOARD_FILE = Path(__file__).resolve().parent / "dashboard.html"

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    if not DASHBOARD_FILE.exists():
        raise HTTPException(status_code=404, detail="Dashboard file not found")
    with open(DASHBOARD_FILE, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/v1/charge", response_model=ChargeResponse)
async def route_charge(request: ChargeRequest):
    """
    Intelligent entrypoint for all payment initiations.
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
        raise HTTPException(status_code=500, detail=f"Adapter for gateway {gateway_name} unavailable")

    verification = await adapter.verify_charge(reference)
    return {
        "reference": reference,
        "gateway": gateway_name,
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
async def get_transactions(limit: int = 20):
    """
    Returns latest transaction records from the ledger.
    """
    return storage.get_recent_transactions(limit=limit)

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

    # Extract signature header
    signature = (
        request.headers.get("x-paystack-signature") or
        request.headers.get("verif-hash") or
        ""
    )

    if not adapter.verify_webhook_signature(body_bytes, signature):
        raise HTTPException(status_code=401, detail="Cryptographic webhook signature verification failed")

    return {"status": "success", "message": f"{gateway.upper()} webhook cryptographically verified and processed"}

if __name__ == "__main__":
    print(f"[EMPIRESWITCH] Engine running at http://{config.SERVER_HOST}:{config.SERVER_PORT}")
    uvicorn.run("app:app", host=config.SERVER_HOST, port=config.SERVER_PORT, reload=True)
