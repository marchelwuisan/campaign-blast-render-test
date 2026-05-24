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
│   │   ├── mapping.py               # Rule-based promo assignment (4 tiers)
│   │   └── schema.py                # PromoOffer, CustomerMessage dataclasses
│   │
│   ├── messaging/
│   │   ├── base.py                  # BaseSender abstract + SendResult
│   │   ├── constructor.py           # Template injection + validation
│   │   ├── mock_sender.py           # Console-print sender (POC default)
│   │   └── meta_sender.py           # Real Meta Cloud API sender (stub)
│   │
│   ├── database/
│   │   ├── db.py                    # SQLite connection, transaction, schema init
│   │   └── wa_blast.db              # SQLite database (2 tables)
│   │
│   └── api/
│       ├── main.py                  # FastAPI app entry point
│       └── routes/
│           ├── customers.py         # At-risk customer list
│           ├── blast.py             # Preview, send, logs
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

Reads the canonical CSV, validates required columns, deduplicates transactions by `(customer_id, purchase_date, order_value)`, parses dates and normalizes phone numbers to E.164, filters out customers newer than `MIN_CUSTOMER_AGE_DAYS`, and groups transactions under each `Customer`. Skipped records are written to `logs/skipped.jsonl` with a reason.

**Dataclasses:**
- `Customer` — `customer_id`, `customer_name`, `phone_number`, `created_at`, optional `gender`, `age`, plus a list of `Transaction` and computed properties (`last_purchase_date`, `total_spend`, `purchase_count`, `avg_order_value`, `top_category`)
- `Transaction` — single purchase record

---

## Stage 2 — Churn Analysis

**Files:** `engine/analyzer.py`, `engine/rfm.py`, `engine/rules.py`, `engine/ml.py`

**Function:** `analyze(customers, date_cutoff, ml_enabled) -> (at_risk, ml_stats, population_rfm_stats)`

Execution order:
1. **Rules first** — `evaluate_rules()` runs R01–R04 using fixed config thresholds
2. **RFM scoring** — percentile-based quintiles (1–5); `combined_score = R + F + M`
3. **ML predictor** (if `ml_enabled=true`) — scores only customers not already flagged by rules
4. **Signal combination** — produces ranked `AtRiskCustomer` list

**Rules:**
| ID | Name | Condition |
|---|---|---|
| R01 | Long Inactivity | No purchase in last `INACTIVITY_THRESHOLD_DAYS` (300) days |
| R02 | Frequency Drop | Current period count < `FREQUENCY_DROP_THRESHOLD` (0.5) × prior period |
| R03 | High-Value Lapse | Total spend ≥ `HIGH_VALUE_SPEND_THRESHOLD` (1500.0) + inactive > `HIGH_VALUE_LAPSE_DAYS` (30) |
| R04 | Single Purchase | Only 1 purchase ever recorded |

**`AtRiskCustomer` fields:** `customer_id`, `name`, `phone`, `risk_level` (HIGH/MEDIUM/LOW), `triggered_rules`, `rfm` (r/f/m/combined scores), `days_since_last_purchase`, `spend_summary` (total_spend, avg_order_value, top_category)

---

## Stage 3 — Promo Assignment

**Files:** `promo/mapping.py`, `promo/schema.py`

**Function:** `assign_promo(customer: AtRiskCustomer) -> PromoOffer`

4-tier static discount mapping:

| Condition | Promo Type | Code | Value |
|---|---|---|---|
| HIGH risk + spend ≥ 1500 | `discount_20` | `DISC20` | 20% off |
| HIGH risk | `discount_15` | `DISC15` | 15% off |
| MEDIUM risk | `discount_10` | `DISC10` | 10% off |
| LOW risk (default) | `discount_5` | `DISC5` | 5% off |

**`PromoOffer` fields:** `promo_type`, `promo_value`, `promo_code`, `expiry_days`

**`CustomerMessage`** — container that flows through Stages 3–5:
```python
@dataclass
class CustomerMessage:
    customer: AtRiskCustomer
    promo: PromoOffer
    message: Optional[WhatsAppMessage] = None  # filled by Stage 4
```

---

## Stage 4 — Message Construction

**Files:** `messaging/constructor.py`

**Functions:**
- `construct_message(customer, promo) -> WhatsAppMessage` — injects slots into re-engagement template, attaches to `CustomerMessage.message`
- `validate_message(msg) -> str | None` — non-empty slots + ≤ 1024 char body

**Template (POC, plain text):**
```
Hi {customer_name}, we miss you!
It's been a while since your last visit.
Here's a personal offer just for you: {offer}.
Use code {code_id} — valid for {days_valid} days.
See you soon!
```

**`WhatsAppMessage` fields:** `to`, `body`, `customer_id`, `promo_code`, `template_name`, `language_code`, `template_params`

---

## Stage 5 — Dispatch

**Files:** `messaging/base.py`, `messaging/mock_sender.py`

**Interface:** `BaseSender.send(message, customer_id, blast_id) -> SendResult`

`MockSender` prints the message preview to console and returns `SendResult(status="mocked")`. All DB persistence (blast_log, customer_blast_status) is handled by the API layer — the sender owns no DB logic.

`MetaSender` is a stub for the production Meta Cloud API swap — switching is a single config change (`SENDER_MODE=meta`).

---

## Database Layer

**File:** `database/db.py`

**Functions:**
- `get_connection()` — opens SQLite with WAL journaling, Row factory, foreign keys ON
- `transaction()` — context manager: commits on success, rolls back on exception
- `init_db()` — idempotent table creation (called on FastAPI startup)

**Tables (2):**

