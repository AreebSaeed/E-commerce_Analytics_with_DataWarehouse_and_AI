\set ON_ERROR_STOP on
-- Fail the run on mismatches; placeholder dimension rows are not source entities.
CREATE TEMP TABLE warehouse_row_checks AS
SELECT 'orders' AS entity,(SELECT count(*) FROM staging.orders) AS source_rows,(SELECT count(*) FROM dw.dim_order WHERE order_key<>0) AS warehouse_rows
UNION ALL SELECT 'items',(SELECT count(*) FROM staging.order_items),(SELECT count(*) FROM dw.fact_order_items)
UNION ALL SELECT 'payments',(SELECT count(*) FROM staging.order_payments),(SELECT count(*) FROM dw.fact_order_payments)
UNION ALL SELECT 'customers',(SELECT count(*) FROM staging.customers),(SELECT count(*) FROM dw.dim_customer WHERE customer_key<>0)
UNION ALL SELECT 'sellers',(SELECT count(*) FROM staging.sellers),(SELECT count(*) FROM dw.dim_seller WHERE seller_key<>0)
UNION ALL SELECT 'products',(SELECT count(*) FROM staging.products),(SELECT count(*) FROM dw.dim_product WHERE product_key<>0)
UNION ALL SELECT 'categories',(SELECT count(DISTINCT nullif(btrim(product_category_name),'')) FROM staging.products),(SELECT count(*) FROM dw.dim_product_category WHERE category_key<>0)
UNION ALL SELECT 'order reporting',(SELECT count(*) FROM staging.orders),(SELECT count(*) FROM dw.v_order_metrics)
UNION ALL SELECT 'delivery features',(SELECT count(*) FROM staging.orders),(SELECT count(*) FROM dw.v_delivery_features)
UNION ALL SELECT 'customer features',
    (SELECT count(DISTINCT customer_unique_id) FROM dw.dim_customer
      WHERE customer_key<>0 AND nullif(btrim(customer_unique_id),'') IS NOT NULL),
    (SELECT count(*) FROM dw.v_customer_features)
UNION ALL SELECT 'regional BI view',
    (SELECT count(*) FROM dw.mv_regional_metrics),
    (SELECT count(*) FROM dw.v_regional_metrics)
UNION ALL SELECT 'category/seller BI view',
    (SELECT count(*) FROM dw.mv_category_seller_metrics),
    (SELECT count(*) FROM dw.v_category_seller_metrics);

CREATE TEMP TABLE warehouse_money_checks AS
SELECT 'item price' AS metric,
    coalesce((SELECT sum(price::numeric) FROM staging.order_items),0) AS source_total,
    coalesce((SELECT sum(price) FROM dw.fact_order_items),0) AS warehouse_total
UNION ALL SELECT 'freight',coalesce((SELECT sum(freight_value::numeric) FROM staging.order_items),0),coalesce((SELECT sum(freight_value) FROM dw.fact_order_items),0)
UNION ALL SELECT 'item total',coalesce((SELECT sum(price::numeric+freight_value::numeric) FROM staging.order_items),0),coalesce((SELECT sum(total_item_value) FROM dw.fact_order_items),0)
UNION ALL SELECT 'payments',coalesce((SELECT sum(payment_value::numeric) FROM staging.order_payments),0),coalesce((SELECT sum(payment_value) FROM dw.fact_order_payments),0)
UNION ALL SELECT 'monthly eligible GMV',
    coalesce((SELECT sum(i.price::numeric+i.freight_value::numeric) FROM staging.order_items i JOIN staging.orders o USING(order_id) WHERE o.order_status NOT IN ('canceled','unavailable')),0),
    coalesce((SELECT sum(gmv) FROM dw.mv_monthly_kpis),0)
UNION ALL SELECT 'regional eligible GMV',
    coalesce((SELECT sum(i.price::numeric+i.freight_value::numeric) FROM staging.order_items i JOIN staging.orders o USING(order_id) WHERE o.order_status NOT IN ('canceled','unavailable')),0),
    coalesce((SELECT sum(gmv) FROM dw.mv_regional_metrics),0)
UNION ALL SELECT 'category/seller eligible GMV',
    coalesce((SELECT sum(i.price::numeric+i.freight_value::numeric) FROM staging.order_items i JOIN staging.orders o USING(order_id) WHERE o.order_status NOT IN ('canceled','unavailable')),0),
    coalesce((SELECT sum(gmv) FROM dw.mv_category_seller_metrics),0)
UNION ALL SELECT 'payment method totals',
    coalesce((SELECT sum(p.payment_value::numeric) FROM staging.order_payments p JOIN staging.orders o USING(order_id) WHERE o.order_status NOT IN ('canceled','unavailable')),0),
    coalesce((SELECT sum(payment_total) FROM dw.v_payment_method_metrics),0)
UNION ALL SELECT 'headline eligible GMV',
    coalesce((SELECT sum(i.price::numeric+i.freight_value::numeric) FROM staging.order_items i JOIN staging.orders o USING(order_id) WHERE o.order_status NOT IN ('canceled','unavailable')),0),
    (SELECT gmv FROM dw.v_sales_kpis)
UNION ALL SELECT 'regional BI GMV',
    coalesce((SELECT sum(gmv) FROM dw.mv_regional_metrics),0),
    coalesce((SELECT sum(gmv) FROM dw.v_regional_metrics),0)
UNION ALL SELECT 'category/seller BI GMV',
    coalesce((SELECT sum(gmv) FROM dw.mv_category_seller_metrics),0),
    coalesce((SELECT sum(gmv) FROM dw.v_category_seller_metrics),0);

