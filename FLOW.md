# WA-Blast: Project Flow & Context Document

---

## Purpose of This Document

This document is the single source of truth for the WA-Blast project. It is written to be fully self-contained — any developer or AI assistant reading this file should be able to understand the project's goals, decisions, current state, known gaps, and how all components fit together, without needing any additional context.

---

## Project Summary

**What it is:** A WhatsApp blast service for customer retention. It identifies customers who are at risk of churning, assigns them a personalized promo offer, and sends them a WhatsApp message to bring them back.

**Who it is for:** Internal business use — marketing or CRM teams trigger blasts against their customer base.

**Current phase:** Proof of concept (POC). We are using a publicly available dummy e-commerce dataset. No real customers, no real WhatsApp sending yet.

**Core goal:** Build and validate the full pipeline — data ingestion → churn analysis → promo assignment → message dispatch — before connecting real infrastructure.

---

## Key Decisions Already Made

These decisions are final and should not be re-proposed unless explicitly revisited.

| Decision | Choice | Reason |
|---|---|---|
| WhatsApp provider | Meta WhatsApp Cloud API | Official, free tier, no infra to maintain |
| Sending mode for POC | Mock sender (log to file) | No Meta credentials needed during development; real sender is a drop-in swap |
| Promo assignment | Rule-based mapping (not AI) | Deterministic, auditable, no external dependency; AI is a future add-on |
| AI integration | Decoupled — future enhancement only | Core pipeline must work without AI; AI will be an optional layer added later |
| API layer | FastAPI | Clean REST interface; dashboard and external tools call this |
| Dashboard | Streamlit (optional) | Thin consumer of FastAPI; can be skipped without affecting core logic |
| Message type | WhatsApp Template Messages only | Required by Meta for all outbound/proactive messages; free-form only allowed within 24h reply window |
| Blast direction | One-way outbound only | No reply handling in scope for POC |

---

## What Is In Scope (POC)

- Load and normalize a dummy customer + transaction dataset
- Score customers using RFM (Recency, Frequency, Monetary) analysis
- Apply rule-based churn triggers on top of RFM scores
- Produce a ranked list of at-risk customers
- Assign a promo offer to each at-risk customer using a rule-based mapping table
- Construct a WhatsApp-formatted message per customer
- Dispatch messages via mock sender (log to console) or real Meta Cloud API
- Expose the full pipeline via FastAPI endpoints
- Log all blast activity to SQLite database

## What Is Out of Scope (POC)

- Handling customer replies or inbound messages
- Meta template submission and approval workflow
- Real-time delivery status webhooks from Meta
- Customer opt-out / unsubscribe management *(known legal gap — must be addressed before production)*
- Multi-language message support
- A/B testing of promo types
- Automated scheduling / cron-based blast triggers *(manual trigger via `POST /blast/send` for POC)*
- AI-powered promo generation *(planned future feature)*
- Full automated feedback loop *(basic redemption metrics available via `GET /analytics/blast/{id}` — advanced automation is future)*

---

## System Architecture

### High-Level Flow

```
[Dataset] → [Ingest & Normalize] → [Churn Analysis] → [Promo Assignment] → [Message Construction] → [Dispatch] → [WhatsApp / Mock Log]
                                                                                                                          ↓
                                                                                                                   [Feedback Loop]
                                                                                                             (redemption & re-engagement)
```

### Component Map

```
wa-blast/
│
├── config.py                  # All env vars and thresholds
│
├── data/
│   ├── loader.py              # Load and normalize any dataset
│   ├── schema.py              # Customer, Transaction dataclasses
│   └── samples/               # Downloaded dummy datasets
│
├── engine/
│   ├── rfm.py                 # RFM scoring logic
│   ├── rules.py               # Churn rule triggers (pluggable)
│   ├── ml.py                  # ChurnPredictor — Random Forest model loader + scorer
│   ├── analyzer.py            # Orchestrates rfm + rules + ml → at-risk list
│   └── models/
│       └── churn_rf.pkl       # Trained Random Forest model artifact (generated offline)
│
├── promo/
│   ├── mapping.py             # Rule-based promo assignment table
│   └── schema.py              # PromoOffer dataclass
│
├── messaging/
│   ├── base.py                # Abstract BaseSender interface
│   ├── mock_sender.py         # Logs to file/console (POC)
│   ├── meta_sender.py         # Real Meta Cloud API (plug in later)
│   ├── constructor.py         # Builds WhatsAppMessage from customer + promo
│   └── templates/
│       └── reengagement.py    # Template v1 slot definitions
│
├── api/
│   ├── main.py                # FastAPI app entry point
│   └── routes/
│       ├── customers.py       # Customer-related endpoints
│       ├── blast.py           # Blast preview, send, logs endpoints
│       ├── promo_codes.py     # Validate and redeem promo code endpoints
│       └── analytics.py       # Blast feedback metrics endpoint
│
├── dashboard/
│   └── app.py                 # Streamlit UI (optional)
│
├── database/
│   └── wa_blast.db            # SQLite database — tables: promo_codes, blast_log, customer_blast_status
│
├── logs/
│   ├── failed_messages.jsonl  # Messages that failed pre-flight validation (missing slots, over limit)
│   └── skipped.jsonl          # Customers excluded at ingest (invalid phone, too new, etc.)
│
├── .env                       # Secrets (not committed)
├── .env.example               # Template for required env vars
└── requirements.txt
```

---

## Stage-by-Stage Flow

---

### Stage 1: Data Ingestion

