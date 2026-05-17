import pandas as pd
import pickle
import json
from pathlib import Path
from datetime import datetime
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import cross_val_score


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

def evaluate_model(model, X, X_test, y_test, minimum_accuracy, minimum_roc_auc):
    unique_classes = y_test.unique()
    if len(unique_classes) < 2:
        raise ValueError(
            f"Test set contains only one class ({unique_classes.tolist()}). "
            "The dataset time span is too short for the PREDICTION_DAYS window — "
            "reduce PREDICTION_DAYS or use a dataset with a longer date range."
        )

    y_pred = model.predict(X_test)

    accuracy    = accuracy_score(y_test, y_pred)
    roc_auc     = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
    
    print(f"\nAccuracy : {accuracy:.3f}")
    print(f"ROC-AUC : {roc_auc:.3f}")

    importances = pd.Series(model.feature_importances_, index=X.columns)
    importances = importances.sort_values(ascending=False)

    print("\nFeature importances:")
    for feature, score in importances.items():
        bar = "█" * int(score * 50)
        print(f"  {feature:<20} {score:.3f} {bar}")

    # --- guard rails ---
    assert accuracy >= minimum_accuracy, f"Accuracy too low: {accuracy:.3f} (expected >= {minimum_accuracy})"
    assert roc_auc >= minimum_roc_auc, f"ROC-AUC too low: {roc_auc:.3f} (expected >= {minimum_roc_auc})"

    print ("\nAll model checks passed.")

    return accuracy, roc_auc, importances



def save_model(model, X_train, y_train, model_path, approach, accuracy, roc_auc, importances):
    
    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    with open(model_path, "wb") as f:
        pickle.dump({"model": model, "features": list(X_train.columns)}, f)

    cv_scores = cross_val_score(model, X_train, y_train, cv=5, scoring="roc_auc")

    meta = {
        "approach":     approach,
        "trained_at":   datetime.now().isoformat(),
        "model_path":   model_path,
        "roc_auc_mean": round(float(cv_scores.mean()), 4),
        "roc_auc_std":  round(float(cv_scores.std()), 4)
    }

    report = {
        "trained_at": datetime.now().isoformat(),
        "dataset": {
            "total_customers": len(X_train),
            "churn_rate": round(float(y_train.mean()), 3),
            "churned": int(y_train.sum()),
            "not_churned": int((y_train == 0).sum()),
        },
        "model": {
            "type": type(model).__name__,
            "params": model.get_params(),
        },
        "metrics": {
            "accuracy":        round(accuracy, 4),
            "roc_auc":         round(roc_auc, 4),
            "roc_auc_mean": round(float(cv_scores.mean()), 4),
            "roc_auc_std": round(float(cv_scores.std()), 4),
            "roc_auc_per_fold": [round(float(s), 4) for s in cv_scores],
        },
        "feature_importances": {
            feature: round(float(score), 4)
            for feature, score in importances.items()
        },
    }


    meta_path = Path(model_path).parent / "model_meta.json"
    report_path = Path(model_path).parent / "train_report.json"

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, default=str)

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"Model saved to {model_path}")
    print(f"Meta saved to {meta_path}")
    print(f"Report saved to {report_path}")
