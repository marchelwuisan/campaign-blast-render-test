# WA-Blast

WhatsApp blast service for customer retention. Identifies at-risk customers using RFM scoring, rule-based triggers, and ML churn prediction, then sends personalized WhatsApp promos.

---

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install pandas scikit-learn
```

---

## Preparing the Dataset

The pipeline expects a CSV file at `Pipeline/transactions.csv` with these required columns:

| Column | Description |
|---|---|
| `customer_id` | Unique customer identifier |
| `purchase_date` | Transaction date (YYYY-MM-DD) |
| `order_value` | Total order amount |
| `product_category` | Product category |
| `phone_number` | Customer phone in Indonesian format (`+62...`, `62...`, or `08...`) |
| `created_at` | Customer registration date (YYYY-MM-DD) |

Optional columns (used if present):
| Column | Description |
|---|---|
| `customer_name` | Display name — falls back to `customer_id` if missing |
| `gender` | Customer gender |
| `age` | Customer age |
| `quantity` | Used to compute `order_value` if missing (`quantity * price_per_unit`) |
| `price_per_unit` | Used to compute `order_value` if missing |

### Using a public dataset

If your dataset has different column names, rename them to match the required columns above before placing the file at `Pipeline/transactions.csv`.

Missing columns can be stubbed:
```python
df["phone_number"] = "+6281200000000"  # stub phone
df["created_at"]   = "2023-01-01"      # stub registration date
```

See `enrich_dataset.py` for a working example of dataset transformation.

---

## Running the Pipeline

### 1. Generate dataset (first time or after changes)

```bash
.venv/bin/python enrich_dataset.py
```

Outputs:
- `Pipeline/transactions.csv` — main transaction dataset
- `Pipeline/customer_profiles.csv` — behavioral profile labels (used for ML training)

### 2. Train the ML model

```bash
.venv/bin/python -m Pipeline.engine.train
```

Outputs:
- `Pipeline/engine/models/churn_rf.pkl` — trained Random Forest model
- `Pipeline/engine/models/train_report.json` — training metrics and feature importances

Must be re-run if the dataset changes or `build_features()` is modified.

### 3. Test the pipeline (optional)

```bash
.venv/bin/python test_pipeline.py
```

Outputs:
- `test_pipeline_report.json` — at-risk customer summary with risk distribution, rule counts, and sample output

### 4. Run the Dashboard (optional)

Install dashboard dependencies first (if not already):

```bash
.venv/bin/pip install streamlit plotly requests
```

Start both the API and the dashboard in separate terminals:

```bash
# Terminal 1 — API server
.venv/bin/python -m uvicorn Pipeline.api.main:app --reload

# Terminal 2 — Streamlit dashboard
.venv/bin/python -m streamlit run dashboard/app.py
```

The dashboard runs at `http://localhost:8501` and connects to the API at `http://localhost:8000`.

**Dashboard pages:**

| Page | Description |
|---|---|
| Blast | Preview or trigger a blast, toggle ML, view result summary |
| Logs | Paginated blast history with search and date filters |
| Customers | At-risk customer list with risk level filter (engine runs once per session) |
| Analytics | Engine overview (risk distribution, rule counts) + per-blast metrics and charts |

---

### 5. Run the API

Install API dependencies first (if not already):

```bash
.venv/bin/pip install fastapi uvicorn python-dotenv
```

Copy the environment template and fill in your values:

```bash
cp .env.example .env
```

Start the server:

```bash
.venv/bin/python -m uvicorn Pipeline.api.main:app --reload
```

The API runs at `http://localhost:8000`. Open `http://localhost:8000/docs` for the interactive Swagger UI.

### 5. Send a blast

Trigger a full blast run via the API:

```bash
curl -X POST http://localhost:8000/blast/send \
  -H "Content-Type: application/json" \
  -d '{"ml_enabled": false}'
```

Or use the Swagger UI at `/docs` — no curl required.

**Blast endpoints:**

| Method | Path | Description |
|---|---|---|
| `POST` | `/blast/preview` | Dry-run — returns messages that would be sent, nothing dispatched |
| `POST` | `/blast/send` | Execute full blast — runs pipeline, writes to DB |
| `GET` | `/blast/logs` | Paginated blast history |
| `GET` | `/customers/at-risk` | Scored at-risk customer list |
| `GET` | `/analytics/blast/{blast_id}` | Metrics for a specific blast run |

---

## Configuration

All settings are in `Pipeline/config.py` and can be overridden with environment variables:

```bash
INACTIVITY_THRESHOLD_DAYS=60 .venv/bin/python test_pipeline.py
```

Key settings:

| Variable | Default | Description |
|---|---|---|
| `RFM_WINDOW_DAYS` | 180 | Days of transaction history used for RFM scoring |
| `RFM_AT_RISK_THRESHOLD` | 6 | Combined RFM score below this = at-risk |
| `INACTIVITY_THRESHOLD_DAYS` | 300 | Days inactive before R01 fires |
| `HIGH_VALUE_SPEND_THRESHOLD` | 1500.0 | Spend threshold for R03 (high-value lapse) |
| `MAX_BLAST_SIZE` | 500 | Maximum customers per blast |
| `BLAST_COOLDOWN_DAYS` | 7 | Minimum days between blasts to the same customer |
| `ML_CHURN_THRESHOLD` | 0.8 | Minimum churn probability to flag a customer |
| `SENDER_MODE` | `mock` | `mock` logs to console; `meta` sends via Meta Cloud API |

---

## Project Structure

```
WA-Blast/
├── Pipeline/
│   ├── config.py                  # All configurable settings
│   ├── transactions.csv           # Input dataset (not committed)
│   ├── customer_profiles.csv      # Profile labels for ML training
│   ├── data/
│   │   ├── schema.py              # Customer and Transaction dataclasses
│   │   └── loader.py              # Stage 1 — CSV ingestion and validation
│   └── engine/
│       ├── rfm.py                 # RFM scoring (quintile-based)
│       ├── rules.py               # Rule-based churn triggers (R01–R04)
│       ├── analyzer.py            # Stage 2 — combines rules + RFM + ML
│       ├── train.py               # ML training script (run once)
│       ├── ml.py                  # ChurnPredictor — scores a single customer
│       └── models/
│           ├── churn_rf.pkl       # Trained model (not committed)
│           └── train_report.json  # Training metrics
├── enrich_dataset.py              # Dataset transformation and enrichment
├── test_pipeline.py               # End-to-end pipeline test
├── FLOW.md                        # Architecture and design decisions
└── README.md
```

---

## Pipeline Stages

| Stage | File | Description |
|---|---|---|
| 1 | `data/loader.py` | Load CSV, validate, normalize phones, build Customer objects |
| 2 | `engine/analyzer.py` | Score customers — rules → RFM → ML → rank at-risk list |
| 3 | `promo/mapping.py` | Assign discount promo per customer based on risk level |
| 4 | `messaging/constructor.py` | Build WhatsApp message from customer + promo |
| 5 | `messaging/mock_sender.py` | Dispatch messages (mock logs to console; swap to MetaSender for real sends) |
| 6 | `api/` | FastAPI layer — exposes full pipeline as REST endpoints |
