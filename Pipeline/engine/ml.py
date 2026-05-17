import pickle
from Pipeline.config import ML_MODEL_PATH
from Pipeline.engine.training.train_temporal import build_features

class ChurnPredictor:
    def __init__(self):
        with open(ML_MODEL_PATH, "rb") as f:
            saved = pickle.load(f)
        self.model      = saved["model"]
        self.features   = saved["features"]

    def score(self, customer, rfm, date_cutoff) -> float:
        if rfm is None:
            return 0.0
        from Pipeline.engine.rules import evaluate_rules, triggered_rule_ids
        from Pipeline.config import HIGH_VALUE_SPEND_THRESHOLD
        results     = evaluate_rules(customer, date_cutoff, HIGH_VALUE_SPEND_THRESHOLD)
        fired       = triggered_rule_ids(results)
        row         = build_features(customer,rfm, fired)
        import pandas as pd
        X = pd.DataFrame([row])[self.features]
        return float(self.model.predict_proba(X)[0][1])