| Table | Purpose |
|---|---|
| `blast_log` | Every dispatch attempt — `blast_id`, `customer_id`, `phone`, `template_name`, `promo_code`, `status` (mocked/sent/failed), `error_code`, `error_reason`, `sent_at` |
| `customer_blast_status` | Cooldown + promo history — `customer_id` (PK), `last_sent_at`, `sent_promo_types` (comma-separated) |

---

## Stage 6 — API Layer (FastAPI)

**File:** `api/main.py` — mounts all routers, calls `init_db()` via lifespan

### `routes/blast.py`

**Helper functions (staged pipeline):**

| Function | Job |
|---|---|
| `_run_engine(ml_enabled)` | `load_customers` + `analyze` → returns `at_risk` list |
| `_apply_cooldown(at_risk)` | Queries `customer_blast_status`, drops customers within `BLAST_COOLDOWN_DAYS` |
| `assign_promos(at_risk)` | Calls `assign_promo()` per customer → returns `list[CustomerMessage]` |
| `construct_messages(cms)` | Calls `construct_message()` per item, fills `cm.message` |
| `validate_messages(cms)` | Pre-flight: checks slots + length → returns `{customer_id: error}` dict |
| `send_blast(cms, blast_id)` | `MockSender.send()` per message, writes `blast_log`, upserts `customer_blast_status` |

**Endpoints:**

- `POST /blast/preview` `{ ml_enabled }` — dry-run, returns message previews, no DB writes
- `POST /blast/send` `{ ml_enabled }` — full execution, aborts with 400 if pre-flight fails
- `GET /blast/logs` — paginated `blast_log` with `limit`, `offset`, `since`, `search`, `sort_by`, `order`

**`POST /blast/send` execution order:**
```
_run_engine → _apply_cooldown → assign_promos → construct_messages
→ validate_messages (abort if errors)
→ blast_id = uuid4()
→ send_blast: MockSender + INSERT blast_log + UPSERT customer_blast_status
→ return { blast_id, total, total_sent, total_failed, sender_mode }
```

### `routes/customers.py`

- `GET /customers/at-risk` — re-runs engine on every call; supports `risk_level`, `search`, `sort_by`, `order`, `limit`, `offset`

### `routes/analytics.py`

- `GET /analytics/blast/{blast_id}` — reads `blast_log` for the given blast: `total`, `total_sent`, `total_failed`, `promo_breakdown` (count per promo code), `failures` list

---

## Configuration Reference

All values live in `Pipeline/config.py`, overridable via `.env`.

| Param | Default | Used in |
|---|---|---|
| `DATA_PATH` | `Pipeline/transactions.csv` | Stage 1 |
| `DB_PATH` | `Pipeline/database/wa_blast.db` | Database |
| `MIN_CUSTOMER_AGE_DAYS` | 14 | Stage 1 |
| `RFM_WINDOW_DAYS` | 180 | Stage 2 |
| `RFM_AT_RISK_THRESHOLD` | 6 | Stage 2 |
| `INACTIVITY_THRESHOLD_DAYS` | 300 | R01 |
| `FREQUENCY_DROP_THRESHOLD` | 0.5 | R02 |
| `HIGH_VALUE_SPEND_THRESHOLD` | 1500.0 | R03 |
| `HIGH_VALUE_LAPSE_DAYS` | 30 | R03 |
| `THRESHOLD_DRIFT_TOLERANCE` | 0.1 | R03 |
| `MAX_BLAST_SIZE` | 500 | Stage 2 |
| `BLAST_COOLDOWN_DAYS` | 7 | Stage 3 |
| `PROMO_EXPIRY_DAYS` | 7 | Stage 3 |
| `SENDER_MODE` | `mock` | Stage 5 |
| `ML_MODEL_PATH` | `engine/models/temporal/churn_rf.pkl` | Stage 2 |
| `ML_CHURN_THRESHOLD` | 0.8 | Stage 2 |

---

## Runtime Flow (`POST /blast/send`)

```
Request { ml_enabled }
   │
   ▼
_run_engine()
   ├─ load_customers(DATA_PATH)         [Stage 1]
   └─ analyze(customers, cutoff)        [Stage 2: RFM + rules + ML]
   │
   ▼
_apply_cooldown(at_risk)
   └─ drop customers in customer_blast_status within BLAST_COOLDOWN_DAYS
   │
   ▼
assign_promos(at_risk) → list[CustomerMessage]
   └─ assign_promo(c) per customer      [Stage 3]
   │
   ▼
construct_messages(cms) → list[CustomerMessage]
   └─ construct_message(c, promo)       [Stage 4]
   │
   ▼
validate_messages(cms)
   └─ abort with HTTP 400 if any message fails
   │
   ▼
blast_id = uuid4()
   │
   ▼
send_blast(cms, blast_id)              [Stage 5]
   ├─ MockSender.send() per message
   ├─ INSERT blast_log (status=mocked/sent/failed)
   └─ UPSERT customer_blast_status (last_sent_at, sent_promo_types)
   │
   ▼
Response { blast_id, total, total_sent, total_failed, sender_mode }
```

---

## Current Status

**Implemented and verified:**
- Stages 1–5 pipeline (data → analysis → promo → message → dispatch)
- 2-table SQLite persistence (`blast_log`, `customer_blast_status`)
- 5 FastAPI endpoints across 3 route files
- Cooldown filtering (7-day default)
- Pre-flight validation with full-blast abort on failure
- 4-tier static promo discount codes (DISC5/10/15/20)

**Pending (pre-production):**
- `MetaSender` real implementation (Meta Cloud API)
- Stage 7 Streamlit dashboard (optional)
- Consent / opt-out mechanism (legal requirement before real use)
- API authentication (`API_KEY` middleware)
