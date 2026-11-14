\set ON_ERROR_STOP on
-- Integration fixture: all table changes roll back, including on connection failure.
-- Run after setup. Requires exclusive access while warehouse tables are locked.
BEGIN;
TRUNCATE staging.orders, staging.order_items, staging.order_payments,
    staging.order_reviews, staging.products, staging.customers, staging.sellers,
    staging.geolocation, staging.category_translation;

INSERT INTO staging.geolocation VALUES ('01234','-23.5','-46.6','test city','SP');
INSERT INTO staging.customers VALUES
    ('customer-known','buyer-known','01234','test city','SP'),
    ('customer-no-geo','buyer-no-geo','99999','remote city','RJ');
INSERT INTO staging.sellers VALUES
    ('seller-known','01234','test city','SP'),
    ('seller-no-geo',NULL,'remote city','RJ');
INSERT INTO staging.products(product_id,product_category_name) VALUES
    ('product-known','beleza_saude'),('product-null',NULL),('product-blank','   '),
    ('product-untranslated','pc_gamer'),('product-new','new_unmapped_category');
INSERT INTO staging.category_translation VALUES ('beleza_saude','health_beauty');
INSERT INTO staging.orders(order_id,customer_id,order_status,order_purchase_timestamp,
    order_delivered_customer_date,order_estimated_delivery_date) VALUES
    ('order-known','customer-known','delivered','2018-01-01','2018-01-05','2018-01-06'),
    ('order-no-customer','missing-customer','shipped','2018-01-02',NULL,'2018-01-08'),
    ('order-no-dates','customer-no-geo','created',NULL,'',''),
    ('order-outside-calendar',NULL,'created','2025-01-01',NULL,'2025-01-10'),
    ('order-canceled','customer-known','canceled','2018-01-01',NULL,'2018-01-06');
INSERT INTO staging.order_reviews(review_id,order_id,review_score,review_creation_date) VALUES
    ('review-old','order-known','1','2018-01-06'),('review-new','order-known','5','2018-01-07');
INSERT INTO staging.order_items(order_id,order_item_id,product_id,seller_id,price,freight_value) VALUES
    ('order-known','1','product-known','seller-known','10','2'),
    ('order-known','2','product-null','seller-no-geo','20','3'),
    ('order-no-customer','1','missing-product','missing-seller','30','4'),
    ('orphan-a','1','product-blank','seller-known','40','5'),
    ('orphan-b','1',NULL,NULL,'50','6'),
    ('order-canceled','1','product-new','seller-known','60','7');
INSERT INTO staging.order_payments VALUES
    ('order-known','1','credit_card','1','15'),('order-known','2','voucher','1','20'),
    ('orphan-a','1','credit_card','1','45'),('orphan-b','1','credit_card','1','56'),
    ('order-canceled','1','credit_card','1','67');

\ir ../sql/transform_warehouse.sql
\ir ../sql/04_views.sql
\ir ../sql/05_validate.sql
DO $$
BEGIN
    IF (SELECT count(*) FROM dw.fact_order_items WHERE order_key=0)<>2
       OR (SELECT count(*) FROM dw.fact_order_payments WHERE order_key=0)<>2 THEN
        RAISE EXCEPTION 'Orphan orders with matching sequence numbers were lost';
    END IF;
    IF (SELECT count(*) FROM dw.fact_order_items WHERE product_key=0 AND seller_key=0)<>2 THEN
        RAISE EXCEPTION 'Missing products/sellers did not map to unknown';
    END IF;
    IF (SELECT count(*) FROM dw.dim_product WHERE product_key<>0 AND category_key=0)<>2 THEN
        RAISE EXCEPTION 'NULL and blank categories must both map to unknown';
    END IF;
    IF (SELECT count(*) FROM dw.dim_customer WHERE customer_key<>0 AND geo_key=0)<>1
       OR (SELECT count(*) FROM dw.dim_seller WHERE seller_key<>0 AND geo_key=0)<>1 THEN
        RAISE EXCEPTION 'Missing geography did not map to unknown';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM dw.dim_product_category WHERE category_name_pt='pc_gamer'
        AND category_name_en='pc_gamer' AND macro_department='Electronics & Computing')
       OR NOT EXISTS (SELECT 1 FROM dw.dim_product_category WHERE category_name_pt='new_unmapped_category'
        AND category_name_en='new_unmapped_category' AND macro_department='Other') THEN
        RAISE EXCEPTION 'Translation/department fallback failed';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM dw.dim_order WHERE order_id='order-outside-calendar'
        AND customer_key=0 AND purchase_date_key=0 AND estimated_date_key=0) THEN
        RAISE EXCEPTION 'Missing references/out-of-range dates failed';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM dw.v_order_metrics WHERE order_id='order-known'
        AND item_count=2 AND gmv=35 AND payment_total=35 AND latest_review_score=5)
       OR (SELECT sum(gmv) FROM dw.mv_monthly_kpis)<>69 THEN
        RAISE EXCEPTION 'Reporting totals were inflated or included canceled/orphan orders';
    END IF;
    -- Constraints must still reject duplicate source facts and explicit NULL references.
    BEGIN
        INSERT INTO dw.fact_order_items(source_order_id,order_item_id) VALUES ('orphan-a',1);
        RAISE EXCEPTION 'Duplicate item grain was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO dw.fact_order_payments(source_order_id,payment_sequential) VALUES ('orphan-b',1);
        RAISE EXCEPTION 'Duplicate payment grain was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO dw.dim_product(product_id,category_key) VALUES ('invalid-null-category',NULL);
        RAISE EXCEPTION 'Explicit NULL reference was accepted';
    EXCEPTION WHEN not_null_violation THEN NULL;
    END;
END $$;

-- Repeat the same load to exercise idempotency with NOT NULL/default constraints active.
\ir ../sql/transform_warehouse.sql
\ir ../sql/04_views.sql
\ir ../sql/05_validate.sql
ROLLBACK;
\echo 'Unknown-member, department, orphan-grain, financial and repeat-load tests passed; fixture rolled back.'
