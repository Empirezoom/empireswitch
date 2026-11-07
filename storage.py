import sqlite3
import json
import uuid
import hashlib
import secrets
from datetime import datetime
from typing import Optional, Dict, Any, List
import config

def get_connection():
    conn = sqlite3.connect(str(config.DB_PATH), timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Merchants Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS merchants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        merchant_id TEXT UNIQUE NOT NULL,
        business_name TEXT NOT NULL,
        contact_email TEXT NOT NULL,
        api_public_key TEXT UNIQUE NOT NULL,
        api_secret_key TEXT UNIQUE NOT NULL,
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL
    );
    """)

    # 2. Merchant Gateway Credentials Table (Encrypted / Secret storage)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS merchant_gateways (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        merchant_id TEXT NOT NULL,
        gateway_name TEXT NOT NULL,
        public_key TEXT,
        secret_key TEXT,
        is_active INTEGER DEFAULT 1,
        priority INTEGER DEFAULT 1,
        updated_at TEXT NOT NULL,
        UNIQUE(merchant_id, gateway_name)
    );
    """)

    # 3. Transactions Ledger with Multi-Channel Support
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reference TEXT UNIQUE NOT NULL,
        merchant_id TEXT NOT NULL,
        idempotency_key TEXT,
        amount REAL NOT NULL,
        currency TEXT NOT NULL,
        customer_email TEXT NOT NULL,
        customer_name TEXT,
        channel TEXT NOT NULL, -- 'card', 'bank_transfer', 'ussd'
        gateway_used TEXT NOT NULL,
        status TEXT NOT NULL, -- 'pending', 'success', 'failed'
        authorization_url TEXT,
        virtual_bank_name TEXT,
        virtual_account_number TEXT,
        virtual_account_expires_at TEXT,
        ussd_code TEXT,
        failover_occurred INTEGER DEFAULT 0,
        attempted_gateways TEXT,
        latency_ms REAL NOT NULL,
        metadata_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # Check and migrate columns on existing database
    cursor.execute("PRAGMA table_info(transactions);")
    existing_cols = {row["name"] for row in cursor.fetchall()}
    
    columns_to_add = [
        ("merchant_id", "TEXT DEFAULT 'mer_empirecodes_master'"),
        ("customer_name", "TEXT DEFAULT 'Valued Client'"),
        ("channel", "TEXT DEFAULT 'card'"),
        ("virtual_bank_name", "TEXT"),
        ("virtual_account_number", "TEXT"),
        ("virtual_account_expires_at", "TEXT"),
        ("ussd_code", "TEXT")
    ]
    for col_name, col_def in columns_to_add:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE transactions ADD COLUMN {col_name} {col_def};")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_idempotency ON transactions (idempotency_key);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_reference ON transactions (reference);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_merchant ON transactions (merchant_id);")

    # 4. Gateway Rolling Telemetry
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

    # 5. Webhook Audit Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS webhook_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gateway TEXT NOT NULL,
        event_type TEXT,
        reference TEXT,
        payload_json TEXT NOT NULL,
        verified INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    """)

    conn.commit()
    conn.close()
    
    # Ensure Default Master Merchant (EmpireCodes) exists
    ensure_default_merchant()

def ensure_default_merchant():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM merchants WHERE merchant_id = 'mer_empirecodes_master' LIMIT 1;")
    row = cursor.fetchone()
    now = datetime.utcnow().isoformat()
    if not row:
        cursor.execute("""
        INSERT INTO merchants (merchant_id, business_name, contact_email, api_public_key, api_secret_key, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (
            "mer_empirecodes_master",
            "EmpireCodes Technologies",
            "matthew@empirecodes.com.ng",
            "emp_pub_live_799ab817337057988231",
            "emp_sec_live_7c5b78cfd3aa71fd436f",
            "active",
            now
        ))

    # Synchronize Paystack credentials if present and live
    if config.PAYSTACK_SECRET_KEY and not config.PAYSTACK_SECRET_KEY.startswith("sk_test_mock"):
        cursor.execute("""
        INSERT INTO merchant_gateways (merchant_id, gateway_name, public_key, secret_key, is_active, priority, updated_at)
        VALUES (?, ?, ?, ?, 1, 1, ?)
        ON CONFLICT(merchant_id, gateway_name) DO UPDATE SET
            public_key = excluded.public_key,
            secret_key = excluded.secret_key,
            is_active = 1,
            priority = 1,
            updated_at = excluded.updated_at;
        """, ("mer_empirecodes_master", "paystack", config.PAYSTACK_PUBLIC_KEY, config.PAYSTACK_SECRET_KEY, now))

    # Disable any mock credentials in the database
    cursor.execute("""
    UPDATE merchant_gateways 
    SET is_active = 0 
    WHERE secret_key LIKE '%mock%' OR secret_key = '' OR secret_key IS NULL;
    """)

    conn.commit()
    conn.close()

