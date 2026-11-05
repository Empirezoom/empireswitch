import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
import config

def get_connection():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Transactions Ledger
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reference TEXT UNIQUE NOT NULL,
        idempotency_key TEXT,
        amount REAL NOT NULL,
        currency TEXT NOT NULL,
        customer_email TEXT NOT NULL,
        gateway_used TEXT NOT NULL,
        status TEXT NOT NULL,
        authorization_url TEXT,
        failover_occurred INTEGER DEFAULT 0,
        attempted_gateways TEXT,
        latency_ms REAL NOT NULL,
        metadata_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # Fast Idempotency Index
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_idempotency ON transactions (idempotency_key);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_reference ON transactions (reference);")

    # Gateway Rolling Telemetry
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS gateway_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gateway TEXT NOT NULL,
        success INTEGER NOT NULL,
        latency_ms REAL NOT NULL,
        created_at TEXT NOT NULL
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_gateway ON gateway_metrics (gateway, created_at);")

    conn.commit()
    conn.close()

def check_idempotency(idempotency_key: str) -> Optional[Dict[str, Any]]:
    if not idempotency_key:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE idempotency_key = ? ORDER BY id DESC LIMIT 1;", (idempotency_key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def save_transaction(tx_data: Dict[str, Any]):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
    INSERT INTO transactions (
        reference, idempotency_key, amount, currency, customer_email,
        gateway_used, status, authorization_url, failover_occurred,
        attempted_gateways, latency_ms, metadata_json, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        tx_data["reference"],
        tx_data.get("idempotency_key"),
        tx_data["amount"],
        tx_data["currency"],
        tx_data["customer_email"],
        tx_data["gateway_used"],
        tx_data["status"],
        tx_data.get("authorization_url"),
        1 if tx_data.get("failover_occurred") else 0,
        json.dumps(tx_data.get("attempted_gateways", [])),
        tx_data["latency_ms"],
        json.dumps(tx_data.get("metadata", {})),
        now,
        now
    ))
    conn.commit()
    conn.close()

def get_transaction_by_reference(reference: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE reference = ?;", (reference,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def record_gateway_metric(gateway: str, success: bool, latency_ms: float):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
    INSERT INTO gateway_metrics (gateway, success, latency_ms, created_at)
    VALUES (?, ?, ?, ?);
    """, (gateway, 1 if success else 0, latency_ms, now))
    conn.commit()
    conn.close()

def get_gateway_rolling_stats(gateway: str, limit: int = 50) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT success, latency_ms FROM gateway_metrics 
    WHERE gateway = ? 
    ORDER BY id DESC LIMIT ?;
    """, (gateway, limit))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {
            "total": 0,
            "successes": 0,
            "failures": 0,
            "success_rate": 1.0,
            "avg_latency_ms": 120.0
        }

    total = len(rows)
    successes = sum(1 for r in rows if r["success"] == 1)
    failures = total - successes
    avg_latency = sum(r["latency_ms"] for r in rows) / total

    return {
        "total": total,
        "successes": successes,
        "failures": failures,
        "success_rate": round(successes / total, 3),
        "avg_latency_ms": round(avg_latency, 1)
    }

def get_recent_transactions(limit: int = 25) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, reference, amount, currency, customer_email, gateway_used, status, 
           failover_occurred, latency_ms, created_at 
    FROM transactions 
    ORDER BY id DESC LIMIT ?;
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# Initialize tables on import
init_db()
