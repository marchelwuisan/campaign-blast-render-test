import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# --- Paths ---
DATA_PATH = os.getenv("DATA_PATH", str(BASE_DIR / "transactions.csv"))
LOG_DIR = os.getenv("LOG_DIR", str(BASE_DIR / "logs"))
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "database" / "wa_blast.db"))

# --- Ingest ---
MIN_CUSTOMER_AGE_DAYS = int(os.getenv("MIN_CUSTOMER_AGE_DAYS", 14))
WA_REGISTRATION_CHECK = os.getenv("WA_REGISTRATION_CHECK", "false").lower() == "true"

# --- RFM ---
RFM_WINDOW_DAYS = int(os.getenv("RFM_WINDOW_DAYS", 180))
RFM_AT_RISK_THRESHOLD = int(os.getenv("RFM_AT_RISK_THRESHOLD", 6))
INACTIVITY_THRESHOLD_DAYS = int(os.getenv("INACTIVITY_THRESHOLD_DAYS", 300))
FREQUENCY_DROP_THRESHOLD = float(os.getenv("FREQUENCY_DROP_THRESHOLD", 0.5))
HIGH_VALUE_SPEND_THRESHOLD = float(os.getenv("HIGH_VALUE_SPEND_THRESHOLD", 1500.0))
THRESHOLD_DRIFT_TOLERANCE = float(os.getenv("THRESHOLD_DRIFT_TOLERANCE", 0.1))
SCORING_VERSION = os.getenv("SCORING_VERSION", "v1.0")
HIGH_VALUE_LAPSE_DAYS = int(os.getenv("HIGH_VALUE_LAPSE_DAYS", 30))

# --- Blast ---
MAX_BLAST_SIZE = int(os.getenv("MAX_BLAST_SIZE", 500))
BLAST_COOLDOWN_DAYS = int(os.getenv("BLAST_COOLDOWN_DAYS", 7))
BLAST_RATE_LIMIT = int(os.getenv("BLAST_RATE_LIMIT", 10))
RATE_LIMIT_WAIT_SECONDS = int(os.getenv("RATE_LIMIT_WAIT_SECONDS", 60))
PROMO_EXPIRY_DAYS = int(os.getenv("PROMO_EXPIRY_DAYS", 7))
MAX_DISCOUNT_PERCENT = int(os.getenv("MAX_DISCOUNT_PERCENT", 30))

# --- Sender ---
SENDER_MODE = os.getenv("SENDER_MODE", "mock")  # "mock" | "meta"
WA_ACCESS_TOKEN = os.getenv("WA_ACCESS_TOKEN", "")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
WA_BUSINESS_ACCOUNT_ID = os.getenv("WA_BUSINESS_ACCOUNT_ID", "")  # WABA ID — for template CRUD
WA_GRAPH_API_VERSION = os.getenv("WA_GRAPH_API_VERSION", "v25.0")

# --- ML ---
ML_MODEL_PATH = os.getenv(
    "ML_MODEL_PATH", str(BASE_DIR / "engine/models/temporal/churn_rf.pkl")
)
ML_CHURN_THRESHOLD = float(os.getenv("ML_CHURN_THRESHOLD", 0.8))

# --- AI ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
