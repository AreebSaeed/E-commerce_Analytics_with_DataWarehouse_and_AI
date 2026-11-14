\set ON_ERROR_STOP on

-- One row per real order. Aggregate items and payments BEFORE joining them.
CREATE OR REPLACE VIEW dw.v_order_metrics AS
SELECT o.order_key, o.order_id, o.order_status, o.customer_key,
    o.purchase_timestamp, o.purchase_date_key, o.is_delivered, o.is_on_time,
    o.delivery_lead_time_days, o.delivery_delay_days, o.latest_review_score,
    coalesce(i.item_count,0) AS item_count,
    coalesce(i.item_price,0) AS item_price,
    coalesce(i.freight,0) AS freight,
    coalesce(i.gmv,0) AS gmv,
    coalesce(p.payment_total,0) AS payment_total
FROM dw.dim_order o
LEFT JOIN (
    SELECT order_key, count(*) AS item_count, sum(price) AS item_price,
        sum(freight_value) AS freight, sum(total_item_value) AS gmv
    FROM dw.fact_order_items GROUP BY order_key
) i USING(order_key)
LEFT JOIN (
    SELECT order_key, sum(payment_value) AS payment_total
    FROM dw.fact_order_payments GROUP BY order_key
) p USING(order_key)
WHERE o.order_key <> 0;

-- Overall cards. Financial metrics exclude canceled/unavailable orders.
-- Delivery/review metrics cover all real orders, matching the monthly summary.
CREATE OR REPLACE VIEW dw.v_sales_kpis AS
SELECT
    count(*) FILTER (WHERE order_status NOT IN ('canceled','unavailable')) AS order_count,
    coalesce(sum(gmv) FILTER (WHERE order_status NOT IN ('canceled','unavailable')),0) AS gmv,
    round(sum(gmv) FILTER (WHERE order_status NOT IN ('canceled','unavailable'))
        / nullif(count(*) FILTER (WHERE order_status NOT IN ('canceled','unavailable')),0),2) AS aov,
    count(*) FILTER (WHERE is_delivered) AS delivered_orders,
    count(*) FILTER (WHERE is_on_time) AS on_time_orders,
    round(100.0 * count(*) FILTER (WHERE is_on_time)
        / nullif(count(*) FILTER (WHERE is_delivered),0),2) AS on_time_delivery_pct,
    round(avg(latest_review_score),2) AS avg_review_score,
    round(100.0 * sum(freight) FILTER (WHERE order_status NOT IN ('canceled','unavailable'))
        / nullif(sum(item_price) FILTER (WHERE order_status NOT IN ('canceled','unavailable')),0),2) AS freight_to_price_pct
FROM dw.v_order_metrics;

-- Keep existing summaries and their indexes; refresh their contents below.
CREATE MATERIALIZED VIEW IF NOT EXISTS dw.mv_monthly_kpis AS
SELECT date_trunc('month',purchase_timestamp)::date AS month,
    count(*) FILTER (WHERE order_status NOT IN ('canceled','unavailable')) AS order_count,
    sum(gmv) FILTER (WHERE order_status NOT IN ('canceled','unavailable')) AS gmv,
    avg(latest_review_score) AS avg_review_score,
    count(*) FILTER (WHERE is_on_time) AS on_time_orders,
    count(*) FILTER (WHERE is_delivered) AS delivered_orders
FROM dw.v_order_metrics GROUP BY 1;
CREATE UNIQUE INDEX IF NOT EXISTS ix_mv_monthly_kpis ON dw.mv_monthly_kpis(month);

-- A small presentation view adds ratios without replacing the stored summary.
CREATE OR REPLACE VIEW dw.v_monthly_kpis AS
SELECT month, order_count, coalesce(gmv,0) AS gmv, avg_review_score,
    on_time_orders, delivered_orders,
    round(gmv / nullif(order_count,0),2) AS aov,
    round(100.0 * on_time_orders / nullif(delivered_orders,0),2) AS on_time_delivery_pct
FROM dw.mv_monthly_kpis;

CREATE MATERIALIZED VIEW IF NOT EXISTS dw.mv_regional_metrics AS
SELECT c.state,
    count(*) FILTER (WHERE o.order_status NOT IN ('canceled','unavailable')) AS order_count,
    sum(o.gmv) FILTER (WHERE o.order_status NOT IN ('canceled','unavailable')) AS gmv,
    avg(o.delivery_lead_time_days) AS avg_delivery_days