**Goal:** Load raw customer and transaction data and normalize it into a consistent internal format.

**Input:**
- CSV or JSON file from a public e-commerce dataset
- Required fields: `customer_id`, `customer_name`, `phone_number`, `purchase_date`, `order_value`, `product_category`

**CSV Schema (canonical):**

The pipeline accepts only a single canonical CSV format. A template file is provided at `data/samples/template.csv`. Users must map their own data to this schema before loading.

| Column | Type | Required | Description |
|---|---|---|---|
| `customer_id` | string | ✅ | Unique customer identifier |
| `customer_name` | string | ✅ | Display name for message personalization |
| `phone_number` | string | ✅ | Customer phone number (any format — normalized at ingest) |
| `created_at` | date (YYYY-MM-DD) | ✅ | Customer registration date — used for age filtering |
| `purchase_date` | date (YYYY-MM-DD) | ✅ | Transaction date |
| `order_value` | float | ✅ | Transaction amount |
| `product_category` | string | ✅ | Category of purchased product |

**Process:**
1. Load raw CSV from file path
2. Validate all required columns are present — if any are missing, print a clear error listing the missing columns and exit immediately. Do not partially process.
3. Deduplicate transaction rows by `(customer_id, purchase_date, order_value)` — removes duplicate dataset entries before any analysis
4. Normalize data types: parse dates to `datetime`, phone numbers to E.164 format (`+628xxx`), numeric values to `float`
5. Validate phone numbers:
   - Skip customer if phone field is empty or cannot be parsed to E.164
   - If `WA_REGISTRATION_CHECK=true` and `SENDER_MODE=meta`: call Meta Contacts API (`GET /v18.0/{phone_number_id}/contacts`) to verify the number is WhatsApp-registered; skip if `status: invalid`
   - If `WA_REGISTRATION_CHECK=false` (default): skip the registration check entirely — assume all normalized numbers are valid WhatsApp numbers
   - **Business assumption:** If customers registered via WhatsApp OTP, their number is already proven active on WhatsApp. Keep `WA_REGISTRATION_CHECK=false` in this case — the API check is redundant. Confirm this assumption per deployment before disabling.
6. Filter out customers whose `created_at` is within `MIN_CUSTOMER_AGE_DAYS` of today — too new to score meaningfully
7. Log all skipped customers with skip reason to a separate `logs/skipped.jsonl`
8. Map to internal `Customer` and `Transaction` dataclasses

**Output:**
- List of `Customer` objects, each carrying their full normalized transaction history
- `logs/skipped.jsonl` recording any customers excluded at this stage with reason

**Known gaps / extension points:**
- No data quality score yet — future: flag low-confidence records
- Meta Contacts API check adds latency for large datasets — future: batch this call

---

### Stage 2: Churn Analysis Engine

**Goal:** Identify and rank customers who are at risk of churning.

**Execution order (runtime optimization):**

```
1. Rules run FIRST → uses HIGH_VALUE_SPEND_THRESHOLD (fixed config) for R03 — no population scan needed
2. RFM scoring → computed for all customers (R/F/M quintile breakpoints derived from population)
3. ML predictor (if ml_enabled) → only scores customers NOT already flagged by rules
4. Signal combination → assembles final at-risk list with risk levels
```

**Why this order:**
- **Rules first** — deterministic checks using a fixed config threshold for R03. No expensive population scan needed. Customers caught by rules are confirmed HIGH risk, so running them through ML afterward adds no value.
- **RFM second** — O(n log n) population sort for quintile breakpoints. Must run before ML since ML uses RFM scores as features.
- **ML last (for unflagged only)** — saves model inference cost at scale by skipping customers already determined HIGH risk by rules. All customers (including rule-flagged) are still used during offline ML training — only runtime inference skips the redundant scoring.

---

#### 2a. RFM Scoring

**What RFM is:** A behavioral scoring model that evaluates each customer on three dimensions:

| Dimension | Definition |
|---|---|
| **Recency (R)** | How many days since their last purchase |
| **Frequency (F)** | How many purchases they made in the analysis window |
| **Monetary (M)** | Total spend in the analysis window |

**Versioned scoring strategy:** The scoring logic is implemented as a `ScoringStrategy` interface. The active version is set via `SCORING_VERSION` config (default: `v1.0`). Upgrading to a new scoring algorithm is a drop-in replacement — no other stage is affected.

**Scoring v1.0 (current):**
- Method: percentile-based quintiles (1–5) within the active customer population
- Recency: customers in the bottom 20% of days-since-purchase get score 5 (most recent); top 20% get score 1
- Frequency and Monetary: higher value = higher score (standard direction)
- This approach handles skewed spend distributions better than equal-width bins
- Combined score = R + F + M (unweighted sum, range 3–15)

**At-risk RFM profile:** Combined score below `RFM_AT_RISK_THRESHOLD` (default: 8). Additionally, any customer with R score ≤ 2 is considered at-risk regardless of F and M scores.

---

#### 2b. ML Churn Predictor (Random Forest)

**What it does:** Takes each customer's RFM scores as input features and outputs a churn probability (0.0–1.0). Customers above `ML_CHURN_THRESHOLD` are flagged as at-risk independently of rule triggers.

**Toggle:** Controlled by `ml_enabled` flag per campaign (default: `false`). When `false`, this step is skipped entirely — RFM + rules run as the sole signal. When `true`, the loaded model scores customers **not already flagged by rules** (runtime optimization — see execution order above) and its output is combined with RFM + rules in Stage 2d.

