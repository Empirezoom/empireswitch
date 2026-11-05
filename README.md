# EmpireSwitch: High-Availability FinTech Gateway Router & Circuit Breaker

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-38bdf8?style=for-the-badge&logo=python)](https://python.org)
[![Resilience](https://img.shields.io/badge/Pattern-Circuit%20Breaker%20%7C%20QoS-orange?style=for-the-badge)](https://empirecodes.com.ng)
[![Architect](https://img.shields.io/badge/Lead%20Architect-Anthony%20Oluwaseun%20Matthew-blueviolet?style=for-the-badge)](https://empirecodes.com.ng)

**EmpireSwitch** is an enterprise-grade, fault-tolerant payment gateway router and circuit breaker designed to eliminate transaction drop-off across African and global e-commerce systems. 

When a payment provider (e.g., Paystack, Flutterwave, or Interswitch) suffers network downtime, API degradation, or bank route failures, **EmpireSwitch automatically detects the failure and seamlessly reroutes transaction traffic to the healthiest alternative gateway in sub-seconds with zero dropped payments.**

---

## 🏛️ System Architecture

```
                  [ Merchant Client / Frontend App ]
                                   │
                                   ▼ POST /api/v1/charge
                    ┌───────────────────────────────┐
                    │     EmpireSwitch Router       │
                    │  (Dynamic QoS Health Scorer)  │
                    └──────────────┬────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
     [ Circuit Breaker ]  [ Circuit Breaker ]  [ Circuit Breaker ]
     Paystack (Primary)   Flutterwave (Backup)  Interswitch (Fallback)
              │                    │                    │
              ▼                    ▼                    ▼
     [ Paystack API ]     [ Flutterwave API ]   [ Interswitch Switch ]
```

---

## ⚡ Core Engineering Capabilities

1. **Dynamic Quality-of-Service (QoS) Scorer:**
   - Real-time algorithmic scoring (0 to 100) combining rolling success rate (70% weight) and round-trip network latency (30% weight).
   - Routes new charges strictly through the highest-scoring available gateway.
2. **Autonomous Circuit Breaker Pattern:**
   - **CLOSED (Healthy):** Normal high-throughput routing.
   - **OPEN (Tripped):** Automatically trips when a provider's failure rate exceeds 20% or latency exceeds 2,500ms, immediately diverting all traffic away from the failing gateway.
   - **HALF-OPEN (Probing):** Sends trial canary requests after a 30-second recovery window to test provider stability before restoring normal traffic.
3. **Idempotency Guarantee:**
   - Client-provided or auto-generated idempotency keys indexed in an ACID ledger prevent duplicate customer charges during network retries.
4. **Cryptographic Webhook Ingestion:**
   - Validates incoming callback signatures (`HMAC-SHA512` for Paystack, secret hash for Flutterwave) to prevent spoofing and replay attacks.
5. **Real-Time Visual Telemetry Dashboard:**
   - Live web console on port `8088` visualizing gateway latency, circuit breaker states, and live transaction ledger.
   - Built-in fault injection controls allowing one-click outage simulation to demo real-time failover.

---

## 🚀 Quick Start

### 1. Run the Router Server
```powershell
cd C:\Users\PC\Downloads\empirecodes_edit_now\empireswitch
python app.py
```
Server boots at: **`http://127.0.0.1:8088`**

### 2. View Live Telemetry Dashboard
Open your browser and navigate to:
👉 **[http://127.0.0.1:8088](http://127.0.0.1:8088)**

### 3. Run Automated Failover Stress Simulation
In a second terminal, execute the fault-injection script:
```powershell
python simulate_traffic.py
```
Watch Paystack get tripped, traffic seamlessly failover to Flutterwave in real-time, and the circuit automatically heal!

---

## 📡 API Specification

### 1. Initiate Smart-Routed Charge
`POST /api/v1/charge`
```json
{
  "amount": 7500.00,
  "currency": "NGN",
  "customer_email": "client@empirecodes.com.ng",
  "customer_name": "Anthony Matthew",
  "preferred_gateway": "paystack"
}
```

**Response:**
```json
{
  "success": true,
  "status": "success",
  "message": "Charge routed successfully through PAYSTACK",
  "reference": "EMP-SW-20261105-8F3A29B1",
  "gateway_used": "paystack",
  "authorization_url": "https://checkout.paystack.com/EMP-SW-20261105-8F3A29B1",
  "amount": 7500.0,
  "currency": "NGN",
  "latency_ms": 114.2,
  "failover_occurred": false,
  "attempted_gateways": ["paystack"]
}
```

### 2. Gateway Health Telemetry
`GET /api/v1/health`
Returns real-time QoS health scores, circuit breaker states, and rolling latency metrics for all configured adapters.

### 3. Simulate Provider Outage (Demo Hook)
`POST /api/v1/simulate/outage`
```json
{
  "gateway": "paystack",
  "outage": true
}
```

---

## 👨‍💻 Engineered By

**Anthony Oluwaseun Matthew**  
*Lead Software Architect & FinTech Systems Engineer*  
- **Website:** [empirecodes.com.ng](https://empirecodes.com.ng)  
- **WhatsApp:** [+234 817 305 7810](https://wa.me/2348173057810)  
- **Call Line:** `+234 813 536 2561`  
- **Email:** `ceo@empirecodes.com.ng` | `matthew@empirecodes.com.ng`  
- **GitHub:** [@Empirezoom](https://github.com/Empirezoom)  
- **Degree:** B.Sc. in Mathematics (OAUSTECH)
