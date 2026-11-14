-- Called inside a transaction by 03_transform.sql and the rollback-only tests.
TRUNCATE dw.fact_order_items, dw.fact_order_payments, dw.dim_order,
    dw.dim_customer, dw.dim_seller, dw.dim_product, dw.dim_product_category,
    dw.dim_geolocation, dw.dim_date RESTART IDENTITY CASCADE;
\ir category_departments.sql

-- NULL natural identifiers cannot collide with real source identifiers.
-- Unknown dates/coordinates stay NULL; no artificial date or location is used.
INSERT INTO dw.dim_date(date_key) VALUES (0);
INSERT INTO dw.dim_geolocation(geo_key, city, state) VALUES (0, 'Unknown', 'Unknown');
INSERT INTO dw.dim_product_category(category_key, category_name_en, macro_department)
VALUES (0, 'Unknown', 'Unknown');
INSERT INTO dw.dim_customer(customer_key, geo_key, city, state) VALUES (0, 0, 'Unknown', 'Unknown');
INSERT INTO dw.dim_seller(seller_key, geo_key, city, state) VALUES (0, 0, 'Unknown', 'Unknown');
INSERT INTO dw.dim_product(product_key, category_key) VALUES (0, 0);
INSERT INTO dw.dim_order(order_key, customer_key, order_status, purchase_date_key,
    delivered_date_key, estimated_date_key, is_delivered)
VALUES (0, 0, 'Unknown', 0, 0, 0, false);

INSERT INTO dw.dim_date
SELECT to_char(d,'YYYYMMDD')::integer, d, extract(year from d)::integer,
    extract(quarter from d)::integer, extract(month from d)::integer, extract(day from d)::integer
FROM generate_series(date '2016-01-01',date '2019-12-31',interval '1 day') AS d;

INSERT INTO dw.dim_geolocation(zip_prefix,city,state,latitude,longitude,geo_point)
SELECT geolocation_zip_code_prefix, min(geolocation_city), min(geolocation_state),
    avg(geolocation_lat::double precision), avg(geolocation_lng::double precision),
    point(avg(geolocation_lng::double precision),avg(geolocation_lat::double precision))
FROM staging.geolocation
WHERE geolocation_lat ~ '^-?[0-9]+(\.[0-9]+)?$'
  AND geolocation_lng ~ '^-?[0-9]+(\.[0-9]+)?$'
  AND nullif(btrim(geolocation_zip_code_prefix),'') IS NOT NULL
GROUP BY geolocation_zip_code_prefix;

INSERT INTO dw.dim_product_category(category_name_pt,category_name_en,macro_department)
SELECT DISTINCT btrim(p.product_category_name),
    coalesce(nullif(btrim(t.product_category_name_english),''),btrim(p.product_category_name)),
    coalesce(m.macro_department,'Other')
FROM staging.products p
LEFT JOIN staging.category_translation t ON t.product_category_name = btrim(p.product_category_name)
LEFT JOIN meta.category_departments m ON m.category_name_pt = btrim(p.product_category_name)
WHERE nullif(btrim(p.product_category_name),'') IS NOT NULL;

INSERT INTO dw.dim_customer(customer_id,customer_unique_id,geo_key,city,state)
SELECT c.customer_id,c.customer_unique_id,coalesce(g.geo_key,0),c.customer_city,c.customer_state
FROM staging.customers c LEFT JOIN dw.dim_geolocation g ON g.zip_prefix=c.customer_zip_code_prefix;
INSERT INTO dw.dim_seller(seller_id,geo_key,city,state)
SELECT s.seller_id,coalesce(g.geo_key,0),s.seller_city,s.seller_state
FROM staging.sellers s LEFT JOIN dw.dim_geolocation g ON g.zip_prefix=s.seller_zip_code_prefix;
INSERT INTO dw.dim_product(product_id,category_key,weight_g,length_cm,height_cm,width_cm)
SELECT p.product_id,coalesce(c.category_key,0),nullif(p.product_weight_g,'')::numeric,
    nullif(p.product_length_cm,'')::numeric,nullif(p.product_height_cm,'')::numeric,
    nullif(p.product_width_cm,'')::numeric
FROM staging.products p
LEFT JOIN dw.dim_product_category c ON c.category_name_pt=nullif(btrim(p.product_category_name),'');

