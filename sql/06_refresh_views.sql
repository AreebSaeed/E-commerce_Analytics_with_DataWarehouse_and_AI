-- Run after warehouse changes. Each summary has a unique index and is populated.
REFRESH MATERIALIZED VIEW CONCURRENTLY dw.mv_monthly_kpis;
REFRESH MATERIALIZED VIEW CONCURRENTLY dw.mv_regional_metrics;
REFRESH MATERIALIZED VIEW CONCURRENTLY dw.mv_category_seller_metrics;
