import pandas as pd
import pickle
import json
from pathlib import Path
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import cross_val_score

from Pipeline.data.loader import load_customers
from Pipeline.engine.rfm import compute_rfm
from Pipeline.engine.rules import evaluate_rules, triggered_rule_ids
from Pipeline.config import HIGH_VALUE_SPEND_THRESHOLD

PROFILES_PATH = "Pipeline/customer_profiles.csv"
MODEL_PATH = "Pipeline/engine/models/churn_rf.pkl"
MINIMUM_ACCURACY = 0.8
MINIMUM_ROC_AUC = 0.78

def build_features(customer, rfm, fired_rules):
    return {
        "recency_days": rfm.recency_days,
        "frequency": rfm.frequency,
        "monetary": rfm.monetary,
        "r_score": rfm.r_score,
        "f_score": rfm.f_score,
        "m_score": rfm.m_score,
        "combined_score": rfm.combined_score,
        "r01": int("R01" in fired_rules),
        "r02": int("R02" in fired_rules),
        "r03": int("R03" in fired_rules),
        "r04": int("R04" in fired_rules),
        "total_spend": customer.total_spend,
        "avg_order_value": customer.avg_order_value,
        "purchase_count": customer.purchase_count,
        "age": customer.age or 0,
    }

def main():
    customers, date_cutoff = load_customers("Pipeline/transactions.csv")

    profiles = pd.read_csv(PROFILES_PATH).set_index("customer_id")["profile"].to_dict()

    rfm_scores = compute_rfm(customers, date_cutoff)
    rfm_map = {r.customer_id: r for r in rfm_scores}

    rows = []
    labels = []

    for customer in customers:
        rfm = rfm_map.get(customer.customer_id)
        if rfm is None:
            continue
        
        profile = profiles.get(customer.customer_id)
        if profile is None:
            continue

        results     = evaluate_rules(customer, date_cutoff, HIGH_VALUE_SPEND_THRESHOLD)
        fired       = triggered_rule_ids(results)
        features    = build_features(customer, rfm, fired)
        churned     = 1 if profile in ("fading", "one_time") else 0

        rows.append(features)
        labels.append(churned)

    X = pd.DataFrame(rows)
    y = pd.Series(labels)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    print(f"Training on {len(X)} customers - churn rate: {y.mean():.1%}")
    print(f"  Train: {len(X_train)}, Test: {len(X_test)}")

    print("Training model...")
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    print("Done.")

    y_pred = model.predict(X_test)

    accuracy    = accuracy_score(y_test, y_pred)
    roc_auc     = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])

    print(f"\nAccuracy : {accuracy:.3f}")
    print(f"ROC-AUC : {roc_auc:.3f}")

    # --- guard rails ---
    assert accuracy >= MINIMUM_ACCURACY, f"Accuracy too low: {accuracy:.3f} (expected >= {MINIMUM_ACCURACY})"
    assert roc_auc >= MINIMUM_ROC_AUC, f"ROC-AUC too low: {roc_auc:.3f} (expected >= {MINIMUM_ROC_AUC})"

    print ("\nAll model checks passed.")

    importances = pd.Series(model.feature_importances_, index=X.columns)
    importances = importances.sort_values(ascending=False)

    print("\nFeature importances:")
    for feature, score in importances.items():
        bar = "█" * int(score * 50)
        print(f"  {feature:<20} {score:.3f} {bar}")

    # --- model evaluation ---
    cv_scores = cross_val_score(model, X_train, y_train, cv=5, scoring="roc_auc")

    report = {
        "trained_at": datetime.now().isoformat(),
        "dataset": {
            "total_customers": len(X),
            "churn_rate": round(float(y.mean()), 3),
            "churned": int(y.sum()),
            "not_churned": int((y == 0).sum()),
        },
        "model": {
            "type": "RandomForestClassifier",
            "n_estimators": 100,
            "random_state": 42,
        },
        "metrics": {
            "roc_auc_mean": round(float(cv_scores.mean()), 4),
            "roc_auc_std": round(float(cv_scores.std()), 4),
            "roc_auc_per_fold": [round(float(s), 4) for s in cv_scores],
        },
        "feature_importances": {
            feature: round(float(score), 4)
            for feature, score in importances.items()
        },
    }

    report_path = Path(MODEL_PATH).parent / "train_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report saved to {report_path}")

    Path(MODEL_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"model": model, "features": list(X_train.columns)}, f)

    print(f"Model saved to {MODEL_PATH}")

if __name__ == "__main__":
    main()