WITH latest_review AS (
    SELECT DISTINCT ON(order_id) order_id,nullif(review_score,'')::integer AS review_score
    FROM staging.order_reviews ORDER BY order_id,review_creation_date DESC NULLS LAST,review_id DESC
), orders AS (
    SELECT o.*, nullif(order_purchase_timestamp,'')::timestamp AS purchased,
        nullif(order_delivered_customer_date,'')::timestamp AS delivered,
        nullif(order_estimated_delivery_date,'')::timestamp AS estimated
    FROM staging.orders o
)
INSERT INTO dw.dim_order(order_id,customer_key,order_status,purchase_timestamp,
    delivered_timestamp,estimated_delivery_timestamp,purchase_date_key,delivered_date_key,
    estimated_date_key,is_delivered,delivery_lead_time_days,delivery_delay_days,is_on_time,latest_review_score)
SELECT o.order_id,coalesce(c.customer_key,0),o.order_status,o.purchased,o.delivered,o.estimated,
    coalesce(pd.date_key,0),coalesce(dd.date_key,0),coalesce(ed.date_key,0),o.delivered IS NOT NULL,
    extract(epoch from (o.delivered-o.purchased))/86400,
    extract(epoch from (o.delivered-o.estimated))/86400,
    CASE WHEN o.delivered IS NULL THEN NULL ELSE o.delivered<=o.estimated END,r.review_score
FROM orders o
LEFT JOIN dw.dim_customer c USING(customer_id)
LEFT JOIN latest_review r USING(order_id)
LEFT JOIN dw.dim_date pd ON pd.calendar_date=o.purchased::date
LEFT JOIN dw.dim_date dd ON dd.calendar_date=o.delivered::date
LEFT JOIN dw.dim_date ed ON ed.calendar_date=o.estimated::date;

INSERT INTO dw.fact_order_items(source_order_id,order_key,order_item_id,product_key,seller_key,price,freight_value,total_item_value)
SELECT i.order_id,coalesce(o.order_key,0),i.order_item_id::integer,coalesce(p.product_key,0),
    coalesce(s.seller_key,0),i.price::numeric,i.freight_value::numeric,i.price::numeric+i.freight_value::numeric
FROM staging.order_items i
LEFT JOIN dw.dim_order o USING(order_id)
LEFT JOIN dw.dim_product p USING(product_id)
LEFT JOIN dw.dim_seller s USING(seller_id);
INSERT INTO dw.fact_order_payments(source_order_id,order_key,payment_sequential,payment_type,payment_installments,payment_value)
SELECT p.order_id,coalesce(o.order_key,0),p.payment_sequential::integer,p.payment_type,
    nullif(p.payment_installments,'')::integer,p.payment_value::numeric
FROM staging.order_payments p LEFT JOIN dw.dim_order o USING(order_id);

-- Enforce the policy on upgraded databases too, after existing data is rebuilt.
DO $$
DECLARE ref record;
BEGIN
    FOR ref IN SELECT * FROM (VALUES
        ('dim_customer','geo_key'), ('dim_seller','geo_key'), ('dim_product','category_key'),
        ('dim_order','customer_key'), ('dim_order','purchase_date_key'),
        ('dim_order','delivered_date_key'), ('dim_order','estimated_date_key'),
        ('fact_order_items','order_key'), ('fact_order_items','product_key'),
        ('fact_order_items','seller_key'), ('fact_order_payments','order_key')
    ) AS refs(table_name,column_name) LOOP
        EXECUTE format('ALTER TABLE dw.%I ALTER COLUMN %I SET DEFAULT 0, ALTER COLUMN %I SET NOT NULL',
            ref.table_name,ref.column_name,ref.column_name);
    END LOOP;
END $$;

INSERT INTO meta.data_dictionary VALUES
 ('GMV','Sum of item price plus freight for orders excluding canceled and unavailable'),
 ('AOV','GMV divided by count of distinct eligible orders'),
 ('On-time delivery rate','Delivered orders with actual delivery timestamp on or before estimated timestamp divided by delivered orders'),
 ('Unknown member','Surrogate key 0 in every dimension; missing references map to 0. Date and coordinate attributes remain NULL. Exclude placeholder dimensions from entity counts.'),
 ('Macro department','Project-defined category grouping from meta.category_departments. Missing category = Unknown; unmapped nonblank category = Other.'),
 ('Orphan facts','Source order IDs preserve item/payment grain when order_key = 0. Included in fact reconciliation but excluded from order-level reporting until the order exists.')
ON CONFLICT(metric_name) DO UPDATE SET definition=excluded.definition;
INSERT INTO meta.etl_log(completed_at,status,source_orders,loaded_orders,loaded_items,loaded_payments,notes)
SELECT now(),'success',(SELECT count(*) FROM staging.orders),
    (SELECT count(*) FROM dw.dim_order WHERE order_key<>0),
    (SELECT count(*) FROM dw.fact_order_items),(SELECT count(*) FROM dw.fact_order_payments),
    CASE WHEN (SELECT count(*) FROM staging.geolocation)=0 THEN 'Geolocation file absent' ELSE NULL END;
