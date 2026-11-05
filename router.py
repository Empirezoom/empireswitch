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
    GatewayName
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
            # Check if recovery window has passed -> transition to HALF_OPEN
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
                # Canary probe succeeded -> close circuit back to normal
                self.status = CircuitStatus.CLOSED
                self.failure_count = 0
                self.last_state_change = time.time()
        else:
            self.failure_count += 1
            if self.status in (CircuitStatus.CLOSED, CircuitStatus.HALF_OPEN):
                # Evaluate if breaker should trip
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
            "flutterwave": FlutterwaveAdapter(),
            "interswitch_sim": InterswitchSimulatorAdapter()
        }
        self.circuits = {
            name: CircuitBreaker(name) for name in self.adapters.keys()
        }

    def get_gateway_health(self, name: str) -> GatewayHealth:
        circuit = self.circuits[name]
        stats = storage.get_gateway_rolling_stats(name, limit=25)
        
        # Calculate algorithmic health score: 0 to 100
        # Success rate (70% weight) + Latency score (30% weight)
        if circuit.manual_outage:
            score = 0
            circuit_status = CircuitStatus.OPEN
        else:
            circuit_status = circuit.status
            latency_factor = min(1.0, 300.0 / max(stats["avg_latency_ms"], 50.0))
            score = int((stats["success_rate"] * 70.0) + (latency_factor * 30.0))
            if circuit_status == CircuitStatus.OPEN:
                score = min(score, 15)

        return GatewayHealth(
            gateway=name,
            circuit_status=circuit_status,
            health_score=score,
            success_rate=stats["success_rate"],
            avg_latency_ms=stats["avg_latency_ms"],
            total_requests=stats["total"],
            successful_requests=stats["successes"],
            failed_requests=stats["failures"],
            manual_outage_active=circuit.manual_outage
        )

    def get_all_health(self) -> List[GatewayHealth]:
        return [self.get_gateway_health(name) for name in self.adapters.keys()]

    def set_manual_outage(self, gateway: str, outage: bool):
        if gateway in self.circuits:
            self.circuits[gateway].manual_outage = outage
            if outage:
                self.circuits[gateway].trip()
                if gateway == "interswitch_sim":
                    self.adapters["interswitch_sim"].set_simulation_state(True)
            else:
                self.circuits[gateway].reset()
                if gateway == "interswitch_sim":
                    self.adapters["interswitch_sim"].set_simulation_state(False)

    def select_gateway_priority(self, preferred: Optional[str] = None) -> List[str]:
        # Sort gateways by Circuit Availability & Health Score
        all_gateways = list(self.adapters.keys())
        
        if preferred and preferred in all_gateways:
            # Move preferred to front if healthy
            circuit = self.circuits[preferred]
            if circuit.can_execute():
                other_gateways = [g for g in all_gateways if g != preferred]
                other_gateways.sort(
                    key=lambda g: (self.circuits[g].can_execute(), self.get_gateway_health(g).health_score),
                    reverse=True
                )
                return [preferred] + other_gateways

        # Rank all by health score
        all_gateways.sort(
            key=lambda g: (self.circuits[g].can_execute(), self.get_gateway_health(g).health_score),
            reverse=True
        )
        return all_gateways

    async def route_charge(self, request: ChargeRequest) -> ChargeResponse:
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
                    authorization_url=existing.get("authorization_url"),
                    amount=existing["amount"],
                    currency=existing["currency"],
                    latency_ms=0.0,
                    failover_occurred=bool(existing.get("failover_occurred")),
                    attempted_gateways=[existing["gateway_used"]]
                )

        # 2. Reference Guarantee
        if not request.reference:
            request.reference = f"EMP-SW-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

        # 3. Gateway Selection Order
        gateway_candidates = self.select_gateway_priority(
            preferred=request.preferred_gateway.value if request.preferred_gateway else None
        )

        attempted = []
        failover_occurred = False
        last_error_msg = "All gateway payment routes exhausted"

        for gateway_name in gateway_candidates:
            circuit = self.circuits[gateway_name]
            if not circuit.can_execute():
                continue

            attempted.append(gateway_name)
            adapter = self.adapters[gateway_name]

            # High-precision timer
            t0 = time.perf_counter()
            try:
                result = await adapter.initialize_charge(request)
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)

                if result.get("success") is True:
                    circuit.record_result(success=True, latency_ms=latency_ms)

                    # Persist to financial transactions ledger
                    tx_record = {
                        "reference": request.reference,
                        "idempotency_key": request.idempotency_key,
                        "amount": request.amount,
                        "currency": request.currency,
                        "customer_email": request.customer_email,
                        "gateway_used": gateway_name,
                        "status": "pending_authorization",
                        "authorization_url": result.get("authorization_url"),
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
                        authorization_url=result.get("authorization_url"),
                        access_code=result.get("access_code"),
                        amount=request.amount,
                        currency=request.currency,
                        latency_ms=latency_ms,
                        failover_occurred=failover_occurred,
                        attempted_gateways=attempted
                    )
                else:
                    # Gateway returned failure (e.g. 504 / rejected / outage)
                    circuit.record_result(success=False, latency_ms=latency_ms)
                    last_error_msg = result.get("message", "Gateway returned failure status")
                    failover_occurred = True

            except Exception as e:
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)
                circuit.record_result(success=False, latency_ms=latency_ms)
                last_error_msg = str(e)
                failover_occurred = True

        # All healthy candidate routes failed
        return ChargeResponse(
            success=False,
            status="failed",
            message=f"Routing Failed: {last_error_msg}",
            reference=request.reference,
            gateway_used="none",
            amount=request.amount,
            currency=request.currency,
            latency_ms=0.0,
            failover_occurred=True,
            attempted_gateways=attempted
        )

# Global Router Instance
router_engine = SmartGatewayRouter()
