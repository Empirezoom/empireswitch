from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, EmailStr

class CircuitStatus(str, Enum):
    CLOSED = "CLOSED"        # Normal healthy operation
    OPEN = "OPEN"            # Tripped - traffic diverted to failover
    HALF_OPEN = "HALF_OPEN"  # Testing recovery with trial traffic

class GatewayName(str, Enum):
    PAYSTACK = "paystack"
    FLUTTERWAVE = "flutterwave"
    INTERSWITCH_SIM = "interswitch_sim"

class ChargeRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Amount to charge in standard currency unit (e.g. 5000.00 for NGN 5,000)")
    currency: str = Field(default="NGN", description="Currency code (e.g. NGN, USD, GHS)")
    customer_email: str = Field(..., description="Customer's email address")
    customer_name: Optional[str] = Field(default="Valued Customer")
    customer_phone: Optional[str] = Field(default=None)
    reference: Optional[str] = Field(default=None, description="Unique merchant transaction reference")
    idempotency_key: Optional[str] = Field(default=None, description="Client idempotency key preventing duplicate billing")
    preferred_gateway: Optional[GatewayName] = Field(default=None, description="Optional manual gateway override")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class ChargeResponse(BaseModel):
    success: bool
    status: str
    message: str
    reference: str
    gateway_used: str
    authorization_url: Optional[str] = None
    access_code: Optional[str] = None
    amount: float
    currency: str
    latency_ms: float
    failover_occurred: bool = False
    attempted_gateways: List[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class VerifyResponse(BaseModel):
    success: bool
    status: str
    reference: str
    gateway_used: str
    amount: float
    currency: str
    paid_at: Optional[str] = None
    channel: Optional[str] = None
    customer_email: str
    gateway_response: str
    raw_response: Optional[Dict[str, Any]] = None

class GatewayHealth(BaseModel):
    gateway: str
    circuit_status: CircuitStatus
    health_score: int = 100  # 0 to 100
    success_rate: float = 1.0  # 0.0 to 1.0
    avg_latency_ms: float = 120.0
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    last_tripped_at: Optional[str] = None
    manual_outage_active: bool = False

class WebhookPayload(BaseModel):
    gateway: str
    event: str
    reference: str
    amount: float
    verified: bool
    raw_payload: Dict[str, Any]
