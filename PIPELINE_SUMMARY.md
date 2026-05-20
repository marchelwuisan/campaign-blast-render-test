# WA-Blast Pipeline Summary

A snapshot of the **current, implemented state** of the WA-Blast pipeline. For design rationale and future-state spec, see `FLOW.md`.

---

## File Structure

```
WA-Blast/
├── Pipeline/
│   ├── config.py                    # All env vars and thresholds
│   ├── transactions.csv             # Dummy dataset
│   │
│   ├── data/
│   │   ├── loader.py                # CSV ingest + normalization
│   │   └── schema.py                # Customer, Transaction dataclasses
│   │
│   ├── engine/
│   │   ├── analyzer.py              # Orchestrates rfm + rules + ml → at-risk list
│   │   ├── rfm.py                   # RFM scoring (percentile quintiles)
│   │   ├── rules.py                 # R01–R04 churn rule triggers
│   │   ├── ml.py                    # ChurnPredictor (Random Forest loader)
│   │   ├── models/                  # Trained model artifacts (.pkl + metadata)
│   │   └── training/                # Offline training scripts (profile + temporal)
│   │
│   ├── promo/
│   │   ├── mapping.py               # Rule-based promo assignment
│   │   └── schema.py                # PromoOffer dataclass
│   │
│   ├── messaging/
│   │   ├── base.py                  # BaseSender abstract + SendResult
│   │   ├── constructor.py           # Template injection + validation
│   │   ├── mock_sender.py           # Console-print sender (POC default)
│   │   └── meta_sender.py           # Real Meta Cloud API sender (stub)
│   │
│   ├── database/
│   │   ├── db.py                    # SQLite connection, transaction, schema init
│   │   └── wa_blast.db              # SQLite database (5 tables)
│   │
│   └── api/
│       ├── main.py                  # FastAPI app entry point
│       └── routes/
│           ├── customers.py         # At-risk list, per-customer promo
│           ├── blast.py             # Preview, send, logs
│           ├── promo_codes.py       # Validate, redeem
│           └── analytics.py         # Per-blast metrics
│
├── test_pipeline.py                 # Standalone test runner for Stages 1–5
├── FLOW.md                          # Full design + future-state spec
└── PIPELINE_SUMMARY.md              # This document
```

---

## Stage 1 — Data Ingestion

**Files:** `data/loader.py`, `data/schema.py`

**Function:** `load_customers(csv_path) -> (list[Customer], date_cutoff)`

Reads the canonical CSV, validates required columns, deduplicates transactions by `(customer_id, purchase_date, order_value)`, parses dates and normalizes phone numbers to E.164, filters out customers younger than `MIN_CUSTOMER_AGE_DAYS`, and groups transactions under each `Customer`. Skipped records are written to `logs/skipped.jsonl` with a reason.

**Dataclasses:**
- `Customer` — `customer_id`, `customer_name`, `phone_number`, `created_at`, optional `gender`, `age`, plus a list of `Transaction` and computed properties (`last_purchase_date`, `total_spend`, `purchase_count`, `avg_order_value`, `top_category`)
- `Transaction` — single purchase record

---

## Stage 2 — Churn Analysis

**Files:** `engine/analyzer.py`, `engine/rfm.py`, `engine/rules.py`, `engine/ml.py`

**Function:** `analyze(customers, date_cutoff, ml_enabled) -> (at_risk, ml_stats, population_rfm_stats)`

Execution order (runtime-optimized):
1. **Rules first** — `evaluate_rules()` runs R01–R04 using fixed config thresholds. Customers caught by rules are confirmed HIGH risk.
2. **RFM scoring** — percentile-based quintiles (1–5) on R/F/M dimensions; `combined_score = R + F + M`.
3. **ML predictor** (if `ml_enabled=true`) — scores only customers **not** already flagged by rules.
4. **Signal combination** — produces `AtRiskCustomer` objects with `risk_level` (HIGH / MEDIUM / LOW), `triggered_rules`, `days_since_last_purchase`, `rfm` scores, `spend_summary`.

