SELECT 'orders' AS entity,(SELECT count(*) FROM staging.orders) AS source_rows,(SELECT count(*) FROM dw.dim_order) AS warehouse_rows
UNION ALL SELECT 'items',(SELECT count(*) FROM staging.order_items),(SELECT count(*) FROM dw.fact_order_items)
UNION ALL SELECT 'payments',(SELECT count(*) FROM staging.order_payments),(SELECT count(*) FROM dw.fact_order_payments)
UNION ALL SELECT 'customers',(SELECT count(*) FROM staging.customers),(SELECT count(*) FROM dw.dim_customer)
UNION ALL SELECT 'sellers',(SELECT count(*) FROM staging.sellers),(SELECT count(*) FROM dw.dim_seller)
UNION ALL SELECT 'products',(SELECT count(*) FROM staging.products),(SELECT count(*) FROM dw.dim_product);

SELECT count(*) AS orders_without_customer FROM dw.dim_order WHERE customer_key IS NULL;
SELECT count(*) AS items_without_product FROM dw.fact_order_items WHERE product_key IS NULL;
SELECT count(*) AS items_without_seller FROM dw.fact_order_items WHERE seller_key IS NULL;
SELECT count(*) AS distinct_geographic_prefixes FROM dw.dim_geolocation;
SELECT count(*) AS orders_with_multiple_payment_rows FROM (SELECT order_key FROM dw.fact_order_payments GROUP BY order_key HAVING count(*)>1) x;
