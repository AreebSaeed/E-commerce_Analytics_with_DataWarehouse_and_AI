"""Time the SQL used by Power BI and the TypeScript dashboard.

Read-only: EXPLAIN ANALYZE executes SELECTs but changes no warehouse data.
"""

import argparse
from pathlib import Path
import sys
from time import perf_counter

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from etl import connection_settings, database_engine  # noqa: E402


QUERIES = {
    "sales_kpis": "SELECT * FROM dw.v_sales_kpis",
    "monthly_kpis": "SELECT * FROM dw.v_monthly_kpis ORDER BY month",
    "regional_metrics": "SELECT * FROM dw.v_regional_metrics ORDER BY gmv DESC",
    "category_seller_metrics": "SELECT * FROM dw.v_category_seller_metrics",
    "payment_method_metrics": "SELECT * FROM dw.v_payment_method_metrics",
    "web_regional_year": """SELECT extract(year from o.purchase_timestamp)::int AS year,
        c.state, count(*) AS order_count, sum(o.gmv) AS gmv,
        avg(o.delivery_lead_time_days) AS avg_delivery_days
        FROM dw.v_order_metrics o JOIN dw.dim_customer c USING(customer_key)
        WHERE o.purchase_timestamp IS NOT NULL
          AND o.order_status NOT IN ('canceled','unavailable') AND c.state IS NOT NULL
        GROUP BY 1,2 ORDER BY 1,4 DESC""",
    "web_category_year": """SELECT extract(year from month)::int AS year,
        category_name_en, macro_department, sum(gmv) AS gmv, sum(item_count) AS item_count
        FROM dw.v_category_seller_metrics WHERE month IS NOT NULL
        GROUP BY 1,2,3 ORDER BY 1,4 DESC""",
    "web_payment_year": """SELECT extract(year from month)::int AS year,
        payment_type, sum(payment_total) AS amount
        FROM dw.v_payment_method_metrics WHERE month IS NOT NULL
        GROUP BY 1,2 ORDER BY 1,3 DESC""",
    "risk_bands": "SELECT risk_band, count(*) FROM dw.ml_order_risk_scores GROUP BY risk_band",
    "segments": "SELECT segment_label, count(*) FROM dw.ml_customer_segments GROUP BY segment_label",
    "spatial_bbox": """SELECT count(*) FROM dw.dim_geolocation
        WHERE geo_point <@ box(point(-47.0,-24.0), point(-46.0,-23.0))""",
    "spatial_nearest": """SELECT zip_prefix, city, state FROM dw.dim_geolocation
        WHERE geo_point IS NOT NULL
        ORDER BY geo_point <-> point(-46.6333,-23.5505) LIMIT 10""",
}


def used_indexes(node):
    found = []
    if "Index Name" in node:
        found.append(node["Index Name"])
    for child in node.get("Plans", []):
        found.extend(used_indexes(child))
    return sorted(set(found))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    settings = connection_settings(argparse.Namespace(host=None, port=None, database=None, user=None))
    engine = database_engine(settings)
    print("Query,Rows,PostgreSQL ms,Warm client ms max,Indexes used")
    try:
        with engine.connect() as db:
            for name, sql in QUERIES.items():
                plan = db.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)).scalar_one()[0]
                timings = []
                rows = 0
                for _ in range(args.repeats):
                    start = perf_counter()
                    rows = len(db.execute(text(sql)).all())
                    timings.append((perf_counter() - start) * 1000)
                print(f"{name},{rows},{plan['Execution Time']:.1f},{max(timings):.1f},"
                      f"{'|'.join(used_indexes(plan['Plan'])) or '-'}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