**Rules:**
| ID | Name | Condition |
|---|---|---|
| R01 | Long Inactivity | No purchase in last `INACTIVITY_THRESHOLD_DAYS` |
| R02 | Frequency Drop | Current period count < `FREQUENCY_DROP_THRESHOLD` × prior period count |
| R03 | High-Value Lapse | Total spend ≥ `HIGH_VALUE_SPEND_THRESHOLD` + inactive > `HIGH_VALUE_LAPSE_DAYS` |
| R04 | Single Purchase | Only 1 purchase ever recorded |

---

## Stage 3 — Promo Assignment

**Files:** `promo/mapping.py`, `promo/schema.py`

**Function:** `assign_promo(customer: AtRiskCustomer) -> PromoOffer`

Deterministic rule-based mapping table:

| Condition | Promo Type | Code (template) |
|---|---|---|
| HIGH risk + spend ≥ threshold | `discount_30` | `BACK30` |
| HIGH risk + regular spend | `discount_20` | `BACK20` |
| MEDIUM risk + R02 fired | `ship_discount_15` | `SHIP15` |
| MEDIUM risk + R04 fired | `bogo` | `BOGO1` |
| LOW risk (default) | `points_2x` | `POINTS2X` |

The template code (`BACK30` etc.) identifies the promo *type*. The actual unique per-customer code (`WA-XXXXXX`) is generated downstream in the API layer when the blast is dispatched.

---

## Stage 4 — Message Construction

**Files:** `messaging/constructor.py`

**Functions:**
- `construct_message(customer, promo) -> WhatsAppMessage` — injects slots into the re-engagement template
- `validate_message(msg) -> str | None` — returns error string or `None`

**Template (POC, plain text):**
```
Hi {customer_name}, we miss you!
It's been a while since your last visit.
Here's a personal offer just for you: {offer}.
Use code {code_id} — valid for {days_valid} days.
See you soon!
```

`WhatsAppMessage` carries `to`, `body`, `customer_id`, `promo_code`, `template_name`, `language_code`, `template_params`. Validation enforces non-empty slots and ≤1024 char body length.

---

## Stage 5 — Dispatch

**Files:** `messaging/base.py`, `messaging/mock_sender.py`, `messaging/meta_sender.py` (stub)

**Interface:** `BaseSender.send(message, customer_id, blast_id) -> SendResult`

`MockSender` prints message preview to console and returns `SendResult(status="mocked", ...)`. It owns **no DB logic** — `blast_log` persistence is handled by the API layer so DB transactions can be coordinated atomically.

`MetaSender` exists as a placeholder for the production swap. Switching senders is a single config change (`SENDER_MODE=meta`).

---

## Database Layer

**File:** `database/db.py`

**Functions:**
- `get_connection()` — opens SQLite connection with `WAL` journaling, `Row` factory, foreign keys ON, creates DB file if missing
- `transaction()` — context manager: commits on success, rolls back on exception, always closes
- `init_db()` — creates all tables idempotently (called once on FastAPI startup)

**Tables:**

| Table | Purpose |
|---|---|
| `blast_log` | Every dispatch attempt — `blast_id`, `customer_id`, `phone`, `template_name`, `promo_code`, `status` (pending → mocked/sent/failed), `sent_at` |
| `promo_codes` | Unique `WA-XXXXXX` codes — `customer_id`, `promo_type`, `issued_at`, `expires_at`, `status`, `is_redeemed`, `redeemed_at` |
| `customer_blast_status` | Cooldown + promo dedup — `customer_id` (PK), `last_sent_at`, `sent_promo_types` (comma-separated) |
| `at_risk_customers` | Snapshot of scored at-risk list per blast run — full RFM, risk level, triggered rules |
| `promo_assignments` | Promo assigned per customer per blast |

`at_risk_customers` and `promo_assignments` are read-only outputs of a blast — `GET /customers/*` endpoints query these directly instead of re-running the pipeline.

---

## Stage 6 — API Layer (FastAPI)

**File:** `api/main.py` — mounts all routers, calls `init_db()` via `lifespan`

### `routes/customers.py`
- `GET /customers/at-risk` — paginated at-risk list from `at_risk_customers` (latest blast). Supports `risk_level`, `search`, `sort_by`, `order`, `limit`, `offset`.
- `GET /customers/{id}/promo` — returns the customer's promo from `promo_assignments` (latest blast).

