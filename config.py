import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Server Configuration
SERVER_HOST = os.getenv("EMPIRESWITCH_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("EMPIRESWITCH_PORT", "8088"))
APP_ENV = os.getenv("APP_ENV", "development")

# Database Path
DB_PATH = BASE_DIR / "empireswitch.db"

# Gateway Credentials (Defaults to test/sandbox)
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "sk_test_mock_paystack_secret_key_12345")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "pk_test_mock_paystack_public_key_12345")

FLUTTERWAVE_SECRET_KEY = os.getenv("FLUTTERWAVE_SECRET_KEY", "FLWSECK_TEST-mock_secret_key_12345")
FLUTTERWAVE_PUBLIC_KEY = os.getenv("FLUTTERWAVE_PUBLIC_KEY", "FLWPUBK_TEST-mock_public_key_12345")
FLUTTERWAVE_ENCRYPTION_KEY = os.getenv("FLUTTERWAVE_ENCRYPTION_KEY", "FLWSECK_TEST_ENC_KEY")

# Circuit Breaker & Routing Thresholds
FAILURE_RATE_THRESHOLD = float(os.getenv("FAILURE_RATE_THRESHOLD", "0.20"))  # 20% failure rate trips breaker
LATENCY_THRESHOLD_MS = int(os.getenv("LATENCY_THRESHOLD_MS", "2500"))       # 2.5s latency trips breaker
MIN_SAMPLES_FOR_EVAL = 5                                                     # Minimum 5 requests to evaluate QoS
CIRCUIT_RECOVERY_TIME_SEC = 30                                               # 30 seconds before half-open probe

# Default Gateway Priority Order
DEFAULT_PRIMARY_GATEWAY = "paystack"
DEFAULT_SECONDARY_GATEWAY = "flutterwave"
DEFAULT_FALLBACK_GATEWAY = "interswitch_sim"
