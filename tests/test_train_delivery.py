"""Check chronological separation and the predictor allow-list."""
import unittest

import numpy as np
import pandas as pd

from train_delivery import (
    FEATURES,
    balance_training_data,
    chronological_split,
    compute_sample_weights,
    fit_weighted_model,
)


class DeliveryTrainingTests(unittest.TestCase):
    def test_chronological_periods_do_not_overlap(self):
        rows = pd.DataFrame({
            "order_id": [f"order-{i}" for i in range(120)],
            "purchase_timestamp": pd.date_range("2018-01-01", periods=120, freq="D"),
            "label_is_late": [i % 5 == 0 for i in range(120)],
        })
        train, validation, test = chronological_split(rows)
        self.assertLess(train.purchase_timestamp.max(), validation.purchase_timestamp.min())
        self.assertLess(validation.purchase_timestamp.max(), test.purchase_timestamp.min())
        self.assertEqual(len(train) + len(validation) + len(test), len(rows))

    def test_outcome_and_identifiers_are_not_predictors(self):
        for forbidden in ("order_id", "purchase_timestamp", "label_is_late",
                          "delivered_timestamp", "estimated_delivery_timestamp",
                          "delivery_delay_days", "latest_review_score", "order_status"):
            self.assertNotIn(forbidden, FEATURES)

    def test_class_balancing_preserves_positives_and_chronology(self):
        rows = pd.DataFrame({
            "order_id": [f"order-{i}" for i in range(100)],
            "purchase_timestamp": pd.date_range("2018-01-01", periods=100, freq="D"),
            "label_is_late": [i % 10 == 0 for i in range(100)],
        })
        balanced = balance_training_data(rows, negative_ratio=3.0)
        self.assertEqual(int(balanced.label_is_late.sum()), 10)
        self.assertEqual(len(balanced), 40)
        self.assertTrue(balanced.purchase_timestamp.is_monotonic_increasing)

    def test_weighted_loss_prioritizes_positives_and_recent_orders(self):
        labels = np.array([0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
        weights = compute_sample_weights(labels, class_power=0.5)
        self.assertAlmostEqual(float(weights.mean()), 1.0, places=6)
        self.assertGreater(weights[4], weights[0])
        self.assertGreater(weights[9], weights[4])

    def test_fit_weighted_model_trains_both_candidates(self):
        rows = pd.DataFrame({
            "purchase_month": [i % 12 + 1 for i in range(60)],
            "purchase_weekday": [i % 7 + 1 for i in range(60)],
            "item_count": [1 + (i % 3) for i in range(60)],
            "item_price": [50.0 + i for i in range(60)],
            "freight_value": [12.0 + (i % 10) for i in range(60)],
            "total_weight_g": [500.0 + i * 10 for i in range(60)],
            "weight_known_items": [1 for _ in range(60)],
            "total_volume_cm3": [2000.0 + i * 20 for i in range(60)],
            "volume_known_items": [1 for _ in range(60)],
            "seller_customer_distance_km": [100.0 + i * 5 for i in range(60)],
            "customer_state": ["SP" if i % 2 == 0 else "RJ" for i in range(60)],
            "seller_state": ["SP" for _ in range(60)],
            "label_is_late": [i % 6 == 0 for i in range(60)],
        })
        for kind in ("logistic_regression", "random_forest"):
            model = fit_weighted_model(kind, rows)
            probs = model.predict_proba(rows[FEATURES])[:, 1]
            self.assertEqual(len(probs), len(rows))
            self.assertTrue(((probs >= 0.0) & (probs <= 1.0)).all())


if __name__ == "__main__":
    unittest.main()