### `routes/blast.py`
- `POST /blast/preview` — dry-run, returns what would be sent; no DB writes.
- `POST /blast/send` — full execution:
  1. Run pipeline (`_run_pipeline`)
  2. Apply cooldown filter (`_apply_cooldown` — skips customers within `BLAST_COOLDOWN_DAYS`)
  3. Pre-flight validation — abort entire blast if any message fails
  4. **First transaction:** insert `at_risk_customers`, `promo_assignments`, `promo_codes` (with unique `WA-XXXXXX` codes), `blast_log` (as `pending`)
  5. **Send loop:** dispatch each message, update `blast_log` status, upsert `customer_blast_status`
- `GET /blast/logs` — paginated blast history with `since`, `search`, `sort_by`, `order`.

### `routes/promo_codes.py`
- `GET /promo-codes/validate/{code}` — checks existence, lifecycle, expiry. Returns discount details or rejection reason (`not_found`, `pending`, `cancelled`, `already_redeemed`, `expired`).
- `POST /promo-codes/redeem/{code}` — marks code as redeemed if `status=active` and not expired.

### `routes/analytics.py`
- `GET /analytics/blast/{blast_id}` — metrics for a blast run: total sent/failed, redemption rate, avg time to redeem, list of failures with reasons.

---

## Configuration

All knobs live in `Pipeline/config.py`, overridable via `.env`. Key values:

| Param | Default | Used in |
|---|---|---|
| `DATA_PATH` | `Pipeline/transactions.csv` | Stage 1 |
| `DB_PATH` | `Pipeline/database/wa_blast.db` | Database layer |
| `MIN_CUSTOMER_AGE_DAYS` | 14 | Stage 1 |
| `RFM_WINDOW_DAYS` | 180 | Stage 2 |
| `RFM_AT_RISK_THRESHOLD` | 6 | Stage 2 |
| `INACTIVITY_THRESHOLD_DAYS` | 300 | R01 |
| `FREQUENCY_DROP_THRESHOLD` | 0.5 | R02 |
| `HIGH_VALUE_SPEND_THRESHOLD` | 1500.0 | R03 |
| `HIGH_VALUE_LAPSE_DAYS` | 30 | R03 |
| `MAX_BLAST_SIZE` | 10000 | Stage 5 |
| `BLAST_COOLDOWN_DAYS` | 7 | Stage 3 |
| `PROMO_EXPIRY_DAYS` | 7 | Stage 3 |
| `SENDER_MODE` | `mock` | Stage 5 |
| `ML_MODEL_PATH` | `engine/models/temporal/churn_rf.pkl` | Stage 2 |
| `ML_CHURN_THRESHOLD` | 0.8 | Stage 2 |

---

## Runtime Flow (`POST /blast/send`)

```
Request → _run_pipeline()
              ├─ load_customers(DATA_PATH)              [Stage 1]
              ├─ analyze(customers, cutoff, ml_enabled) [Stage 2]
              ├─ assign_promo(c) for c in at_risk       [Stage 3]
              └─ construct_message(c, promo)            [Stage 4]
       ↓
       _apply_cooldown(at_risk)
              └─ query customer_blast_status, drop on-cooldown
       ↓
       validate_message() pre-flight
              └─ abort blast with 400 if any failure
       ↓
       Transaction 1 — DB state writes
              ├─ INSERT at_risk_customers
              ├─ INSERT promo_assignments
              ├─ INSERT OR IGNORE promo_codes (WA-XXXXXX, status=active)
              └─ INSERT blast_log (status=pending)
       ↓
       Send loop — per customer
              ├─ MockSender.send() → SendResult         [Stage 5]
              ├─ UPDATE blast_log SET status
              └─ UPSERT customer_blast_status
       ↓
       Response { blast_id, total, sent, failed, sender_mode }
```

---

## Current Status

**Implemented and verified:**
- All 5 pipeline stages (data → analysis → promo → message → dispatch)
- Full SQLite persistence (5 tables)
- Full FastAPI surface (8 endpoints)
- Cooldown filtering via `customer_blast_status`
- Unique per-customer promo codes
- Pre-flight validation with full-blast abort

**Pending:**
- Stage 3 promo deduplication via `sent_promo_types` (avoid repeating promo types per customer)
- `MetaSender` real implementation
- Stage 7 Streamlit dashboard (optional)
- Consent / opt-out mechanism (deferred — required before production)
- API authentication
