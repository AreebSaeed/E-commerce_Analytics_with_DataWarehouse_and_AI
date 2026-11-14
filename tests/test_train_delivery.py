"""Check chronological separation and the predictor allow-list."""
import unittest

import pandas as pd

from train_delivery import FEATURES, chronological_split


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


if __name__ == "__main__":
    unittest.main()
