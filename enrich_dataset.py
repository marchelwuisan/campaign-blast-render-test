import pandas as pd
import numpy as np
from datetime import timedelta

INPUT  = "retail_sales_dataset.csv"
OUTPUT = "Pipeline/transactions.csv"
SEED   = 42

# Behavioral profiles — % of 1000 customers assigned to each
PROFILES = {
    "loyal":      {"pct": 0.20, "txn_range": (8, 12),  "recency_days": (0, 30)},
    "occasional": {"pct": 0.40, "txn_range": (3, 5),   "recency_days": (20, 90)},
    "fading":     {"pct": 0.25, "txn_range": (2, 3),   "recency_days": (60, 150)},
    "one_time":   {"pct": 0.15, "txn_range": (1, 1),   "recency_days": (90, 180)},
}

df = pd.read_csv(INPUT)
df.columns = df.columns.str.lower().str.replace(" ", "_")
df = df.rename(columns={"total_amount": "order_value", "date": "purchase_date"})
df["phone_number"] = "+6282187792052"
df["created_at"]   = "2023-01-01"

# Lock gender and age per customer from original data
profile = df.set_index("customer_id")[["gender", "age"]].to_dict(orient="index")

rng = np.random.default_rng(SEED)

categories = df["product_category"].unique()
price_map = {
    "Beauty":      (10, 500),
    "Clothing":    (50, 1000),
    "Electronics": (100, 2000),
}

date_end   = pd.Timestamp("2024-01-01")
date_start = pd.Timestamp("2023-01-01")

# Assign each customer a behavioral profile
customer_ids = sorted(df["customer_id"].unique())
rng.shuffle(customer_ids)

cutoffs = {}
start = 0
for pname, pconf in PROFILES.items():
    count = int(len(customer_ids) * pconf["pct"])
    for cid in customer_ids[start:start + count]:
        cutoffs[cid] = (pname, pconf)
    start += count
# assign remainder to occasional
for cid in customer_ids[start:]:
    cutoffs[cid] = ("occasional", PROFILES["occasional"])

max_txn_id = df["transaction_id"].max()

rows = []
txn_counter = 0

for cid, (pname, pconf) in cutoffs.items():
    txn_count = int(rng.integers(pconf["txn_range"][0], pconf["txn_range"][1] + 1))
    recency_lo, recency_hi = pconf["recency_days"]

    # Most recent transaction date based on recency range
    most_recent_offset = int(rng.integers(recency_lo, recency_hi + 1))
    most_recent_date = date_end - timedelta(days=most_recent_offset)

    # Spread remaining transactions back in time from most_recent_date
    txn_dates = [most_recent_date]
    for _ in range(txn_count - 1):
        days_back = int(rng.integers(1, 365))
        txn_date = most_recent_date - timedelta(days=days_back)
        # clamp to date_start
        if txn_date < date_start:
            txn_date = date_start + timedelta(days=int(rng.integers(0, 30)))
        txn_dates.append(txn_date)

    for txn_date in txn_dates:
        cat = categories[rng.integers(0, len(categories))]
        lo, hi = price_map.get(cat, (10, 500))
        price = int(rng.integers(lo, hi + 1))
        qty   = int(rng.integers(1, 4))

        rows.append({
            "transaction_id":   max_txn_id + txn_counter + 1,
            "purchase_date":    txn_date.strftime("%Y-%m-%d"),
            "customer_id":      cid,
            "gender":           profile[cid]["gender"],
            "age":              profile[cid]["age"],
            "product_category": cat,
            "quantity":         qty,
            "price_per_unit":   price,
            "order_value":      price * qty,
            "phone_number":     "+6282187792052",
            "created_at":       "2023-01-01",
        })
        txn_counter += 1

synthetic = pd.DataFrame(rows)

# Keep original 1000 rows untouched, append synthetic
combined = pd.concat([df, synthetic], ignore_index=True)
combined = combined[[
    "transaction_id", "purchase_date", "customer_id",
    "gender", "age", "product_category",
    "quantity", "price_per_unit", "order_value",
    "phone_number", "created_at",
]]

combined.to_csv(OUTPUT, index=False)

# Summary
txn_per_customer = combined.groupby("customer_id").size()
profile_counts = {p: sum(1 for v in cutoffs.values() if v[0] == p) for p in PROFILES}

print(f"Saved to {OUTPUT}")
print(f"  Total rows        : {len(combined)}")
print(f"  Unique customers  : {combined['customer_id'].nunique()}")
print(f"  Txn per customer  — min: {txn_per_customer.min()}, max: {txn_per_customer.max()}, avg: {txn_per_customer.mean():.1f}")
print(f"  Profile breakdown :")
for pname, count in profile_counts.items():
    print(f"    {pname:<12}: {count} customers")
print(f"  Gender consistent : {(combined.groupby('customer_id')['gender'].nunique() == 1).all()}")
print(f"  Age consistent    : {(combined.groupby('customer_id')['age'].nunique() == 1).all()}")
