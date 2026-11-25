"""Export small, aggregate-only dashboard data from the local PostgreSQL warehouse."""

import argparse
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import sys

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from etl import connection_settings, database_engine  # noqa: E402


def plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def read_rows(connection, query):
    return [{key: plain(value) for key, value in row.items()}
            for row in connection.execute(text(query)).mappings()]


def main():
    args = argparse.Namespace(host=None, port=None, database=None, user=None)
    settings = connection_settings(args)
    engine = database_engine(settings)
    try:
        with engine.connect() as connection:
            data = {
                "headline": read_rows(
                    connection,
                    "SELECT order_count, gmv, aov, delivered_orders, on_time_orders, "
                    "on_time_delivery_pct, avg_review_score, freight_to_price_pct "
                    "FROM dw.v_sales_kpis",
                )[0],
                "monthly": read_rows(
                    connection,
                    "SELECT month, order_count, gmv, on_time_orders, delivered_orders "
                    "FROM dw.v_monthly_kpis WHERE month IS NOT NULL ORDER BY month",
                ),
                "regional": read_rows(
                    connection,
                    "SELECT extract(year from o.purchase_timestamp)::int AS year, c.state, "
                    "count(*) AS order_count, sum(o.gmv) AS gmv, "
                    "avg(o.delivery_lead_time_days) AS avg_delivery_days "
                    "FROM dw.v_order_metrics o JOIN dw.dim_customer c USING(customer_key) "
                    "WHERE o.purchase_timestamp IS NOT NULL "
                    "AND o.order_status NOT IN ('canceled','unavailable') AND c.state IS NOT NULL "
                    "GROUP BY 1,2 ORDER BY 1,4 DESC",
                ),
                "categories": read_rows(
                    connection,
                    "SELECT extract(year from month)::int AS year, category_name_en AS category, "
                    "macro_department, sum(gmv) AS gmv, sum(item_count) AS item_count "
                    "FROM dw.v_category_seller_metrics WHERE month IS NOT NULL "
                    "GROUP BY 1,2,3 ORDER BY 1,4 DESC",
                ),
                "payments": read_rows(
                    connection,
                    "SELECT extract(year from month)::int AS year, payment_type, "
                    "sum(payment_total) AS amount FROM dw.v_payment_method_metrics "
                    "WHERE month IS NOT NULL GROUP BY 1,2 ORDER BY 1,3 DESC",
                ),
                "risks": read_rows(
                    connection,
                    "SELECT risk_band AS label, count(*) AS count FROM dw.ml_order_risk_scores "
                    "GROUP BY risk_band ORDER BY risk_band",
                ),
                "segments": read_rows(
                    connection,
                    "SELECT cluster_id, segment_label AS label, count(*) AS count "
                    "FROM dw.ml_customer_segments GROUP BY cluster_id, segment_label ORDER BY cluster_id",
                ),
            }
    finally:
        engine.dispose()
    output = Path(__file__).parent / "public/dashboard.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported aggregate dashboard snapshot to {output}")


if __name__ == "__main__":
    main()
