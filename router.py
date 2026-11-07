import time
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

import config
import storage
from models import (
    ChargeRequest,
    ChargeResponse,
    GatewayHealth,
    CircuitStatus,
    GatewayName,
    PaymentChannel
)
from adapters.paystack import PaystackAdapter
from adapters.flutterwave import FlutterwaveAdapter
from adapters.simulator import InterswitchSimulatorAdapter

class CircuitBreaker:
    def __init__(self, name: str):
        self.name = name
        self.status = CircuitStatus.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_state_change = time.time()
        self.manual_outage = False

    def can_execute(self) -> bool:
        if self.manual_outage:
            return False

        if self.status == CircuitStatus.CLOSED:
            return True

        if self.status == CircuitStatus.OPEN:
            if time.time() - self.last_state_change >= config.CIRCUIT_RECOVERY_TIME_SEC:
                self.status = CircuitStatus.HALF_OPEN
                self.last_state_change = time.time()
                return True
            return False

        if self.status == CircuitStatus.HALF_OPEN:
            return True

        return True

    def record_result(self, success: bool, latency_ms: float):
        storage.record_gateway_metric(self.name, success, latency_ms)

        if success:
            self.success_count += 1
            if self.status == CircuitStatus.HALF_OPEN:
                self.status = CircuitStatus.CLOSED
                self.failure_count = 0
                self.last_state_change = time.time()
        else:
            self.failure_count += 1
            if self.status in (CircuitStatus.CLOSED, CircuitStatus.HALF_OPEN):
                stats = storage.get_gateway_rolling_stats(self.name, limit=10)
                if stats["total"] >= config.MIN_SAMPLES_FOR_EVAL:
                    failure_rate = (stats["total"] - stats["successes"]) / stats["total"]
                    if failure_rate >= config.FAILURE_RATE_THRESHOLD or latency_ms > config.LATENCY_THRESHOLD_MS:
                        self.trip()

    def trip(self):
        self.status = CircuitStatus.OPEN
        self.last_state_change = time.time()

    def reset(self):
        self.status = CircuitStatus.CLOSED
        self.manual_outage = False
        self.failure_count = 0
        self.last_state_change = time.time()

