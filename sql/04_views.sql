CREATE OR REPLACE VIEW dw.v_order_metrics AS
SELECT o.order_key,o.order_id,o.order_status,o.customer_key,o.purchase_timestamp,o.purchase_date_key,o.is_delivered,o.is_on_time,o.delivery_lead_time_days,o.delivery_delay_days,o.latest_review_score,coalesce(i.item_count,0) item_count,coalesce(i.item_price,0) item_price,coalesce(i.freight,0) freight,coalesce(i.gmv,0) gmv,coalesce(p.payment_total,0) payment_total
FROM dw.dim_order o LEFT JOIN (SELECT order_key,count(*) item_count,sum(price) item_price,sum(freight_value) freight,sum(total_item_value) gmv FROM dw.fact_order_items GROUP BY order_key) i USING(order_key)
LEFT JOIN (SELECT order_key,sum(payment_value) payment_total FROM dw.fact_order_payments GROUP BY order_key) p USING(order_key);
DROP MATERIALIZED VIEW IF EXISTS dw.mv_monthly_kpis;
CREATE MATERIALIZED VIEW dw.mv_monthly_kpis AS
SELECT date_trunc('month',purchase_timestamp)::date month,count(*) FILTER(WHERE order_status NOT IN ('canceled','unavailable')) order_count,sum(gmv) FILTER(WHERE order_status NOT IN ('canceled','unavailable')) gmv,avg(latest_review_score) avg_review_score,count(*) FILTER(WHERE is_on_time) on_time_orders,count(*) FILTER(WHERE is_delivered) delivered_orders
FROM dw.v_order_metrics GROUP BY 1;
CREATE UNIQUE INDEX ix_mv_monthly_kpis ON dw.mv_monthly_kpis(month);
DROP MATERIALIZED VIEW IF EXISTS dw.mv_regional_metrics;
CREATE MATERIALIZED VIEW dw.mv_regional_metrics AS
SELECT c.state,count(*) FILTER(WHERE o.order_status NOT IN ('canceled','unavailable')) order_count,sum(o.gmv) FILTER(WHERE o.order_status NOT IN ('canceled','unavailable')) gmv,avg(o.delivery_lead_time_days) avg_delivery_days FROM dw.v_order_metrics o JOIN dw.dim_customer c USING(customer_key) GROUP BY c.state;
CREATE UNIQUE INDEX ix_mv_regional_metrics ON dw.mv_regional_metrics(state);
