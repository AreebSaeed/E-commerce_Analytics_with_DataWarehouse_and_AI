"""Group buyers with K-Means and save the resulting segments to PostgreSQL."""

import argparse
from datetime import datetime, timezone
import io
import json

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text

from etl import ROOT, connection_settings, database_engine

FEATURES = [
    "recency_days",
    "frequency_orders",
    "log_monetary_gmv",
    "avg_review_score",
    "avg_delivery_delay_days",
]
SAMPLE_SIZE = 2000  # A fixed, bounded sample keeps silhouette evaluation quick.


def prepare(data):
    """Return eligible buyers and the fitted transformations for all five inputs."""
    buyers = data.loc[data.frequency_orders > 0].copy().reset_index(drop=True)
    if len(buyers) < 100:
        raise ValueError("At least 100 buyers with eligible orders are needed")
    values = buyers[FEATURES].apply(pd.to_numeric, errors="coerce")
    medians = values.median().fillna(0)
    values = values.fillna(medians)
    lower, upper = values.quantile(0.01), values.quantile(0.99)
    values = values.clip(lower=lower, upper=upper, axis="columns")
    scaler = StandardScaler()
    matrix = scaler.fit_transform(values)
    if not np.isfinite(matrix).all():
        raise ValueError("Customer features contain invalid numbers")
    return buyers, matrix, {
        "median": medians,
        "lower": lower,
        "upper": upper,
        "scaler": scaler,
    }


def choose_clusters(matrix):
    sample = np.random.default_rng(42).choice(
        len(matrix),
        size=min(SAMPLE_SIZE, len(matrix)),
        replace=False,
    )
    scores = {}
    models = {}
    for k in range(2, 9):
        model = KMeans(n_clusters=k, n_init=5, random_state=42)
        model.fit(matrix)
        sample_labels = model.labels_[sample]
        if len(np.unique(sample_labels)) < 2:
            continue
        scores[k] = float(silhouette_score(matrix[sample], sample_labels))
        models[k] = model
        print(f"k={k}: sample silhouette={scores[k]:.3f}", flush=True)
    if not scores:
        raise ValueError("No valid clustering was found")
    best_k = max(scores, key=scores.get)
    return best_k, models[best_k], scores, len(sample)


def label_clusters(buyers):
    """Use simple profile-based names; cluster numbers keep names unambiguous."""
    overall = buyers[["monetary_gmv", "recency_days", "avg_delivery_delay_days"]].median()
    spend_high = buyers.monetary_gmv.quantile(0.75)
    recency_high = buyers.recency_days.quantile(0.75)
    delay_high = buyers.avg_delivery_delay_days.quantile(0.75)
    profiles, names = {}, {}
    for cluster_id, group in buyers.groupby("cluster_id"):
        med = group[["frequency_orders", "monetary_gmv", "recency_days",
                     "avg_review_score", "avg_delivery_delay_days"]].median()
        if med.frequency_orders >= 2 and med.monetary_gmv >= overall.monetary_gmv:
            name = "Higher spend repeat buyers"
        elif med.frequency_orders >= 2:
            name = "Repeat buyers"
        elif med.avg_delivery_delay_days > max(delay_high, 0):
            name = "Historically delayed buyers"
        elif med.monetary_gmv >= spend_high:
            name = "Higher spend buyers"
        elif med.recency_days >= recency_high:
            name = "Older one-time buyers"
        else:
            name = "One-time lower spend buyers"
        names[int(cluster_id)] = f"{name} (Cluster {cluster_id})"
        profiles[int(cluster_id)] = {
            "customers": len(group),
            "label": names[int(cluster_id)],
            **{
                key: None if pd.isna(value) else round(float(value), 2)
                for key, value in med.items()
            },
        }
    return names, profiles


def save_segments(engine, output, version, scores, sample_size, profiles):
    if output.customer_unique_id.isna().any() or output.customer_unique_id.duplicated().any():
        raise ValueError("Segments must contain one row per permanent buyer ID")
    with engine.begin() as connection:
        connection.exec_driver_sql("TRUNCATE dw.ml_customer_segments")
        cursor = connection.connection.driver_connection.cursor()
        try:
            for start in range(0, len(output), 10000):
                buffer = io.StringIO()
                output.iloc[start:start + 10000].to_csv(buffer, index=False,
                    header=False, lineterminator="\n")
                buffer.seek(0)
                cursor.copy_expert("COPY dw.ml_customer_segments "
                    "(customer_unique_id,cluster_id,segment_label,model_version) "
                    "FROM STDIN WITH (FORMAT CSV)", buffer)
        finally:
            cursor.close()
        notes = json.dumps({"model_version": version, "silhouette_sample": sample_size})
        metrics = {f"silhouette_k{k}": value for k, value in scores.items()}
        metrics["selected_k"] = max(scores, key=scores.get)
        metrics.update({f"cluster_{k}_customers": p["customers"] for k, p in profiles.items()})
        metrics["no_eligible_purchase_customers"] = int((output.cluster_id == -1).sum())
        for name, value in metrics.items():
            connection.execute(text("INSERT INTO meta.ml_runs "
                "(model_name,sample_size,metric_name,metric_value,notes) "
                "VALUES ('kmeans',:sample,:name,:value,:notes)"),
                {"sample": sample_size, "name": name, "value": value, "notes": notes})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("host", "port", "database", "user"):
        parser.add_argument(f"--{option}")
    settings = connection_settings(parser.parse_args())
    engine = database_engine(settings)
    try:
        with engine.connect() as connection:
            data = pd.read_sql(text("SELECT customer_unique_id, " + ", ".join(FEATURES) +
                ", monetary_gmv FROM dw.v_customer_features"), connection)
        buyers, matrix, transform = prepare(data)
        best_k, model, scores, sample_size = choose_clusters(matrix)
        buyers["cluster_id"] = model.labels_.astype(int)
        names, profiles = label_clusters(buyers)
        buyers["segment_label"] = buyers.cluster_id.map(names)
        inactive = data.loc[data.frequency_orders == 0, ["customer_unique_id"]].copy()
        inactive["cluster_id"] = -1
        inactive["segment_label"] = "No eligible purchases"
        output = pd.concat((buyers[["customer_unique_id", "cluster_id", "segment_label"]],
                            inactive), ignore_index=True)
        if len(output) != len(data):
            raise ValueError("Every customer must receive exactly one segment")
        version = "segments_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        output["model_version"] = version
        model_dir = ROOT / "models"
        model_dir.mkdir(exist_ok=True)
        model_path = model_dir / f"{version}.joblib"
        joblib.dump({"model": model, "transform": transform, "features": FEATURES}, model_path)
        save_segments(engine, output, version, scores, sample_size, profiles)
        report = {"version": version, "selected_k": best_k, "sample_size": sample_size,
            "silhouette_scores": scores, "cluster_profiles": profiles,
            "buyers_with_eligible_orders": len(buyers),
            "buyers_without_eligible_orders": len(inactive), "total_customers": len(output)}
        (model_dir / f"{version}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Selected k={best_k}; saved {len(output):,} customer segments", flush=True)
        for profile in profiles.values():
            print(f"  {profile['label']}: {profile['customers']:,} customers", flush=True)
        print(f"  No eligible purchases: {len(inactive):,} customers", flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