**Algorithm:** Random Forest classifier (scikit-learn `RandomForestClassifier`).
- Features: `r_score`, `f_score`, `m_score`, `days_since_last_purchase`, `total_spend`, `avg_order_value`, `purchase_count`
- Target label: `churned` (bool) — derived from historical data: a customer is labeled `churned=true` if they had ≥ 2 purchases followed by inactivity exceeding `INACTIVITY_THRESHOLD_DAYS`
- Split: 80% train / 20% test
- Output: churn probability per customer

**Training:** Performed offline as a separate script (`engine/train.py`). The trained model is saved as `engine/models/churn_rf.pkl` and loaded at runtime by `engine/ml.py`. The pipeline never retrains at runtime.

**At runtime:** `ChurnPredictor.score(customer)` loads the saved model once at startup and returns a probability for each customer. Customers with `churn_probability >= ML_CHURN_THRESHOLD` (default: `0.6`) are passed to Stage 2d as ML-flagged at-risk.

**Fallback:** If the model file is missing and `ml_enabled=true`, the service raises a startup error and refuses to run — no silent degradation.

**Known gap:** The model requires labeled historical data to train. For the POC, labels are derived from the dummy dataset using the inactivity definition above. Model quality depends on how representative the dummy data is. Real training data improves accuracy significantly.

---

#### 2c. Rule-Based Triggers

Hard cutoff rules applied as a safety net before RFM/ML scoring. A customer flagged by any rule is included in the at-risk list regardless of their RFM score. Each rule is implemented as a standalone function in `engine/rules.py` and runs through the `evaluate_rules` orchestrator — adding, removing, or tuning a rule is a localized change.

| Rule ID | Name | Condition | Priority |
|---|---|---|---|
| R01 | Long Inactivity | No purchase in last `INACTIVITY_THRESHOLD_DAYS` days (default: 30) | High |
| R02 | Frequency Drop | Current period purchase count < `FREQUENCY_DROP_THRESHOLD` × prior period count (default: 0.5 = >50% drop) | Medium |
| R03 | High-Value Lapse | Customer's total spend ≥ `HIGH_VALUE_SPEND_THRESHOLD`, now inactive > 14 days | High |
| R04 | Single Purchase | Only 1 purchase ever recorded, no subsequent return | Medium |

**Period definition for R02:** Current period = last `RFM_WINDOW_DAYS / 2` days. Prior period = the `RFM_WINDOW_DAYS / 2` days before that. Changing the comparison window is a config change only (`RFM_WINDOW_DAYS`).

**Tunable threshold (R02):** `FREQUENCY_DROP_THRESHOLD` (default: 0.5) controls how steep a frequency drop must be to fire. Lower = stricter (fires on smaller drops), higher = more lenient.

**Hybrid threshold strategy (R03):** The high-value threshold uses a **fixed config + drift detection** pattern instead of pure dynamic computation. This avoids the cost of computing a population-wide 80th percentile on every run (which would force RFM to run before rules), while still self-correcting when the data distribution shifts significantly.

```
1. Run R03 with HIGH_VALUE_SPEND_THRESHOLD (fixed config)         ← fast path
2. Compute dynamic 80th-percentile threshold across population
3. drift = |dynamic - fixed| / fixed
4. If drift > THRESHOLD_DRIFT_TOLERANCE (default: 0.1 = 10%):
       re-run R03 with the dynamic threshold                       ← self-correction
   Else: keep results from step 1                                  ← stable fast path
```

In production, the config value should be reviewed and updated periodically when drift alerts fire. For the POC, drift will be 0 since the dataset is static — the structure is in place for production use.

---

#### 2d. Combining Signals

**At-risk determination:** A customer is at-risk if ANY of the following are true:
- Combined RFM score < `RFM_AT_RISK_THRESHOLD`
- R score ≤ 2
- Any rule trigger fires
- ML churn probability ≥ `ML_CHURN_THRESHOLD` (only when `ml_enabled=true`)

**Risk level assignment:**

| Condition | Risk Level |
|---|---|
| R score = 1 OR rule R01/R03 triggered | HIGH |
| R score = 2 OR rule R02/R04 triggered | MEDIUM |
| RFM score below threshold only | LOW |

**Ranking:** At-risk customers are sorted by risk level (HIGH first), then by days since last purchase (descending).

**Blast cap:** Maximum customers per blast run is configurable (`MAX_BLAST_SIZE`, default: 500). When more customers qualify than the cap allows, the top N are selected by descending `combined_score` — highest-risk customers are always prioritized.

**New customer exclusion:** Customers whose `created_at` is within `MIN_CUSTOMER_AGE_DAYS` of today (default: 14) are excluded from at-risk scoring entirely.

**Campaign Targeting Filters:** Each blast run can define an optional SQL WHERE clause applied on top of the at-risk list before the blast cap is applied. The at-risk customer list is loaded into an in-memory SQLite table, and the filter is executed as a SQL query against it.

Examples:
```sql
-- Simple age filter
customer_age_days >= 100

-- Multi-condition segment
customer_age_days >= 14 AND location = 'manado'

-- Complex targeting
top_category = 'electronics' AND risk_level = 'HIGH' AND order_value_avg >= 500000

-- Exclude a segment
risk_level IN ('HIGH', 'MEDIUM') AND location NOT IN ('jakarta', 'surabaya')
```

Any column present in the customer dataset is queryable — adding a new data column to the CSV automatically makes it available as a filter field with no code changes. If no filter is defined, all at-risk customers up to `MAX_BLAST_SIZE` are included. Different blast campaigns can each carry their own SQL filter to target different segments simultaneously.

