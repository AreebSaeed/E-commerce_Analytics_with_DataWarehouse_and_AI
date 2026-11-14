\set ON_ERROR_STOP on
BEGIN;
TRUNCATE dw.fact_order_items, dw.fact_order_payments, dw.dim_order, dw.dim_customer, dw.dim_seller, dw.dim_product, dw.dim_product_category, dw.dim_geolocation, dw.dim_date RESTART IDENTITY CASCADE;
INSERT INTO dw.dim_date SELECT to_char(d,'YYYYMMDD')::integer,d,extract(year from d)::integer,extract(quarter from d)::integer,extract(month from d)::integer,extract(day from d)::integer FROM generate_series(date '2016-01-01',date '2019-12-31',interval '1 day') AS d;
INSERT INTO dw.dim_geolocation(zip_prefix,city,state,latitude,longitude,geo_point)
SELECT geolocation_zip_code_prefix,min(geolocation_city),min(geolocation_state),avg(geolocation_lat::double precision),avg(geolocation_lng::double precision),point(avg(geolocation_lng::double precision),avg(geolocation_lat::double precision))
FROM staging.geolocation WHERE geolocation_lat ~ '^-?[0-9]+(\.[0-9]+)?$' AND geolocation_lng ~ '^-?[0-9]+(\.[0-9]+)?$' GROUP BY geolocation_zip_code_prefix;
INSERT INTO dw.dim_product_category(category_name_pt,category_name_en)
SELECT DISTINCT p.product_category_name,coalesce(t.product_category_name_english,p.product_category_name,'unknown') FROM staging.products p LEFT JOIN staging.category_translation t USING(product_category_name) WHERE p.product_category_name IS NOT NULL;
INSERT INTO dw.dim_customer(customer_id,customer_unique_id,geo_key,city,state)
SELECT c.customer_id,c.customer_unique_id,g.geo_key,c.customer_city,c.customer_state FROM staging.customers c LEFT JOIN dw.dim_geolocation g ON g.zip_prefix=c.customer_zip_code_prefix;
INSERT INTO dw.dim_seller(seller_id,geo_key,city,state)
SELECT s.seller_id,g.geo_key,s.seller_city,s.seller_state FROM staging.sellers s LEFT JOIN dw.dim_geolocation g ON g.zip_prefix=s.seller_zip_code_prefix;
INSERT INTO dw.dim_product(product_id,category_key,weight_g,length_cm,height_cm,width_cm)
SELECT p.product_id,c.category_key,nullif(p.product_weight_g,'')::numeric,nullif(p.product_length_cm,'')::numeric,nullif(p.product_height_cm,'')::numeric,nullif(p.product_width_cm,'')::numeric FROM staging.products p LEFT JOIN dw.dim_product_category c ON c.category_name_pt=p.product_category_name;
WITH latest_review AS (SELECT DISTINCT ON(order_id) order_id,nullif(review_score,'')::integer AS review_score FROM staging.order_reviews ORDER BY order_id,review_creation_date DESC NULLS LAST,review_id DESC)
INSERT INTO dw.dim_order(order_id,customer_key,order_status,purchase_timestamp,delivered_timestamp,estimated_delivery_timestamp,purchase_date_key,delivered_date_key,estimated_date_key,is_delivered,delivery_lead_time_days,delivery_delay_days,is_on_time,latest_review_score)
SELECT o.order_id,c.customer_key,o.order_status,nullif(o.order_purchase_timestamp,'')::timestamp,nullif(o.order_delivered_customer_date,'')::timestamp,nullif(o.order_estimated_delivery_date,'')::timestamp,to_char(nullif(o.order_purchase_timestamp,'')::timestamp,'YYYYMMDD')::integer,to_char(nullif(o.order_delivered_customer_date,'')::timestamp,'YYYYMMDD')::integer,to_char(nullif(o.order_estimated_delivery_date,'')::timestamp,'YYYYMMDD')::integer,o.order_delivered_customer_date IS NOT NULL AND o.order_delivered_customer_date<>'',extract(epoch from (nullif(o.order_delivered_customer_date,'')::timestamp-nullif(o.order_purchase_timestamp,'')::timestamp))/86400,extract(epoch from (nullif(o.order_delivered_customer_date,'')::timestamp-nullif(o.order_estimated_delivery_date,'')::timestamp))/86400,CASE WHEN nullif(o.order_delivered_customer_date,'') IS NULL THEN NULL ELSE nullif(o.order_delivered_customer_date,'')::timestamp<=nullif(o.order_estimated_delivery_date,'')::timestamp END,r.review_score
FROM staging.orders o LEFT JOIN dw.dim_customer c USING(customer_id) LEFT JOIN latest_review r USING(order_id);
INSERT INTO dw.fact_order_items(order_key,order_item_id,product_key,seller_key,price,freight_value,total_item_value)
SELECT o.order_key,i.order_item_id::integer,p.product_key,s.seller_key,i.price::numeric,i.freight_value::numeric,i.price::numeric+i.freight_value::numeric FROM staging.order_items i JOIN dw.dim_order o USING(order_id) LEFT JOIN dw.dim_product p USING(product_id) LEFT JOIN dw.dim_seller s USING(seller_id);
INSERT INTO dw.fact_order_payments(order_key,payment_sequential,payment_type,payment_installments,payment_value)
SELECT o.order_key,p.payment_sequential::integer,p.payment_type,nullif(p.payment_installments,'')::integer,p.payment_value::numeric FROM staging.order_payments p JOIN dw.dim_order o USING(order_id);
INSERT INTO meta.data_dictionary VALUES ('GMV','Sum of item price plus freight for orders excluding canceled and unavailable'),('AOV','GMV divided by count of distinct eligible orders'),('On-time delivery rate','Delivered orders with actual delivery timestamp on or before estimated timestamp divided by delivered orders') ON CONFLICT(metric_name) DO UPDATE SET definition=excluded.definition;
INSERT INTO meta.etl_log(completed_at,status,source_orders,loaded_orders,loaded_items,loaded_payments,notes) SELECT now(),'success',(SELECT count(*) FROM staging.orders),(SELECT count(*) FROM dw.dim_order),(SELECT count(*) FROM dw.fact_order_items),(SELECT count(*) FROM dw.fact_order_payments),CASE WHEN (SELECT count(*) FROM staging.geolocation)=0 THEN 'Geolocation file absent' ELSE NULL END;
COMMIT;
\i sql/04_views.sql
