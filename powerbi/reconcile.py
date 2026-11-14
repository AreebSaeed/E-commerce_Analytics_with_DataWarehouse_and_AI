"""Check the figures shown in Olist_PowerBI_Dashboard.pbix against PostgreSQL."""

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from etl import connection_settings, database_engine  # noqa: E402


def main():
    args = argparse.Namespace(host=None, port=None, database=None, user=None)
    engine = database_engine(connection_settings(args))
    with engine.connect() as db:
        sales = db.execute(text("SELECT order_count, gmv, aov, on_time_delivery_pct FROM dw.v_sales_kpis")).one()
        totals = db.execute(text("""
            SELECT
              (SELECT sum(order_count) FROM dw.v_monthly_kpis) AS monthly_orders,
              (SELECT sum(gmv) FROM dw.v_monthly_kpis) AS monthly_gmv,
              (SELECT sum(gmv) FROM dw.v_regional_metrics) AS regional_gmv,
              (SELECT sum(gmv) FROM dw.v_category_seller_metrics) AS category_gmv,
              (SELECT sum(payment_total) FROM dw.v_payment_method_metrics) AS payment_total,
              (SELECT count(*) FROM dw.ml_order_risk_scores) AS risk_orders,
              (SELECT count(*) FROM dw.ml_customer_segments) AS segmented_customers
        """)).one()
        risk = db.execute(text("SELECT risk_band, count(*) FROM dw.ml_order_risk_scores GROUP BY 1 ORDER BY 1")).all()
        segments = db.execute(text("SELECT segment_label, count(*) FROM dw.ml_customer_segments GROUP BY 1 ORDER BY 1")).all()

    print(f"Sales cards: orders={sales.order_count:,}, GMV={sales.gmv:,.2f}, "
          f"AOV={sales.aov:,.2f}, on-time={sales.on_time_delivery_pct}%")
    print(f"Monthly orders={totals.monthly_orders:,}; monthly GMV={totals.monthly_gmv:,.2f}")
    print(f"Regional GMV={totals.regional_gmv:,.2f}; category GMV={totals.category_gmv:,.2f}")
    print(f"Payment-method total={totals.payment_total:,.2f}")
    print(f"Risk-band orders={totals.risk_orders:,}: {dict(risk)}")
    print(f"Segmented customers={totals.segmented_customers:,}: {dict(segments)}")
    assert sales.order_count == totals.monthly_orders
    assert sales.gmv == totals.monthly_gmv == totals.regional_gmv == totals.category_gmv
    assert sum(count for _, count in risk) == totals.risk_orders
    assert sum(count for _, count in segments) == totals.segmented_customers
    print("Reporting reconciliation passed.")


if __name__ == "__main__":
    main()