**Security note — SQL filter validation:** The filter string is operator-supplied and must be validated before execution. Implementation spec:

1. **Parse with `sqlparse`** — tokenize the input and walk the AST before wrapping it in `SELECT * FROM customers WHERE <filter>`
2. **Allowlist tokens:**
   - Comparison operators: `=`, `!=`, `<>`, `<`, `>`, `<=`, `>=`, `IN`, `NOT IN`, `LIKE`, `BETWEEN`
   - Logical connectors: `AND`, `OR`, `NOT`
   - Parentheses and string/number literals
   - Column names that exist in the `AtRiskCustomer` schema only
3. **Blocklist — reject immediately if any of these appear:**
   - DML/DDL keywords: `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `EXEC`, `EXECUTE`
   - Injection markers: `;`, `--`, `/*`, `*/`, `xp_`
   - Subquery indicators: nested `SELECT` or `FROM` tokens
4. **Reject on validation failure** — return a `400 Bad Request` with the invalid token highlighted; never execute a filter that fails validation
5. **Execute via parameterized query** — even after validation, wrap execution in a parameterized SQLite call, not raw string interpolation

**Seasonality note:** Customers who historically only buy in a specific season (e.g. year-end) will appear in the at-risk list during their inactive months. This is intentional — the blast is a valid re-engagement attempt and may convert them to purchase outside their usual window. Seasonality-aware suppression is a future fine-tuning option, not a current requirement.

**Output:**
- Ranked list of `AtRiskCustomer` objects containing:
  - `customer_id`, `name`, `phone`
  - `rfm_scores`: `{r, f, m, combined}`
  - `risk_level`: `HIGH | MEDIUM | LOW`
  - `triggered_rules`: list of rule IDs that fired
  - `days_since_last_purchase`
  - `spend_summary`: total historical spend, average order value, top category

**Known gaps / extension points:**
- No seasonal adjustment — a customer who only buys in December looks inactive in March
- Future: cohort comparison (compare customer against similar-profile peers)
- Future: retrain pipeline — automate periodic retraining of `churn_rf.pkl` as new blast + outcome data accumulates

---

### Stage 3: Promo Assignment

**Goal:** Assign the most appropriate promo offer to each at-risk customer using a deterministic rule-based mapping.

---

#### POC Implementation (current)

Simple mapping function — no database, no lifecycle, no cooldown. Input is `AtRiskCustomer`, output is a `PromoOffer`. High spender is determined by comparing `spend_summary.total_spend` against `HIGH_VALUE_SPEND_THRESHOLD` from config.

**Promo mapping (if/elif):**

| Condition | Promo Value | Code |
|---|---|---|
| HIGH risk + total_spend ≥ HIGH_VALUE_SPEND_THRESHOLD | 30% off your next purchase | `BACK30` |
| HIGH risk + regular spend | 20% off your next purchase | `BACK20` |
| MEDIUM risk + R02 fired | Free shipping + 15% off | `SHIP15` |
| MEDIUM risk + R04 fired | Buy 1 Get 1 on any item | `BOGO1` |
| LOW risk (default) | 2x loyalty points on next purchase | `POINTS2X` |

**Output — `PromoOffer` dataclass:**
- `promo_type` — category string (e.g. `discount_30`)
- `promo_value` — human-readable offer string (e.g. `"30% off your next purchase"`)
- `promo_code` — static code (e.g. `BACK30`)

**What is deferred to production:** unique per-customer codes, SQLite promo lifecycle, cooldown check, promo deduplication, budget cap enforcement, AI toggle. Full spec below.

---

#### Production Spec (deferred)

**AI toggle:** Each campaign can set `ai_enabled: true/false` (default: `false`). When `false`, the rule-based mapping table runs. When `true`, Claude API is called instead. Either way, the output is always a `PromoOffer` object — Stages 4 and 5 are unaware of which strategy was used. `ANTHROPIC_API_KEY` is only required when `ai_enabled=true`.

**Input:** `AtRiskCustomer` object (risk level, RFM scores, triggered rules, spend summary)

**Promo mapping table (v1):**

| Condition | Promo Type | Value | Code Format |
|---|---|---|---|
| HIGH risk + high historical spend (top 20%) | Percentage discount | 30% off | `BACK30` |
| HIGH risk + regular spend | Percentage discount | 20% off | `BACK20` |
| MEDIUM risk + frequency drop (R02) | Free shipping + discount | Free shipping + 15% off | `SHIP15` |
| MEDIUM risk + single purchase (R04) | BOGO | Buy 1 Get 1 on any item | `BOGO1` |
| LOW risk | Loyalty points bonus | 2x points on next purchase | `POINTS2X` |

**Promo code handling:** Each blast generates a unique per-customer code (e.g. `WA-X7K2AB`) and writes it to the SQLite `promo_codes` table with `status: pending`. Codes are short, typeable, and exclude ambiguous characters (`0/O`, `1/I`). Our service owns validation and redemption via API — POS integration is the business's responsibility.

**Code lifecycle:**
- `pending` — written during Stage 3 promo assignment; not yet redeemable
- `active` — promoted by Stage 5 after the message is successfully dispatched; now redeemable at POS
- `cancelled` — set by Stage 5 if the blast is aborted during pre-flight or if dispatch fails for this customer; not redeemable
- `redeemed` — set by `POST /promo-codes/redeem/{code}` after cashier applies discount

**Why pending first:** Pre-flight validation (Stage 4) may abort the entire blast after codes are already written. Writing as `pending` ensures orphaned codes (blast aborted, message never sent) are never redeemable. Stage 5 only promotes to `active` on successful dispatch.

**Promo codes table (SQLite):**

| Column | Type | Description |
|---|---|---|
| `code` | string (PK) | Unique code per customer |
| `customer_id` | string | Customer this code was issued to |
| `promo_type` | string | e.g. `discount_30`, `bogo` |
| `discount_percent` | float | Actual discount value after cap check |
| `issued_at` | datetime | When the blast was sent |
| `expires_at` | datetime | `issued_at + PROMO_EXPIRY_DAYS` |
| `status` | string | `pending` → `active` → `redeemed` or `cancelled` |
| `is_redeemed` | bool | Whether it has been used |
| `redeemed_at` | datetime | When it was redeemed |

**Redemption flow:**
1. Customer shows WhatsApp message with code to cashier
2. Cashier calls `GET /promo-codes/validate/{code}` — returns discount details or rejection reason (`expired`, `already_redeemed`, `not_found`, `pending`, `cancelled`)
3. Cashier applies discount manually at POS
4. Cashier calls `POST /promo-codes/redeem/{code}` — marks `is_redeemed=true`, records `redeemed_at`
5. Customer deletes the WhatsApp message (informal trust step, acceptable for now)

**Known gap:** Steps 2 and 4 are separate calls — a race window exists where the same code could be validated at two registers before either marks it redeemed. Future fix: atomic `POST /promo-codes/validate-and-redeem/{code}` that validates and marks redeemed in a single transaction.

**Budget cap:** After any strategy (rule-based or AI) produces a `PromoOffer`, a validation step checks the discount value against `MAX_DISCOUNT_PERCENT` (default: `30`). If exceeded, the value is clamped to the cap. This is enforced once at the output boundary regardless of which strategy ran.

**Cooldown and deduplication guard:** Before assigning a promo, query the `customer_blast_status` table in `wa_blast.db` against two rules:
1. **Time cooldown** — skip if `last_sent_at` exists and is within `BLAST_COOLDOWN_DAYS` (default: 7 days)
2. **Promo deduplication** — exclude any promo types already recorded in `sent_promo_types` for this customer, ensuring each customer receives a different offer on every re-engagement attempt

**`customer_blast_status` table (SQLite, in `wa_blast.db`):**

| Column | Type | Description |
|---|---|---|
| `customer_id` | string (PK) | Customer identifier |
| `last_sent_at` | datetime | Timestamp of most recent successful dispatch to this customer |
| `sent_promo_types` | string | Comma-separated list of promo types already sent (e.g. `discount_30,bogo`) |

After successful dispatch, `last_sent_at` is updated and the new promo type is appended to `sent_promo_types`. Indexed on `customer_id` for O(1) lookup. All blast state now lives in a single `wa_blast.db` — no separate JSON file.

**Output:**
- `PromoOffer` object per customer:
  - `promo_type`: category string
  - `promo_value`: human-readable offer string
  - `promo_code`: redemption code (display only)
  - `expiry_days`: days until offer expires (default from config)
  - `strategy_used`: `rule_based` or `ai` — for audit logging

**Known gaps / extension points:**
- Future: AI strategy (Claude API) when `ai_enabled=true` per campaign
- Future: atomic validate-and-redeem API call to close the race window between validate and redeem steps

---

### Stage 4: Message Construction

**Goal:** Combine customer data and promo offer into a valid WhatsApp message object.

**WhatsApp template context:** For POC, the template is plain text with named placeholders — no Meta approval required since mock sender is used. When switching to real Meta sender, the template must be reformatted with `{{1}}`, `{{2}}` numbered slots and submitted to Meta for approval. That is a production migration step.

**Template v1 — Re-engagement (POC format):**

```
Hi {name}, we miss you!

