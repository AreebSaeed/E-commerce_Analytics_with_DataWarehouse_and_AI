"""Train and evaluate a late-delivery classifier, then score warehouse orders."""

import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, confusion_matrix, precision_recall_fscore_support
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import text

from etl import ROOT, connection_settings, database_engine

# Only these columns are given to a model. IDs, timestamps and the label are not.
NUMERIC = ["purchase_month", "purchase_weekday", "item_count", "item_price",
           "freight_value", "total_weight_g", "weight_known_items",
           "total_volume_cm3", "volume_known_items", "seller_customer_distance_km"]
CATEGORICAL = ["customer_state", "seller_state"]
FEATURES = NUMERIC + CATEGORICAL
THRESHOLDS = np.arange(0.05, 0.95, 0.025)
MODEL_CONFIGS = {
    "logistic_regression": {"negative_ratio": 3.0, "class_power": 0.7},
    "random_forest": {"negative_ratio": None, "class_power": 0.5},
}


def read_features(engine):
    columns = ", ".join(FEATURES)
    with engine.connect() as connection:
        labeled = pd.read_sql(text(
            f"SELECT order_id, purchase_timestamp, label_is_late, {columns} "
            "FROM dw.v_delivery_training"), connection)
        all_orders = pd.read_sql(text(
            f"SELECT order_id, {columns} FROM dw.v_delivery_features"), connection)
    for data in (labeled, all_orders):
        for column in NUMERIC:
            data[column] = pd.to_numeric(data[column], errors="coerce")
        for column in CATEGORICAL:
            data[column] = data[column].fillna("Unknown").astype(str)
    return labeled, all_orders


def chronological_split(labeled):
    rows = labeled.dropna(subset=["purchase_timestamp", "label_is_late"]).sort_values(
        ["purchase_timestamp", "order_id"]).reset_index(drop=True)
    if len(rows) < 100:
        raise ValueError("At least 100 labeled orders are needed for training")
    first_cutoff = rows.loc[int(len(rows) * 0.70), "purchase_timestamp"]
    second_cutoff = rows.loc[int(len(rows) * 0.85), "purchase_timestamp"]
    train = rows[rows.purchase_timestamp < first_cutoff]
    validation = rows[(rows.purchase_timestamp >= first_cutoff)
                      & (rows.purchase_timestamp < second_cutoff)]
    test = rows[rows.purchase_timestamp >= second_cutoff]
    if not len(train) or not len(validation) or not len(test):
        raise ValueError("Purchase dates do not form three nonempty periods")
    if train.label_is_late.nunique() != 2 or validation.label_is_late.nunique() != 2 or test.label_is_late.nunique() != 2:
        raise ValueError("Each period needs both on-time and late examples")
    return train, validation, test


def balance_training_data(data, negative_ratio=None, random_state=42):
    """Keep all positive late orders and downsample majority orders if ratio is set."""
    if negative_ratio is None:
        return data
    labels = data.label_is_late.astype(int).to_numpy()
    pos_idx = np.where(labels == 1)[0]
    neg_idx = np.where(labels == 0)[0]
    target_neg = int(len(pos_idx) * negative_ratio)
    if not len(pos_idx) or target_neg >= len(neg_idx):
        return data
    rng = np.random.default_rng(random_state)
    sampled_neg = rng.choice(neg_idx, size=max(1, target_neg), replace=False)
    keep_idx = np.sort(np.concatenate([pos_idx, sampled_neg]))
    return data.iloc[keep_idx].reset_index(drop=True)


def compute_sample_weights(labels, class_power=0.5, recency_min=0.5, recency_max=1.5):
    """Compute normalized class-balanced and temporally recency-weighted sample weights."""
    y = np.asarray(labels, dtype=int)
    pos_count = int((y == 1).sum())
    neg_count = int((y == 0).sum())
    if pos_count == 0 or neg_count == 0:
        return np.ones(len(y), dtype=float)
    pos_weight = float((neg_count / pos_count) ** class_power)
    class_weights = np.where(y == 1, pos_weight, 1.0)
    recency_weights = np.linspace(recency_min, recency_max, len(y))
    combined = class_weights * recency_weights
    return combined / combined.mean()


def model_pipeline(kind):
    numeric = Pipeline([("fill", SimpleImputer(strategy="median", keep_empty_features=True)),
                        ("scale", StandardScaler())])
    category = Pipeline([("fill", SimpleImputer(strategy="constant", fill_value="Unknown")),
                         ("encode", OneHotEncoder(handle_unknown="ignore"))])
    preprocess = ColumnTransformer([("numbers", numeric, NUMERIC),
                                    ("states", category, CATEGORICAL)])
    if kind == "random_forest":
        classifier = RandomForestClassifier(n_estimators=200, max_depth=14,
            min_samples_leaf=12, random_state=42, n_jobs=-1)
    else:
        classifier = LogisticRegression(max_iter=1000, C=0.25, random_state=42)
    return Pipeline([("preprocess", preprocess), ("classifier", classifier)])


def fit_weighted_model(kind, data):
    """Apply class balancing and weighted loss, then fit the requested pipeline."""
    cfg = MODEL_CONFIGS[kind]
    balanced = balance_training_data(data, negative_ratio=cfg["negative_ratio"])
    y = balanced.label_is_late.astype(int)
    sample_weight = compute_sample_weights(y, class_power=cfg["class_power"])
    model = model_pipeline(kind)
    model.fit(balanced[FEATURES], y, classifier__sample_weight=sample_weight)
    return model


