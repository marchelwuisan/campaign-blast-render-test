import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

from Pipeline.data.loader import load_customers
from Pipeline.engine.rfm import compute_rfm
from Pipeline.engine.rules import evaluate_rules, triggered_rule_ids
from Pipeline.config import HIGH_VALUE_SPEND_THRESHOLD
from Pipeline.engine.training.base import build_features, evaluate_model, save_model

PROFILES_PATH = "Pipeline/customer_profiles.csv"
APPROACH = "profile_based"
MODEL_PATH = f"Pipeline/engine/models/{APPROACH}/churn_rf.pkl"
MINIMUM_ACCURACY = 0.8
MINIMUM_ROC_AUC = 0.78

def main():
    # 1. load data
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


    # 2. derive labels
    X = pd.DataFrame(rows)
    y = pd.Series(labels)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    print(f"Training on {len(X)} customers - churn rate: {y.mean():.1%}")
    print(f"  Train: {len(X_train)}, Test: {len(X_test)}")

    # 3. train
    print("Training model...")
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    print("Done.")

    # 4. evaluate
    accuracy, roc_auc, importances = evaluate_model(model, X_train, X_test, y_test, MINIMUM_ACCURACY, MINIMUM_ROC_AUC)

    # 5. save model
    save_model(model, X_train, y_train, MODEL_PATH, APPROACH, accuracy, roc_auc, importances)

if __name__ == "__main__":
    main()