It's been a while since your last visit.
Here's a personal offer just for you: {promo_value}.

Use code {promo_code} — valid for {expiry_days} days.

See you soon!
```

| Slot | Value |
|---|---|
| `{name}` | Customer name |
| `{promo_value}` | e.g. `30% off your next purchase` |
| `{promo_code}` | Unique code from promo_codes table, e.g. `WA-X7K2AB` |
| `{expiry_days}` | e.g. `7` |

**Process:**
1. For each customer in the blast batch, inject slot values into the template to produce a `WhatsAppMessage` object
2. Once all messages are constructed, run a **pre-flight validation pass** over the entire batch before dispatching anything:
   - All slots are non-null and non-empty
   - Rendered message length ≤ 1024 characters
   - Promo code exists in the `promo_codes` table with `status=pending`, `is_redeemed=false`, `expires_at` in the future
3. If **any** message fails validation: abort the entire blast, write all failures to `logs/failed_messages.jsonl` (customer ID, failure reason, timestamp), return a full error report to the API caller — no messages are sent
4. If all messages pass: hand the batch to Stage 5 for dispatch

**Design principle:** No partial blasts. The operator sees the full error list, fixes the root cause, and re-runs cleanly.

**Output — `WhatsAppMessage` object:**
```json
{
  "to": "+628123456789",
  "template_name": "reengagement_promo",
  "language_code": "en",
  "template_params": ["John", "30% off your next purchase", "BACK30", "7"],
  "body_preview": "Hi John, we miss you! ..."
}
```

**Known gaps / extension points:**
- Only one template currently defined — add new templates in `messaging/templates/`
- Future: rich media templates (header image + body text)
- Future: per-customer language/locale selection

---

### Stage 5: Message Dispatch

**Goal:** Send (or mock-log) all constructed messages and record results.

**Sender interface:** Both sender implementations (`MockSender`, `MetaSender`) implement the same `BaseSender` abstract class with a single `send(message: WhatsAppMessage) -> SendResult` method. Switching between them is a single config value change (`SENDER_MODE`).

#### Mock Sender (POC default)
- Prints message preview to console
- Writes a log entry to the `blast_log` table in `wa_blast.db`
- Returns a synthetic `SendResult` with `status: "mocked"`

#### Meta Cloud API Sender (production)

```
POST https://graph.facebook.com/v18.0/{WA_PHONE_NUMBER_ID}/messages
Authorization: Bearer {WA_ACCESS_TOKEN}
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "to": "+628123456789",
  "type": "template",
  "template": {
    "name": "reengagement_promo",
    "language": { "code": "en" },
    "components": [{
      "type": "body",
      "parameters": [
        { "type": "text", "text": "John" },
        { "type": "text", "text": "30% off your next purchase" },
        { "type": "text", "text": "BACK30" },
        { "type": "text", "text": "7" }
      ]
    }]
  }
}
```

**Error handling:**

| Error | HTTP Code | Behavior |
|---|---|---|
| Invalid phone / bad request | 400 | Log as `failed` with reason, skip customer, continue blast |
| Rate limit hit | 429 | Pause for `RATE_LIMIT_WAIT_SECONDS` (default: 60s), retry once — if still failing, log as `failed` and continue |
| Meta server error / timeout | 500 / timeout | Log as `failed` with reason, skip customer, continue blast |

**Rate limiting:** Default 10 messages/second (`BLAST_RATE_LIMIT`). Meta allows up to 80/second on Cloud API.

**Blast log (SQLite table in `wa_blast.db`):**

| Column | Type | Description |
|---|---|---|
| `id` | integer (PK) | Auto-increment |
| `blast_id` | string | UUID generated once per `POST /blast/send` call — groups all rows from the same blast run |
| `customer_id` | string | Recipient |
| `phone` | string | E.164 number used |
| `template_name` | string | Template used |
| `promo_code` | string | Code included in message |
| `status` | string | `sent`, `mocked`, `failed` |
| `error_code` | string | HTTP error code if failed |
| `error_reason` | string | Human-readable failure reason |
| `sent_at` | datetime | Dispatch timestamp |

**Opt-out / consent — deferred, open questions:**
- Not implemented for POC
- Must be resolved before any real customer data is used
- Open questions pending business decisions: what constitutes consent (registration checkbox, opt-in reply, implicit relationship), how customers opt out (reply "STOP", message link, customer service), where consent is stored and who maintains the opt-out list
- Meta recommends customers can reply "STOP" to any blast — this ties into reply handling which is also out of scope for POC

**Known gaps / extension points:**
- Consent and opt-out mechanism — required before production
- Future: webhook listener to receive Meta delivery receipts (delivered, read, failed)
- Future: send scheduling per customer timezone

---

### Stage 6: API Layer (FastAPI)

**Goal:** Expose the full pipeline as a REST API consumed by the dashboard and any external integrations.

**Endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/customers/at-risk` | List at-risk customers with RFM scores, triggered rules, risk level. |
| `GET` | `/customers/{id}/promo` | Run rule-based promo assignment for one customer, return the `PromoOffer` — no message sent. Useful for preview before blasting. |
| `POST` | `/blast/preview` | Dry-run the full pipeline — returns all messages that would be sent, with `sent: false`. Nothing is dispatched. |
| `POST` | `/blast/send` | Execute full blast. Runs pre-flight validation on all messages first — aborts with error report if any fail. Optional body: `{ "customer_ids": [...] }` to target a subset. |
| `GET` | `/blast/logs` | Return blast history from the `blast_log` SQLite table. |
| `GET` | `/promo-codes/validate/{code}` | Check if a promo code is valid. Returns discount details or rejection reason (`expired`, `already_redeemed`, `not_found`, `inactive`). Intended for cashier use at POS. |
| `POST` | `/promo-codes/redeem/{code}` | Mark a promo code as redeemed. Records `redeemed_at`. Must be called immediately after cashier applies the discount. |
| `GET` | `/analytics/blast/{blast_id}` | Return feedback metrics for a blast run: redemption rate, re-engagement rate, time-to-redeem, breakdown by promo type. |

