"""Check that incomplete and extreme customer records remain usable."""
import unittest

import numpy as np
import pandas as pd

from segment_customers import FEATURES, prepare


class CustomerSegmentationTests(unittest.TestCase):
    def test_missing_values_and_outliers_produce_finite_features(self):
        rows = pd.DataFrame({
            "customer_unique_id": [f"buyer-{i}" for i in range(121)],
            "recency_days": [10] * 119 + [100000, None],
            "frequency_orders": [1] * 120 + [0],
            "log_monetary_gmv": [4] * 119 + [20, 0],
            "avg_review_score": [5] * 119 + [None, None],
            "avg_delivery_delay_days": [-1] * 119 + [None, None],
        })
        buyers, matrix, config = prepare(rows)
        self.assertEqual(len(buyers), 120)
        self.assertEqual(matrix.shape, (120, len(FEATURES)))
        self.assertTrue(np.isfinite(matrix).all())
        self.assertEqual(config["median"]["avg_review_score"], 5)


if __name__ == "__main__":
    unittest.main()
