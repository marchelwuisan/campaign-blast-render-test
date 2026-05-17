# Temporal Training Approach

## Goal

Predict customer churn using **real transaction behavior** instead of invented profile labels. The model learns from historical patterns: given a customer's behavior in an early time window, can it predict whether their activity will decline in a later window?

---

## How Labels Are Derived

The dataset is split into two time windows based on `date_cutoff`:

```
|-------- observation window --------|---- prediction window ----|
              (early period)                  (last 90 days)
```

For each customer, count transactions in each window:
- `prior_count`  — transactions in the observation window
- `recent_count` — transactions in the prediction window

**Label rule (frequency drop):**

```
churned = 1 if recent_count < prior_count * 0.5 else 0
```

A customer is labeled churned if their recent transaction count dropped by more than 50% compared to the observation window — captures both customers who stopped buying entirely AND those who are fading.

**Edge cases:**
- Customers with `prior_count < 3` are excluded — too little baseline data for reliable labels
- Customers with `prior_count == 0` are excluded — no baseline to compare against

---

## How Features Are Computed

Features come from the **observation window only**. The prediction window is reserved for label derivation — never used to compute features. This prevents data leakage (using future information to predict the future).

Same 15 features as `profile_based`:
- RFM scores (recency, frequency, monetary, r/f/m scores, combined)
- Rule flags (r01, r02, r03, r04)
- Spend stats (total_spend, avg_order_value, purchase_count)
- Demographics (age)

---

## Why This Beats Profile-Based

| | Profile-based | Temporal |
|---|---|---|
| Label source | Invented profiles | Real transaction behavior |
| Generalizes to new data | No (needs profile mapping) | Yes (any transaction CSV) |
| Discovers new patterns | No (model reproduces rules) | Yes (model finds non-obvious signals) |
| Production-ready | No | Yes |
| Expected accuracy | ~95% (suspicious) | ~70–80% (realistic) |

The lower accuracy of the temporal approach is a **feature, not a bug** — it reflects the real difficulty of predicting customer behavior without engineered labels.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PREDICTION_DAYS` | 90 | Length of the prediction window (last N days) |
| `MIN_PRIOR_COUNT` | 3 | Minimum transactions needed in observation window to include customer |
| `DROP_THRESHOLD` | 0.5 | Ratio of recent/prior to flag as churned (0.5 = 50% drop) |
| `MINIMUM_ACCURACY` | 0.75 | Guard rail — training fails if accuracy is below this |
| `MINIMUM_ROC_AUC` | 0.72 | Guard rail — training fails if ROC-AUC is below this |

---

## Running

```bash
.venv/bin/python -m Pipeline.engine.training.train_temporal
```

Outputs:
- `Pipeline/engine/models/temporal/churn_rf.pkl` — trained model
- `Pipeline/engine/models/temporal/model_meta.json` — lightweight metadata
- `Pipeline/engine/models/temporal/train_report.json` — full training report

---

## Switching to This Model in the Pipeline

Set `ML_MODEL_PATH` to point at the temporal model:

```bash
ML_MODEL_PATH=Pipeline/engine/models/temporal/churn_rf.pkl .venv/bin/python test_pipeline.py
```

Or update `Pipeline/config.py` default to use temporal as the primary model.

---

## Limitations

1. **Requires sufficient transaction history** — customers with very few prior transactions are excluded from training. New customers won't be scored well.
2. **Window length is fixed at training time** — 90 days for prediction means the model assumes a 90-day churn horizon. Changing this requires retraining.
3. **No seasonality awareness** — a customer who only buys during holidays will look like a "churner" for most of the year.
4. **Label noise** — frequency drop is a proxy for churn, not ground truth. Some customers labeled churned may return organically without intervention.

These are acceptable for POC and align with how non-contractual churn is typically modeled in retail.