**Standard query parameters for all GET list endpoints (`/customers/at-risk`, `/blast/logs`):**

| Parameter | Description | Example |
|---|---|---|
| `limit` | Max results to return | `?limit=50` |
| `offset` | Results to skip for pagination | `?offset=100` |
| `search` | Partial match on customer name or ID | `?search=john` |
| `sort_by` | Column to sort by | `?sort_by=combined_score` |
| `order` | Sort direction: `asc` or `desc` | `?order=desc` |
| `risk_level` | Filter by risk level (customers endpoint) | `?risk_level=HIGH` |
| `since` | Records after this datetime (logs endpoint) | `?since=2026-05-01` |

**Notes:**
- All responses are JSON
- No authentication in POC — add API key middleware before any external exposure; one `API_KEY` config value is all it takes
- `/blast/send` is idempotent per customer per cooldown window (cooldown check happens inside promo assignment)

---

### Stage 7: Dashboard (Streamlit) — Optional

**Goal:** Visual interface to operate the pipeline without using the API directly.

**Pages:**
1. **At-Risk Customers** — sortable table of customers with RFM scores and risk levels
2. **Promo Preview** — select a customer, view the assigned promo offer before committing to send
3. **Blast Control** — run preview or execute blast, monitor progress
4. **Blast History** — view past send logs filtered by date or status

