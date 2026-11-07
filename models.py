from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

class CircuitStatus(str, Enum):
    CLOSED = "CLOSED"        # Normal healthy operation
    OPEN = "OPEN"            # Tripped - traffic diverted to failover
    HALF_OPEN = "HALF_OPEN"  # Testing recovery with trial traffic

class GatewayName(str, Enum):
    PAYSTACK = "paystack"
    FLUTTERWAVE = "flutterwave"
    INTERSWITCH_SIM = "interswitch_sim"

class PaymentChannel(str, Enum):
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    USSD = "ussd"
    AUTO = "auto"

class ChargeRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Amount to charge in standard currency unit (e.g. 5000.00 for NGN 5,000)")
    currency: str = Field(default="NGN", description="Currency code (e.g. NGN, USD, GHS)")
    customer_email: str = Field(..., description="Customer's email address")
    customer_name: Optional[str] = Field(default="Valued Client")
    customer_phone: Optional[str] = Field(default=None)
    reference: Optional[str] = Field(default=None, description="Unique merchant transaction reference")
    idempotency_key: Optional[str] = Field(default=None, description="Client idempotency key preventing duplicate billing")
    channel: PaymentChannel = Field(default=PaymentChannel.AUTO, description="Payment method: card, bank_transfer, ussd, or auto")
    preferred_gateway: Optional[GatewayName] = Field(default=None, description="Optional manual gateway override")
    merchant_id: Optional[str] = Field(default="mer_empirecodes_master", description="Merchant account ID")
    gateway_secret_key: Optional[str] = Field(default=None, description="Internal injected gateway secret key")
    gateway_public_key: Optional[str] = Field(default=None, description="Internal injected gateway public key")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class ChargeResponse(BaseModel):
    success: bool
    status: str
    message: str
    reference: str
    gateway_used: str
    channel: str = "card"
    authorization_url: Optional[str] = None
    access_code: Optional[str] = None
    virtual_bank_name: Optional[str] = None
    virtual_account_number: Optional[str] = None
    virtual_account_expires_at: Optional[str] = None
    ussd_code: Optional[str] = None
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
    health_score: int = 100
    success_rate: float = 1.0
    avg_latency_ms: float = 120.0
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    last_tripped_at: Optional[str] = None
    manual_outage_active: bool = False

class MerchantGatewayConfig(BaseModel):
    gateway: str
    public_key: str
    secret_key: str
    priority: int = 1
    is_active: bool = True