FROM dw.v_order_metrics o JOIN dw.dim_customer c USING(customer_key)
GROUP BY c.state;
CREATE UNIQUE INDEX IF NOT EXISTS ix_mv_regional_metrics ON dw.mv_regional_metrics(state);

-- Ordinary views over stored summaries are easy to select in BI connectors.
CREATE OR REPLACE VIEW dw.v_regional_metrics AS
SELECT state, order_count, gmv, avg_delivery_days
FROM dw.mv_regional_metrics;

-- Grain: purchase month + product category + seller.
-- GMV and item counts are additive; distinct order counts across groups are not.
CREATE MATERIALIZED VIEW IF NOT EXISTS dw.mv_category_seller_metrics AS
SELECT date_trunc('month',o.purchase_timestamp)::date AS month,
    c.category_key, c.category_name_en, c.macro_department,
    s.seller_key, s.seller_id, s.state AS seller_state,
    count(*) AS item_count, count(DISTINCT o.order_key) AS order_count,
    sum(i.price) AS item_price, sum(i.freight_value) AS freight,
    sum(i.total_item_value) AS gmv,
    round(sum(i.total_item_value) / nullif(count(DISTINCT o.order_key),0),2) AS gmv_per_order,
    round(100.0 * sum(i.freight_value) / nullif(sum(i.price),0),2) AS freight_to_price_pct
FROM dw.fact_order_items i
JOIN dw.dim_order o USING(order_key)
JOIN dw.dim_product p USING(product_key)
JOIN dw.dim_product_category c USING(category_key)
JOIN dw.dim_seller s USING(seller_key)
WHERE o.order_key <> 0 AND o.order_status NOT IN ('canceled','unavailable')
GROUP BY 1, c.category_key, c.category_name_en, c.macro_department,
    s.seller_key, s.seller_id, s.state;
CREATE UNIQUE INDEX IF NOT EXISTS ix_mv_category_seller_metrics
ON dw.mv_category_seller_metrics(month,category_key,seller_key);

CREATE OR REPLACE VIEW dw.v_category_seller_metrics AS
SELECT month, category_key, category_name_en, macro_department,
    seller_key, seller_id, seller_state, item_count, order_count,
    item_price, freight, gmv, gmv_per_order, freight_to_price_pct
FROM dw.mv_category_seller_metrics;

-- Payments are summarized directly; no join to item-grain facts.
-- An order using two methods appears once in each method's order count.
CREATE OR REPLACE VIEW dw.v_payment_method_metrics AS
WITH methods AS (
    SELECT date_trunc('month',o.purchase_timestamp)::date AS month,
        coalesce(nullif(p.payment_type,''),'Unknown') AS payment_type,
        count(*) AS payment_rows, count(DISTINCT o.order_key) AS order_count,
        sum(p.payment_value) AS payment_total,
        round(avg(p.payment_installments),2) AS avg_installments
    FROM dw.fact_order_payments p JOIN dw.dim_order o USING(order_key)
    WHERE o.order_key <> 0 AND o.order_status NOT IN ('canceled','unavailable')
    GROUP BY 1, 2
)
SELECT methods.*,
    round(100.0 * payment_total / nullif(sum(payment_total) OVER (PARTITION BY month),0),2) AS payment_share_pct
FROM methods;

INSERT INTO meta.data_dictionary VALUES
 ('Freight-to-price percentage','100 * sum(freight) / sum(item price) for eligible orders; NULL when item price totals zero.'),
 ('Payment method share','Percentage of eligible payment value in a purchase month; order counts overlap when orders use multiple methods. Installment averages are per payment row.'),
 ('Category seller summary','One row per purchase month, category and seller. GMV is additive; distinct order counts and ratios must not be summed across groups.'),
 ('Reporting percentages','Percentage columns use 0-100. Undefined ratios use NULL. Delivery/review metrics include all real orders; financial metrics exclude canceled/unavailable orders.')
ON CONFLICT(metric_name) DO UPDATE SET definition=excluded.definition;

\ir 06_refresh_views.sql
\ir 07_ml_features.sql