**Architecture note:** The dashboard is a pure consumer of the FastAPI layer. It has no direct access to the engine or database. This means it can be replaced, removed, or run on a different machine without affecting the core service.

---

## Configuration Reference

All configuration lives in `.env` (secrets) and `config.py` (defaults with env overrides).

| Parameter | Description | Default |
|---|---|---|
| `WA_ACCESS_TOKEN` | Meta WhatsApp Cloud API bearer token | — |
| `WA_PHONE_NUMBER_ID` | Meta registered phone number ID | — |
| `SENDER_MODE` | `mock` or `meta` | `mock` |
| `SCORING_VERSION` | Active scoring strategy version (`v1.0`, `v1.1`, ...) | `v1.0` |
| `INACTIVITY_THRESHOLD_DAYS` | Days of inactivity to trigger R01 rule | `30` |
| `FREQUENCY_DROP_THRESHOLD` | R02 trigger ratio — current period count must be below this fraction of prior period (0.5 = >50% drop) | `0.5` |
| `HIGH_VALUE_SPEND_THRESHOLD` | Fixed total-spend cutoff above which a customer is "high value" for R03 | `1500.0` |
| `THRESHOLD_DRIFT_TOLERANCE` | If dynamic 80th percentile differs from `HIGH_VALUE_SPEND_THRESHOLD` by more than this fraction, re-run R03 with dynamic value | `0.1` |
| `RFM_WINDOW_DAYS` | Lookback window for RFM calculation | `180` |
| `RFM_AT_RISK_THRESHOLD` | Combined RFM sum below this = at-risk | `8` |
| `MIN_CUSTOMER_AGE_DAYS` | Exclude customers newer than this from scoring | `14` |
| `MAX_BLAST_SIZE` | Maximum customers per blast run | `500` |
| `BLAST_COOLDOWN_DAYS` | Minimum days between blasts to same customer | `7` |
| `BLAST_RATE_LIMIT` | Messages per second during dispatch | `10` |
| `RATE_LIMIT_WAIT_SECONDS` | Seconds to pause when a 429 rate limit response is received before retrying | `60` |
| `PROMO_EXPIRY_DAYS` | Default days until promo offer expires | `7` |
| `WA_REGISTRATION_CHECK` | Whether to call Meta Contacts API to verify each number is WhatsApp-registered. Set `false` if business uses WhatsApp OTP at signup. | `false` |
| `MAX_DISCOUNT_PERCENT` | Maximum discount value any promo strategy may output — clamped at validation | `30` |
| `ANTHROPIC_API_KEY` | Claude API key — only required when a campaign has `ai_enabled=true` | — |
| `ML_MODEL_PATH` | Path to trained Random Forest model artifact | `engine/models/churn_rf.pkl` |
| `ML_CHURN_THRESHOLD` | Minimum churn probability to flag a customer as at-risk via ML | `0.6` |

---

## Data Flow Diagram

```
┌──────────────────┐
│  Dataset (CSV)   │
└────────┬─────────┘
         │ Stage 1: Ingest & Normalize
         ▼
┌──────────────────────┐
│  Customer + Txn      │
│  (normalized)        │
└────────┬─────────────┘
         │ Stage 2: Churn Analysis
         ▼
┌──────────────────────────────────────────────┐
│  RFM Scoring (percentile-based)              │
│  + Rule-Based Triggers                       │
│  + ML ChurnPredictor [if ml_enabled=true]    │
│  → Ranked At-Risk List                       │
└────────┬─────────────────────────────────────┘
         │ Stage 3: Promo Assignment
         ▼
┌──────────────────────────────────────────┐
│  Rule-Based Promo Mapping Table          │
│  (+ cooldown check vs.                   │
│     customer_blast_status SQLite table)  │
│  → PromoOffer per customer               │
│  → promo_codes written as pending        │
└────────┬─────────────────────────────────┘
         │ Stage 4: Message Construction
         ▼
┌──────────────────────────────────┐
│  Template Slot Injection         │
│  → WhatsAppMessage per customer  │
└────────┬─────────────────────────┘
         │ Stage 5: Dispatch
         ▼
┌──────────────────────────────────────────┐
│  MockSender (log to file)                │
│  OR MetaSender (Meta Cloud API)          │
│  — same interface, config-switchable —   │
└────────┬─────────────────────────────────┘
         │
         ▼
┌──────────────────────────┐
│  wa_blast.db (SQLite)          │
│  tables: blast_log,            │
│          promo_codes,          │
│          customer_blast_status │
└────────────────────────────────┘
```

---

## Future Enhancements (Not In Scope Now)

These are planned features with defined integration points. Do not implement until the core pipeline is stable.

| Feature | Where It Plugs In |
|---|---|
| AI Promo Generator (Claude API) | Replaces or augments `promo/mapping.py` in Stage 3 |
| ML retraining pipeline | Automate periodic retraining of `churn_rf.pkl` as new blast outcome data accumulates |
| Delivery receipt webhooks | New FastAPI route consuming Meta webhook callbacks |
| Customer opt-out management | New `consent` field in `data/schema.py`, checked in Stage 5 |
| Feedback loop automation | Feed redemption rates from `GET /analytics/blast/{id}` back into Stage 3 promo mapping automatically |
| Automated scheduling | Cron or APScheduler wrapper around `POST /blast/send` — manual trigger is used for POC |
| A/B testing | Split at-risk list in Stage 3, assign different promo rules per group |
| Rich media templates | Extend `messaging/templates/` with header image support |

