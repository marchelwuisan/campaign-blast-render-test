import pandas as pd
from datetime import timezone, timedelta
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier

from Pipeline.config import HIGH_VALUE_SPEND_THRESHOLD
from Pipeline.data.loader import load_customers
from Pipeline.engine.rfm import compute_rfm
from Pipeline.engine.rules import evaluate_rules, triggered_rule_ids
from Pipeline.engine.training.base import build_features, evaluate_model, save_model

APPROACH = "temporal"
MODEL_PATH = "Pipeline/engine/models/temporal/churn_rf.pkl"
PREDICTION_DAYS = 90
MIN_PRIOR_COUNT = 2
DROP_THRESHOLD = 0.5
MINIMUM_ACCURACY = 0.75
MINIMUM_ROC_AUC = 0.72


def derive_labels(
    customers, date_cutoff, prediction_days, min_prior_count, drop_threshold
):
    cutoff = date_cutoff.replace(tzinfo=timezone.utc)
    pred_start = cutoff - timedelta(days=prediction_days)

    labels = {}
    for customer in customers:
        prior_count = sum(
            1 for t in customer.transactions if t.purchase_date < pred_start
        )
        recent_count = sum(
            1 for t in customer.transactions if t.purchase_date >= pred_start
        )

        if prior_count < min_prior_count:
            continue

        churned = 1 if recent_count < prior_count * drop_threshold else 0
        labels[customer.customer_id] = churned

    return labels


def main():
    customers, date_cutoff = load_customers("Pipeline/transactions.csv")

    labels = derive_labels(
        customers, date_cutoff, PREDICTION_DAYS, MIN_PRIOR_COUNT, DROP_THRESHOLD
    )

    print(f"Customers with valid labels: {len(labels)}")
    churn_rate = sum(labels.values()) / len(labels)
    print(f"Churn rate: {churn_rate:.1%}")

    # RFM computed on observation window only - no data leakage
    observation_cutoff = date_cutoff.replace(tzinfo=timezone.utc) - timedelta(
        days=PREDICTION_DAYS
    )
    rfm_scores = compute_rfm(customers, observation_cutoff)
    rfm_map = {r.customer_id: r for r in rfm_scores}

    rows, y_labels = [], []

    for customer in customers:
        churned = labels.get(customer.customer_id)
        if churned is None:
            continue

        rfm = rfm_map.get(customer.customer_id)
        if rfm is None:
            continue

        fired = triggered_rule_ids(
            evaluate_rules(customer, observation_cutoff, HIGH_VALUE_SPEND_THRESHOLD)
        )

        rows.append(build_features(customer, rfm, fired))
        y_labels.append(churned)

    X = pd.DataFrame(rows)
    y = pd.Series(y_labels)

    print(f"Training on {len(X)} customers - churn rate: {y.mean():.1%}")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42
    )
    print(f"    Train: {len(X_train)}, Test: {len(X_test)}")

    print("Training model...")
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    print("Done.")

    accuracy, roc_auc, importances = evaluate_model(
        model, X_train, X_test, y_test, MINIMUM_ACCURACY, MINIMUM_ROC_AUC
    )
    save_model(
        model, X_train, y_train, MODEL_PATH, APPROACH, accuracy, roc_auc, importances
    )


if __name__ == "__main__":
    main()