def evaluate_probabilities(actual, probability, threshold):
    """Compute binary classification metrics from precomputed probabilities."""
    predicted = (probability >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        actual, predicted, average="binary", zero_division=0)
    tn, fp, fn, tp = confusion_matrix(actual, predicted, labels=[0, 1]).ravel()
    ap = average_precision_score(actual, probability) if len(np.unique(actual)) == 2 else 0.0
    return {"rows": len(actual), "late_rows": int(actual.sum()),
            "precision": float(precision), "recall": float(recall), "f1": float(f1),
            "average_precision": float(ap),
            "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}


def evaluate(model, data, threshold):
    actual = data.label_is_late.astype(int)
    probability = model.predict_proba(data[FEATURES])[:, 1]
    return evaluate_probabilities(actual, probability, threshold)


def choose_threshold(model, validation):
    actual = validation.label_is_late.astype(int)
    probability = model.predict_proba(validation[FEATURES])[:, 1]
    results = [(evaluate_probabilities(actual, probability, float(threshold)), float(threshold))
               for threshold in THRESHOLDS]
    return max(results, key=lambda pair: (pair[0]["f1"], pair[0]["precision"]))


def write_scores(engine, all_orders, model, kind, version, threshold, validation, test):
    probability = model.predict_proba(all_orders[FEATURES])[:, 1]
    scores = pd.DataFrame({"order_id": all_orders.order_id,
        "late_probability": np.round(probability, 6),
        "predicted_late": probability >= threshold,
        "risk_band": np.where(probability < threshold / 2, "Low",
                       np.where(probability < threshold, "Medium", "High")),
        "model_version": version})
    if len(scores) != scores.order_id.nunique() or scores.late_probability.isna().any():
        raise ValueError("Scores must contain one valid probability per order")
    with engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE dw.ml_order_risk_scores")
        cursor = connection.connection.driver_connection.cursor()
        try:
            # COPY keeps the write-back fast and atomic for the full warehouse.
            for start in range(0, len(scores), 10000):
                buffer = io.StringIO()
                scores.iloc[start:start + 10000].to_csv(buffer, index=False, header=False,
                    lineterminator="\n", float_format="%.6f")
                buffer.seek(0)
                cursor.copy_expert("COPY dw.ml_order_risk_scores "
                    "(order_id,late_probability,predicted_late,risk_band,model_version) "
                    "FROM STDIN WITH (FORMAT CSV)", buffer)
        finally:
            cursor.close()
        for split, metrics in (("validation", validation), ("test", test)):
            notes = json.dumps({"model_version": version, "split": split,
                                "decision_threshold": threshold})
            for name in ("precision", "recall", "f1", "average_precision", "tn", "fp", "fn", "tp"):
                connection.execute(text("INSERT INTO meta.ml_runs "
                    "(model_name,sample_size,metric_name,metric_value,notes) "
                    "VALUES (:model,:sample,:name,:value,:notes)"),
                    {"model": kind, "sample": metrics["rows"],
                     "name": name, "value": metrics[name], "notes": notes})
    return len(scores)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("host", "port", "database", "user"):
        parser.add_argument(f"--{option}")
    settings = connection_settings(parser.parse_args())
    engine = database_engine(settings)
    try:
        labeled, all_orders = read_features(engine)
        train, validation, test = chronological_split(labeled)
        print(
            f"Labeled orders: train {len(train):,}, validation {len(validation):,}, test {len(test):,}",
            flush=True
        )
        print(f"Periods: train before {validation.purchase_timestamp.min().date()}, "
              f"test from {test.purchase_timestamp.min().date()}", flush=True)
        candidates = {}
        for kind in ("logistic_regression", "random_forest"):
            model = fit_weighted_model(kind, train)
            result, threshold = choose_threshold(model, validation)
            candidates[kind] = (result, threshold)
            print(f"{kind} validation: precision={result['precision']:.3f}, "
                  f"recall={result['recall']:.3f}, F1={result['f1']:.3f}, "
                  f"AP={result['average_precision']:.3f}, cutoff={threshold:.3f}", flush=True)
        chosen = max(
            candidates,
            key=lambda name: (candidates[name][0]["f1"], candidates[name][0]["precision"])
        )
        validation_result, threshold = candidates[chosen]
        # Refit on train + validation. The later test period remains untouched.
        train_and_validation = pd.concat((train, validation), ignore_index=True)
        final_model = fit_weighted_model(chosen, train_and_validation)
        test_result = evaluate(final_model, test, threshold)
        print(f"Selected {chosen}; held-out test: precision={test_result['precision']:.3f}, "
              f"recall={test_result['recall']:.3f}, F1={test_result['f1']:.3f}, "
              f"AP={test_result['average_precision']:.3f}", flush=True)
        print(f"Confusion matrix: TN={test_result['tn']}, FP={test_result['fp']}, "
              f"FN={test_result['fn']}, TP={test_result['tp']}", flush=True)

        version = "delivery_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        model_dir = ROOT / "models"
        model_dir.mkdir(exist_ok=True)
        model_path = model_dir / f"{version}.joblib"
        joblib.dump({"model": final_model, "features": FEATURES, "threshold": threshold}, model_path)
        score_count = write_scores(engine, all_orders, final_model, chosen, version, threshold,
                                   validation_result, test_result)
        report = {
            "version": version,
            "selected_model": chosen,
            "feature_columns": FEATURES,
            "train_rows": len(train),
            "validation": {name: result for name, (result, _) in candidates.items()},
            "test": test_result,
            "scored_orders": score_count,
            "threshold": threshold,
            "training_cutoff": str(validation.purchase_timestamp.min()),
            "test_cutoff": str(test.purchase_timestamp.min()),
        }
        (model_dir / f"{version}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Saved {score_count:,} order scores and model {model_path.name}", flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
