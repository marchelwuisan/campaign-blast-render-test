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
        # Drop a pre-existing orphaned promo_codes table that predates this
        # schema (the old version lacked the phone column). It was never
        # populated by code, so dropping is safe.
        promo_cols = [r[1] for r in conn.execute("PRAGMA table_info(promo_codes)").fetchall()]
        if promo_cols and "phone" not in promo_cols:
            conn.execute("DROP TABLE promo_codes")

        blast_cols = [r[1] for r in conn.execute("PRAGMA table_info(blast_log)").fetchall()]
        if blast_cols and "mode" not in blast_cols:
            conn.execute("ALTER TABLE blast_log ADD COLUMN mode TEXT")

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
                mode            TEXT,           -- meta | mock
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
                analyzed_at              TIMESTAMP NOT NULL,
                promo_type               TEXT,
                promo_code               TEXT,
                promo_value              TEXT,
                promo_expiry_days        INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_analyzed_risk
                ON analyzed_customers (risk_level);

            CREATE TABLE IF NOT EXISTS templates (
                id                  TEXT PRIMARY KEY,   -- Meta template id
                name                TEXT NOT NULL,
                status              TEXT,               -- APPROVED | PENDING | REJECTED | ...
                language            TEXT,
                category            TEXT,
                parameter_format    TEXT,               -- NAMED | POSITIONAL
                raw                 TEXT NOT NULL,      -- full Meta template object as JSON
                synced_at           TIMESTAMP NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_templates_name
                ON templates (name);

            CREATE TABLE IF NOT EXISTS promo_codes (
                code            TEXT PRIMARY KEY,   -- unique per-issuance code, e.g. WA-X7K2AB
                customer_id     TEXT NOT NULL,
                name            TEXT,
                phone           TEXT,
                promo_type      TEXT,               -- generic promo code, e.g. DISC20
                promo_value     TEXT,               -- human-readable, e.g. "20% off"
                status          TEXT NOT NULL,      -- pending | active | redeemed | cancelled
                blast_id        TEXT,
                issued_at       TIMESTAMP NOT NULL,
                expires_at      TIMESTAMP,
                redeemed_at     TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_promo_codes_phone
                ON promo_codes (phone);

            CREATE TABLE IF NOT EXISTS incoming_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sender      TEXT NOT NULL,
                content     TEXT,
                received_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS outgoing_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient   TEXT NOT NULL,
                sent_at     TEXT NOT NULL
            );
        """)

        # Migrate caches created before parameter_format existed.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(templates)").fetchall()]
        if "parameter_format" not in cols:
            conn.execute("ALTER TABLE templates ADD COLUMN parameter_format TEXT")
