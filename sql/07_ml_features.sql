\set ON_ERROR_STOP on

-- One row per order. Only identifiers, purchase-time facts, and features appear here.
-- The highest-value seller represents a multi-seller order for state/distance.
CREATE OR REPLACE VIEW dw.v_delivery_features AS
WITH item_features AS (
    SELECT i.order_key, count(*) AS item_count,
        sum(i.price) AS item_price,
        sum(i.freight_value) AS freight_value,
        sum(p.weight_g) AS total_weight_g,
        count(*) FILTER (WHERE p.weight_g IS NOT NULL) AS weight_known_items,
        sum(p.length_cm * p.height_cm * p.width_cm) AS total_volume_cm3,
        count(*) FILTER (WHERE p.length_cm IS NOT NULL
            AND p.height_cm IS NOT NULL AND p.width_cm IS NOT NULL) AS volume_known_items
    FROM dw.fact_order_items i
    JOIN dw.dim_product p USING(product_key)
    WHERE i.order_key <> 0
    GROUP BY i.order_key
), seller_ranked AS (
    SELECT order_key, seller_key,
        row_number() OVER (PARTITION BY order_key
            ORDER BY sum(total_item_value) DESC NULLS LAST, seller_key) AS seller_rank
    FROM dw.fact_order_items WHERE order_key <> 0
    GROUP BY order_key, seller_key
)
SELECT o.order_id, o.purchase_timestamp,
    extract(month from o.purchase_timestamp)::int AS purchase_month,
    extract(isodow from o.purchase_timestamp)::int AS purchase_weekday,
    coalesce(c.state,'Unknown') AS customer_state,
    coalesce(s.state,'Unknown') AS seller_state,
    coalesce(i.item_count,0) AS item_count,
    i.item_price, i.freight_value, i.total_weight_g,
    coalesce(i.weight_known_items,0) AS weight_known_items,
    i.total_volume_cm3,
    coalesce(i.volume_known_items,0) AS volume_known_items,
    -- Haversine great-circle distance from postal-prefix centroids, in kilometers.
    -- Broad Brazil bounds screen implausible source coordinates; it is not a
    -- state-boundary or precise country-boundary test.
    CASE WHEN cg.latitude BETWEEN -34 AND 6 AND cg.longitude BETWEEN -74 AND -34
           AND sg.latitude BETWEEN -34 AND 6 AND sg.longitude BETWEEN -74 AND -34 THEN
        2 * 6371.0088 * asin(sqrt(least(1.0,
            power(sin(radians(cg.latitude - sg.latitude) / 2), 2) +
            cos(radians(cg.latitude)) * cos(radians(sg.latitude)) *
            power(sin(radians(cg.longitude - sg.longitude) / 2), 2))))
    END AS seller_customer_distance_km
FROM dw.dim_order o
JOIN dw.dim_customer c USING(customer_key)
JOIN dw.dim_geolocation cg ON cg.geo_key = c.geo_key
LEFT JOIN item_features i USING(order_key)
LEFT JOIN seller_ranked sr ON sr.order_key = o.order_key AND sr.seller_rank = 1
LEFT JOIN dw.dim_seller s ON s.seller_key = sr.seller_key
LEFT JOIN dw.dim_geolocation sg ON sg.geo_key = s.geo_key
WHERE o.order_key <> 0;

-- The outcome lives only in this training view. It is never a predictor column
-- in v_delivery_features. Unfinished orders cannot have an observed label.
CREATE OR REPLACE VIEW dw.v_delivery_training AS
SELECT f.*, (o.delivered_timestamp > o.estimated_delivery_timestamp) AS label_is_late
FROM dw.v_delivery_features f
JOIN dw.dim_order o USING(order_id)
WHERE o.is_delivered = true
  AND o.purchase_timestamp IS NOT NULL
  AND o.estimated_delivery_timestamp IS NOT NULL
  AND o.order_status NOT IN ('canceled','unavailable');

-- One row per permanent buyer ID. Use the latest date IN THE DATASET as the
-- reference date, so the historical recency measure does not drift each day.
-- Only eligible orders contribute; the existing order view prevents item/payment fan-out.
CREATE OR REPLACE VIEW dw.v_customer_features AS
WITH eligible_orders AS (
    SELECT c.customer_unique_id, o.order_id, o.purchase_timestamp,
        o.gmv, o.latest_review_score, o.delivery_delay_days
    FROM dw.v_order_metrics o
    JOIN dw.dim_customer c USING(customer_key)
    WHERE o.order_status NOT IN ('canceled','unavailable')
      AND o.purchase_timestamp IS NOT NULL
), reference_date AS (
    SELECT max(purchase_timestamp)::date AS as_of_date FROM eligible_orders
)
SELECT c.customer_unique_id, r.as_of_date,
    max(e.purchase_timestamp)::date AS last_purchase_date,
    r.as_of_date - max(e.purchase_timestamp)::date AS recency_days,
    count(DISTINCT e.order_id) AS frequency_orders,
    coalesce(sum(e.gmv),0) AS monetary_gmv,
    ln(1 + greatest(coalesce(sum(e.gmv),0),0)) AS log_monetary_gmv,
    avg(e.latest_review_score) AS avg_review_score,
    avg(e.delivery_delay_days) AS avg_delivery_delay_days
FROM (SELECT DISTINCT customer_unique_id FROM dw.dim_customer
      WHERE customer_key <> 0 AND nullif(btrim(customer_unique_id),'') IS NOT NULL) c
CROSS JOIN reference_date r
LEFT JOIN eligible_orders e USING(customer_unique_id)
GROUP BY c.customer_unique_id, r.as_of_date;

INSERT INTO meta.data_dictionary VALUES
 ('Delivery features','One row per real order. Seller state and Haversine distance use the seller with the largest item total; ties use seller key. Missing or out-of-range coordinates yield NULL distance.'),
 ('Delivery training label','label_is_late is delivered timestamp after estimated timestamp; only delivered, estimable, eligible orders are labeled. Never pass the label or delivery/review fields as predictor inputs.'),
 ('Customer recency','Days since the latest eligible purchase, measured from the latest eligible purchase date in the dataset. Customers with no eligible purchases have NULL recency.'),
 ('Customer frequency and monetary','Distinct eligible orders with a purchase timestamp, and sum of their order-level GMV. log_monetary_gmv is natural log(1 + nonnegative GMV).')
ON CONFLICT(metric_name) DO UPDATE SET definition=excluded.definition;