CREATE TEMP TABLE warehouse_unknown_counts (
    reference_name text, unknown_rows bigint, null_rows bigint
);
DO $$
DECLARE ref record; n bigint;
BEGIN
    IF EXISTS (SELECT 1 FROM warehouse_row_checks WHERE source_rows<>warehouse_rows) THEN
        RAISE EXCEPTION 'Source/warehouse row counts do not match';
    END IF;
    IF EXISTS (SELECT 1 FROM warehouse_money_checks WHERE source_total<>warehouse_total) THEN
        RAISE EXCEPTION 'Source/warehouse financial totals do not match';
    END IF;
    FOR ref IN SELECT * FROM (VALUES
        ('dim_date','date_key'),('dim_geolocation','geo_key'),
        ('dim_product_category','category_key'),('dim_customer','customer_key'),
        ('dim_seller','seller_key'),('dim_product','product_key'),('dim_order','order_key')
    ) AS dims(table_name,key_name) LOOP
        EXECUTE format('SELECT count(*) FROM dw.%I WHERE %I=0',ref.table_name,ref.key_name) INTO n;
        IF n<>1 THEN RAISE EXCEPTION 'Missing unknown member in %',ref.table_name; END IF;
    END LOOP;
    FOR ref IN SELECT * FROM (VALUES
        ('dim_customer','geo_key','customer_key<>0'),('dim_seller','geo_key','seller_key<>0'),
        ('dim_product','category_key','product_key<>0'),('dim_order','customer_key','order_key<>0'),
        ('dim_order','purchase_date_key','order_key<>0'),('dim_order','delivered_date_key','order_key<>0'),
        ('dim_order','estimated_date_key','order_key<>0'),('fact_order_items','order_key','true'),
        ('fact_order_items','product_key','true'),('fact_order_items','seller_key','true'),
        ('fact_order_payments','order_key','true')
    ) AS refs(table_name,column_name,predicate) LOOP
        EXECUTE format(
            'INSERT INTO warehouse_unknown_counts SELECT %L, count(*) FILTER (WHERE %I=0), count(*) FILTER (WHERE %I IS NULL) FROM dw.%I WHERE %s',
            ref.table_name||'.'||ref.column_name,ref.column_name,ref.column_name,ref.table_name,ref.predicate);
    END LOOP;
    IF EXISTS (SELECT 1 FROM warehouse_unknown_counts WHERE null_rows<>0) THEN
        RAISE EXCEPTION 'NULL foreign key found instead of unknown member';
    END IF;
    IF EXISTS (SELECT 1 FROM dw.dim_date WHERE date_key=0 AND calendar_date IS NOT NULL)
       OR EXISTS (SELECT 1 FROM dw.dim_geolocation WHERE geo_key=0 AND (latitude IS NOT NULL OR longitude IS NOT NULL OR geo_point IS NOT NULL)) THEN
        RAISE EXCEPTION 'Unknown member contains an invented date/location';
    END IF;
    IF EXISTS (SELECT 1 FROM dw.v_order_metrics WHERE order_key=0) THEN
        RAISE EXCEPTION 'Placeholder order leaked into reporting';
    END IF;
    IF EXISTS (SELECT 1 FROM dw.dim_order WHERE order_key<>0 AND delivered_timestamp IS NULL
        AND (delivered_date_key<>0 OR is_delivered OR is_on_time IS NOT NULL OR delivery_delay_days IS NOT NULL OR delivery_lead_time_days IS NOT NULL)) THEN
        RAISE EXCEPTION 'Missing delivery date handled incorrectly';
    END IF;
    IF EXISTS (SELECT 1 FROM staging.products s JOIN dw.dim_product p USING(product_id)
        WHERE nullif(btrim(s.product_category_name),'') IS NULL AND p.category_key<>0) THEN
        RAISE EXCEPTION 'Missing product category did not map to key 0';
    END IF;
    IF EXISTS (SELECT 1 FROM dw.dim_product_category c
        LEFT JOIN meta.category_departments m USING(category_name_pt)
        WHERE c.macro_department IS DISTINCT FROM
            CASE WHEN c.category_key=0 THEN 'Unknown' ELSE coalesce(m.macro_department,'Other') END) THEN
        RAISE EXCEPTION 'Incorrect category department';
    END IF;
    IF EXISTS (SELECT 1 FROM dw.fact_order_items f LEFT JOIN dw.dim_order o ON o.order_id=f.source_order_id
        WHERE f.order_key IS DISTINCT FROM coalesce(o.order_key,0))
       OR EXISTS (SELECT 1 FROM dw.fact_order_payments f LEFT JOIN dw.dim_order o ON o.order_id=f.source_order_id
        WHERE f.order_key IS DISTINCT FROM coalesce(o.order_key,0)) THEN
        RAISE EXCEPTION 'Fact source order and surrogate reference disagree';
    END IF;
END $$;

TABLE warehouse_row_checks;
TABLE warehouse_money_checks;
TABLE warehouse_unknown_counts;
SELECT count(*) AS distinct_geographic_prefixes FROM dw.dim_geolocation WHERE geo_key<>0;
SELECT count(*) AS orders_with_multiple_payment_rows
FROM (SELECT source_order_id FROM dw.fact_order_payments GROUP BY source_order_id HAVING count(*)>1) x;
SELECT macro_department, count(*) AS category_count
FROM dw.dim_product_category GROUP BY macro_department ORDER BY macro_department;
DROP TABLE warehouse_row_checks, warehouse_money_checks, warehouse_unknown_counts;