def get_merchant_by_public_key(public_key: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM merchants WHERE api_public_key = ? AND status = 'active' LIMIT 1;", (public_key,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_merchant_gateways(merchant_id: str) -> Dict[str, Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT gateway_name, public_key, secret_key, is_active, priority 
    FROM merchant_gateways 
    WHERE merchant_id = ? AND is_active = 1 
      AND secret_key IS NOT NULL AND secret_key != '' AND secret_key NOT LIKE '%mock%'
    ORDER BY priority ASC;
    """, (merchant_id,))
    rows = cursor.fetchall()
    conn.close()
    return {r["gateway_name"]: dict(r) for r in rows}

def save_merchant_gateway(merchant_id: str, gateway: str, pub_key: str, sec_key: str, priority: int = 1):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    is_active = 1 if sec_key and not "mock" in sec_key.lower() else 0
    cursor.execute("""
    INSERT INTO merchant_gateways (merchant_id, gateway_name, public_key, secret_key, is_active, priority, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(merchant_id, gateway_name) DO UPDATE SET
        public_key = excluded.public_key,
        secret_key = excluded.secret_key,
        is_active = excluded.is_active,
        priority = excluded.priority,
        updated_at = excluded.updated_at;
    """, (merchant_id, gateway, pub_key, sec_key, is_active, priority, now))
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
    return dict(row) if row else None

def save_transaction(tx_data: Dict[str, Any]):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
    INSERT INTO transactions (
        reference, merchant_id, idempotency_key, amount, currency, customer_email, customer_name,
        channel, gateway_used, status, authorization_url, virtual_bank_name, virtual_account_number,
        virtual_account_expires_at, ussd_code, failover_occurred, attempted_gateways, latency_ms,
        metadata_json, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        tx_data["reference"],
        tx_data.get("merchant_id", "mer_empirecodes_master"),
        tx_data.get("idempotency_key"),
        tx_data["amount"],
        tx_data["currency"],
        tx_data["customer_email"],
        tx_data.get("customer_name"),
        tx_data.get("channel", "card"),
        tx_data["gateway_used"],
        tx_data["status"],
        tx_data.get("authorization_url"),
        tx_data.get("virtual_bank_name"),
        tx_data.get("virtual_account_number"),
        tx_data.get("virtual_account_expires_at"),
        tx_data.get("ussd_code"),
        1 if tx_data.get("failover_occurred") else 0,
        json.dumps(tx_data.get("attempted_gateways", [])),
        tx_data["latency_ms"],
        json.dumps(tx_data.get("metadata", {})),
        now,
        now
    ))
    conn.commit()
    conn.close()

def update_transaction_status(reference: str, status: str, gateway_response: str = None) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
    UPDATE transactions 
    SET status = ?, updated_at = ? 
    WHERE reference = ?;
    """, (status, now, reference))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated

def get_transaction_by_reference(reference: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE reference = ?;", (reference,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

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

def get_recent_transactions(limit: int = 30) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, reference, merchant_id, amount, currency, customer_email, channel, gateway_used, 
           status, authorization_url, virtual_bank_name, virtual_account_number, ussd_code,
           failover_occurred, latency_ms, created_at 
    FROM transactions 
    ORDER BY id DESC LIMIT ?;
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def log_webhook_event(gateway: str, event_type: str, reference: str, payload: dict, verified: bool):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
    INSERT INTO webhook_logs (gateway, event_type, reference, payload_json, verified, created_at)
    VALUES (?, ?, ?, ?, ?, ?);
    """, (gateway, event_type, reference, json.dumps(payload), 1 if verified else 0, now))
    conn.commit()
    conn.close()

# Initialize tables
init_db()
