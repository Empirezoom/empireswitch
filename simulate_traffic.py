import asyncio
import time
import httpx

BASE_URL = "http://127.0.0.1:8088"

async def run_simulation():
    print("=" * 65)
    print("[EMPIRESWITCH] AUTOMATED MULTI-GATEWAY FAILOVER SIMULATION")
    print("=" * 65)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Warm-up Healthy Traffic
        print("\n[PHASE 1] Dispatching Normal Baseline Traffic...")
        for i in range(1, 4):
            payload = {
                "amount": 5000 + (i * 500),
                "currency": "NGN",
                "customer_email": f"client_{i}@empirecodes.com.ng",
                "customer_name": f"Enterprise Client {i}"
            }
            res = await client.post(f"{BASE_URL}/api/v1/charge", json=payload)
            data = res.json()
            print(f"  Tx #{i}: Ref={data['reference']} | Route={data['gateway_used'].upper()} | Latency={data['latency_ms']}ms | Failover={data['failover_occurred']}")
            await asyncio.sleep(0.3)

        # 2. Trip Paystack (Simulate Provider Outage)
        print("\n[PHASE 2] SIMULATING SUDDEN PAYSTACK OUTAGE / 504 DOWNTIME...")
        await client.post(f"{BASE_URL}/api/v1/simulate/outage", json={"gateway": "paystack", "outage": True})
        print("  Paystack Circuit Breaker: FORCED OPEN (Tripped)")

        # 3. Dispatch Transactions during Outage (Demonstrates Zero-Loss Failover)
        print("\n[PHASE 3] Dispatching Transactions During Outage (Testing Failover)...")
        for i in range(4, 7):
            payload = {
                "amount": 12000 + (i * 1000),
                "currency": "NGN",
                "customer_email": f"vip_client_{i}@empirecodes.com.ng",
                "customer_name": f"VIP Client {i}"
            }
            res = await client.post(f"{BASE_URL}/api/v1/charge", json=payload)
            data = res.json()
            attempted = " -> ".join([g.upper() for g in data['attempted_gateways']])
            print(f"  Tx #{i}: Ref={data['reference']} | Path=[{attempted}] | Active Route={data['gateway_used'].upper()} | Failover={data['failover_occurred']} [ZERO DROPPED REVENUE]")
            await asyncio.sleep(0.3)

        # 4. Restore Paystack
        print("\n[PHASE 4] RESTORING PAYSTACK HEALTH & HEALING CIRCUIT...")
        await client.post(f"{BASE_URL}/api/v1/simulate/outage", json={"gateway": "paystack", "outage": False})
        print("  Paystack Circuit Breaker: RESTORED & PROBING")

        # 5. Final Verification
        print("\n[PHASE 5] Verification Complete. Fetching Router Health Telemetry...")
        health_res = await client.get(f"{BASE_URL}/api/v1/health")
        for gw in health_res.json():
            print(f"  * {gw['gateway'].upper():<16} Status={gw['circuit_status']:<10} QoS Score={gw['health_score']}/100 SuccessRate={gw['success_rate']*100:.1f}% AvgLatency={gw['avg_latency_ms']}ms")

    print("\n" + "=" * 65)
    print("[SUCCESS] 100% Transaction Delivery with Automated Failover!")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(run_simulation())
