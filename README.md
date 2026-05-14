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

### 3. Test the pipeline

```bash
.venv/bin/python test_pipeline.py
```

Outputs:
- `test_pipeline_report.json` — at-risk customer summary with risk distribution, rule counts, and sample output

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
| `RFM_AT_RISK_THRESHOLD` | 8 | Combined RFM score below this = at-risk |
| `INACTIVITY_THRESHOLD_DAYS` | 30 | Days inactive before R01 fires |
| `HIGH_VALUE_SPEND_THRESHOLD` | 1500.0 | Spend threshold for R03 (high-value lapse) |
| `MAX_BLAST_SIZE` | 500 | Maximum customers per blast |
| `ML_CHURN_THRESHOLD` | 0.6 | Minimum churn probability to flag a customer |

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
| 3 | _(coming soon)_ | Promo assignment |
| 4 | _(coming soon)_ | Message construction |
| 5 | _(coming soon)_ | WhatsApp dispatch |