class SmartGatewayRouter:
    def __init__(self):
        self.adapters = {
            "paystack": PaystackAdapter(),
            "flutterwave": FlutterwaveAdapter()
        }
        self.circuits = {
            name: CircuitBreaker(name) for name in self.adapters.keys()
        }

    def get_gateway_health(self, name: str) -> GatewayHealth:
        if name not in self.circuits:
            self.circuits[name] = CircuitBreaker(name)

        circuit = self.circuits[name]
        stats = storage.get_gateway_rolling_stats(name, limit=25)
        
        if circuit.manual_outage:
            score = 0
            circuit_status = CircuitStatus.OPEN
        else:
            circuit_status = circuit.status
            latency_factor = min(1.0, 300.0 / max(stats["avg_latency_ms"], 50.0))
            score = int((stats["success_rate"] * 70) + (latency_factor * 30))
            score = max(0, min(100, score))

        return GatewayHealth(
            gateway=name,
            circuit_status=circuit_status,
            health_score=score,
            success_rate=stats["success_rate"],
            avg_latency_ms=stats["avg_latency_ms"],
            total_requests=stats["total"],
            successful_requests=stats["successes"],
            failed_requests=stats["failures"],
            last_tripped_at=datetime.fromtimestamp(circuit.last_state_change).isoformat() if circuit.status == CircuitStatus.OPEN else None,
            manual_outage_active=circuit.manual_outage
        )

    def get_all_health(self, merchant_id: str = "mer_empirecodes_master") -> List[GatewayHealth]:
        merchant_gateways = storage.get_merchant_gateways(merchant_id)
        # Only report health for gateways configured with live credentials by this merchant
        active_gw_names = [g for g in merchant_gateways.keys() if g in self.adapters]
        if not active_gw_names and "paystack" in self.adapters:
            active_gw_names = ["paystack"]
        return [self.get_gateway_health(name) for name in active_gw_names]

    def set_manual_outage(self, name: str, outage: bool):
        if name in self.circuits:
            circuit = self.circuits[name]
            circuit.manual_outage = outage
            if outage:
                circuit.trip()
            else:
                circuit.reset()

    def select_gateway_priority(self, merchant_id: str, preferred: Optional[str] = None, channel: PaymentChannel = PaymentChannel.AUTO) -> List[str]:
        # Filter strictly by gateways the merchant has configured and activated
        merchant_gateways = storage.get_merchant_gateways(merchant_id)
        candidate_gateways = [g for g in merchant_gateways.keys() if g in self.adapters]

        if not candidate_gateways:
            return []

        if preferred and preferred in candidate_gateways:
            pref_circuit = self.circuits[preferred]
            if pref_circuit.can_execute():
                remaining = [g for g in candidate_gateways if g != preferred]
                remaining.sort(key=lambda g: self.get_gateway_health(g).health_score, reverse=True)
                return [preferred] + remaining

        # Sort candidate gateways by active QoS health score descending
        candidate_gateways.sort(
            key=lambda g: (
                1 if self.circuits[g].can_execute() else 0,
                self.get_gateway_health(g).health_score
            ),
            reverse=True
        )
        return candidate_gateways

    async def route_charge(self, request: ChargeRequest) -> ChargeResponse:
        merchant_id = request.merchant_id or "mer_empirecodes_master"

        # 1. Idempotency Check
        if request.idempotency_key:
            existing = storage.check_idempotency(request.idempotency_key)
            if existing:
                return ChargeResponse(
                    success=True,
                    status=existing["status"],
                    message="Idempotent response retrieved from ledger",
                    reference=existing["reference"],
                    gateway_used=existing["gateway_used"],
                    channel=existing.get("channel", "card"),
                    authorization_url=existing.get("authorization_url"),
                    virtual_bank_name=existing.get("virtual_bank_name"),
                    virtual_account_number=existing.get("virtual_account_number"),
                    ussd_code=existing.get("ussd_code"),
                    amount=existing["amount"],
                    currency=existing["currency"],
                    latency_ms=0.0,
                    failover_occurred=bool(existing.get("failover_occurred")),
                    attempted_gateways=[existing["gateway_used"]]
                )

        # 2. Reference Guarantee
        if not request.reference:
            request.reference = f"EMP-SW-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

        # 3. Dynamic Merchant Gateway Candidates (Only gateways with active merchant credentials)
        merchant_gateways = storage.get_merchant_gateways(merchant_id)
        gateway_candidates = self.select_gateway_priority(
            merchant_id=merchant_id,
            preferred=request.preferred_gateway.value if request.preferred_gateway else None,
            channel=request.channel
        )

        if not gateway_candidates:
            return ChargeResponse(
                success=False,
                status="failed",
                message=f"No active payment gateways configured for merchant '{merchant_id}'. Please register API keys.",
                reference=request.reference,
                gateway_used="none",
                channel=request.channel.value if hasattr(request.channel, 'value') else str(request.channel),
                amount=request.amount,
                currency=request.currency,
                latency_ms=0.0,
                failover_occurred=False,
                attempted_gateways=[]
            )

        attempted = []
        failover_occurred = False
        last_error_msg = "All configured gateway payment routes exhausted"

        for gateway_name in gateway_candidates:
            circuit = self.circuits[gateway_name]
            if not circuit.can_execute():
                continue

            attempted.append(gateway_name)
            adapter = self.adapters[gateway_name]

            # Inject merchant credentials into request for this gateway
            gw_cfg = merchant_gateways.get(gateway_name, {})
            setattr(request, "gateway_secret_key", gw_cfg.get("secret_key"))
            setattr(request, "gateway_public_key", gw_cfg.get("public_key"))

            t0 = time.perf_counter()
            try:
                result = await adapter.initialize_charge(request)
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)

                if result.get("success") is True:
                    circuit.record_result(success=True, latency_ms=latency_ms)

                    # Persist to financial ledger
                    tx_record = {
                        "reference": request.reference,
                        "merchant_id": request.merchant_id,
                        "idempotency_key": request.idempotency_key,
                        "amount": request.amount,
                        "currency": request.currency,
                        "customer_email": request.customer_email,
                        "customer_name": request.customer_name,
                        "channel": request.channel.value if hasattr(request.channel, 'value') else str(request.channel),
                        "gateway_used": gateway_name,
                        "status": "pending",
                        "authorization_url": result.get("authorization_url"),
                        "virtual_bank_name": result.get("virtual_bank_name"),
                        "virtual_account_number": result.get("virtual_account_number"),
                        "virtual_account_expires_at": result.get("virtual_account_expires_at"),
                        "ussd_code": result.get("ussd_code"),
                        "failover_occurred": failover_occurred,
                        "attempted_gateways": attempted,
                        "latency_ms": latency_ms,
                        "metadata": request.metadata
                    }
                    storage.save_transaction(tx_record)

                    return ChargeResponse(
                        success=True,
                        status="success",
                        message=f"Charge routed successfully through {gateway_name.upper()}",
                        reference=request.reference,
                        gateway_used=gateway_name,
                        channel=request.channel.value if hasattr(request.channel, 'value') else str(request.channel),
                        authorization_url=result.get("authorization_url"),
                        access_code=result.get("access_code"),
                        virtual_bank_name=result.get("virtual_bank_name"),
                        virtual_account_number=result.get("virtual_account_number"),
                        virtual_account_expires_at=result.get("virtual_account_expires_at"),
                        ussd_code=result.get("ussd_code"),
                        amount=request.amount,
                        currency=request.currency,
                        latency_ms=latency_ms,
                        failover_occurred=failover_occurred,
                        attempted_gateways=attempted
                    )
                else:
                    circuit.record_result(success=False, latency_ms=latency_ms)
                    last_error_msg = result.get("message", "Gateway returned failure status")
                    failover_occurred = True

            except Exception as e:
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)
                circuit.record_result(success=False, latency_ms=latency_ms)
                last_error_msg = str(e)
                failover_occurred = True

        return ChargeResponse(
            success=False,
            status="failed",
            message=f"Routing Failed: {last_error_msg}",
            reference=request.reference,
            gateway_used="none",
            channel=request.channel.value if hasattr(request.channel, 'value') else str(request.channel),
            amount=request.amount,
            currency=request.currency,
            latency_ms=0.0,
            failover_occurred=True,
            attempted_gateways=attempted
        )

# Global Router Instance
router_engine = SmartGatewayRouter()
