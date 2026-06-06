import sqlite3
from contextlib import contextmanager
from pathlib import Path

from Pipeline.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with transaction() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS blast_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                blast_id        TEXT NOT NULL,
                customer_id     TEXT NOT NULL,
                phone           TEXT NOT NULL,
                template_name   TEXT NOT NULL,
                promo_code      TEXT,
                status          TEXT NOT NULL,  -- sent | mocked | failed 
                error_code      TEXT,
                error_reason    TEXT,
                sent_at         TIMESTAMP NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_blast_log_blast_id
                ON blast_log (blast_id);
            CREATE INDEX IF NOT EXISTS idx_blast_log_customer_id
                ON blast_log (customer_id);
                           
            CREATE TABLE IF NOT EXISTS customer (
                customer_id         TEXT PRIMARY KEY,
                last_sent_at        TIMESTAMP NOT NULL,
                sent_promo_types    TEXT NOT NULL DEFAULT '', -- comma-separated
                phone_number        TEXT,
                is_unsubscribe      INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS analyzed_customers (
                customer_id              TEXT PRIMARY KEY,
                name                     TEXT,
                phone                    TEXT,
                gender                   TEXT,
                age                      INTEGER,
                risk_level               TEXT,
                rfm_r_score              INTEGER,
                rfm_f_score              INTEGER,
                rfm_m_score              INTEGER,
                rfm_combined_score       INTEGER,
                days_since_last_purchase INTEGER,
                total_spend              REAL,
                avg_order_value          REAL,
                top_category             TEXT,
                triggered_rules          TEXT,
                churn_probability        REAL,
                ml_enabled               INTEGER NOT NULL DEFAULT 0,
                analyzed_at              TIMESTAMP NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_analyzed_risk
                ON analyzed_customers (risk_level);
        """)
