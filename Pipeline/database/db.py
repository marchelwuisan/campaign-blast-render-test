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
                           
            CREATE TABLE IF NOT EXISTS promo_codes (
                code                TEXT PRIMARY KEY,
                customer_id         TEXT NOT NULL,
                promo_type          TEXT NOT NULL,
                discount_percent    REAL,
                issued_at           TIMESTAMP NOT NULL,
                expires_at          TIMESTAMP NOT NULL,
                status              TEXT NOT NULL DEFAULT 'pending', -- pending | active | redeemed | cancelled
                is_redeemed         INTEGER NOT NULL DEFAULT 0,
                redeemed_at         TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_promo_code_customer_id
                ON promo_codes (customer_id);
                           
            CREATE TABLE IF NOT EXISTS customer_blast_status (
                customer_id         TEXT PRIMARY KEY,
                last_sent_at        TIMESTAMP NOT NULL,
                sent_promo_types    TEXT NOT NULL DEFAULT '' -- comma-separated
            );
            CREATE TABLE IF NOT EXISTS at_risk_customers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                blast_id        TEXT NOT NULL,
                customer_id     TEXT NOT NULL,
                name            TEXT NOT NULL,
                phone           TEXT NOT NULL,
                risk_level      TEXT NOT NULL,
                days_inactive   INTEGER NOT NULL,
                r_score         INTEGER NOT NULL,
                f_score         INTEGER NOT NULL,
                m_score         INTEGER NOT NULL,
                combined_score  INTEGER NOT NULL,
                triggered_rules TEXT NOT NULL,
                scored_at       TIMESTAMP NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_at_risk_blast_id
                ON at_risk_customers (blast_id);

            CREATE TABLE IF NOT EXISTS promo_assignments (
                blast_id        TEXT NOT NULL,
                customer_id     TEXT NOT NULL,
                promo_type      TEXT NOT NULL,
                promo_value     TEXT NOT NULL,
                promo_code      TEXT NOT NULL,
                expiry_days     INTEGER NOT NULL,
                PRIMARY KEY (blast_id, customer_id)
            );
        """)