---

## Known Gaps Summary

These are documented weaknesses that must be resolved before production. See `WEAKNESS.md` for full detail and severity ratings.

| ID | Gap | Severity | Stage |
|---|---|---|---|
| 5.1 | No opt-out / consent mechanism — legal requirement | 🔴 Critical | Stage 5 |
| 2.1 | Versioned `ScoringStrategy` interface — v1.0 uses percentile quintiles, future versions are drop-in | ✅ Resolved | Stage 2 |
| 2.2 | Combined score = R+F+M sum for v1.0; formula is part of the versioned strategy | ✅ Resolved | Stage 2 |
| 3.1 | AI decoupled from core — Stage 3 is now rule-based promo assignment | ✅ Resolved | Stage 3 |
| 2.3 | Frequency Drop period = two equal halves of `RFM_WINDOW_DAYS`, fully config-driven | ✅ Resolved | Stage 2 |
| 2.4 | `MAX_BLAST_SIZE` cap with top-N priority sort by `combined_score` | ✅ Resolved | Stage 2 |
| 2.5 | New customer exclusion via `created_at` + `MIN_CUSTOMER_AGE_DAYS` | ✅ Resolved | Stage 2 |
| 2.6 | Seasonality reframed as opportunity — seasonal customers stay in pool intentionally | ✅ Resolved | Stage 2 |
| 3.4 | `is_sent` via `customer_blast_status.json` — O(1) cooldown + promo deduplication | ✅ Resolved | Stage 3 |
| 3.3 | Per-customer unique codes in SQLite `promo_codes` table — validate/redeem via API | ✅ Resolved | Stage 3 |
| 3.2 | `MAX_DISCOUNT_PERCENT` cap enforced at `PromoOffer` validation — all strategies clamped | ✅ Resolved | Stage 3 |
| 1.1 | Transaction deduplication + blast cooldown + promo deduplication — all defined | ✅ Resolved | Stage 1 + 3 |
| 1.2 | Phone validation pipeline + `WA_REGISTRATION_CHECK` flag — defined in Stage 1 | ✅ Resolved | Stage 1 |
| 1.3 | Customer age filter via `created_at` + `MIN_CUSTOMER_AGE_DAYS` | ✅ Resolved | Stage 1 |
| 1.4 | Canonical CSV schema + strict column validation at ingest | ✅ Resolved | Stage 1 |
| 5.2 | Blast log moved to SQLite `blast_log` table in `wa_blast.db` | ✅ Resolved | Stage 5 |
| 5.3 | Three-case error handling: 400 skip, 429 pause+retry, 500 skip | ✅ Resolved | Stage 5 |
| 4.1 | Plain text template for POC — Meta format is a production migration step | ✅ Resolved | Stage 4 |
| 4.2 | Missing slot = skip message + log to `failed_messages.jsonl` | ✅ Resolved | Stage 4 |
| 4.3 | Pre-flight batch validation — abort entire blast if any message fails | ✅ Resolved | Stage 4 |
| 6.2 | `/customers/{id}/promo` now returns rule-based `PromoOffer` | ✅ Resolved | Stage 6 |
| 6.3 | Standard list query params on all GET endpoints — limit, offset, search, sort, filter | ✅ Resolved | Stage 6 |
| G.1 | Feedback loop via `GET /analytics/blast/{id}` — redemption + re-engagement metrics | ✅ Resolved | Stage 6 |
| G.2 | Flow diagram updated — AI removed, Promo Assignment shown | ✅ Resolved | Diagram |
| G.3 | Manual trigger via `POST /blast/send` for POC | ✅ Resolved | Stage 6 |
| 6.1 | No API authentication — add one middleware + `API_KEY` config when ready | ⏸ Noted | Stage 6 |
| 5.1 | No opt-out / consent mechanism — legal requirement before production | 🔴 Deferred | Stage 5 |
| C2 | `customer_blast_status` moved from JSON file to SQLite `wa_blast.db` — single source of truth | ✅ Resolved | Stage 3 |
| C3 | `blast_id` UUID column added to `blast_log` — enables `GET /analytics/blast/{id}` grouping | ✅ Resolved | Stage 5 |
| C4 | Promo code lifecycle: `pending → active → redeemed/cancelled` — orphaned codes from aborted blasts are never redeemable | ✅ Resolved | Stage 3/4/5 |
| C5 | SQL filter injection guard specified: `sqlparse` AST walk, token allowlist/blocklist, parameterized execution | ✅ Resolved | Stage 2 |
| C1 | Random Forest ML ChurnPredictor added as Stage 2b — `ml_enabled` flag per campaign, trained offline, loaded at runtime | ✅ Resolved | Stage 2 |
| C6 | Stage 2 execution order: rules-first (cheap, uses fixed config for R03) → RFM → ML for unflagged only → combine. Rule-caught HIGH risk customers bypass ML scoring at runtime (still used in training). | ✅ Resolved | Stage 2 |
| C7 | R02 frequency-drop ratio promoted to config (`FREQUENCY_DROP_THRESHOLD`) — tunable without code change | ✅ Resolved | Stage 2c |
| C8 | R03 high-value threshold uses hybrid fixed-config + drift detection pattern (`HIGH_VALUE_SPEND_THRESHOLD` + `THRESHOLD_DRIFT_TOLERANCE`) — avoids per-run percentile recomputation while self-correcting on data drift | ✅ Resolved | Stage 2c |
