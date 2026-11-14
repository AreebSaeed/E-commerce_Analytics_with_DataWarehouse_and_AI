# Olist data warehouse

This project loads the Olist CSV files into a local PostgreSQL database. A small Python runner uses pandas and SQLAlchemy to load the CSVs, then runs the existing SQL transformations and reports through PostgreSQL's `psql` client. pgAdmin is the graphical client for exploring the resulting schemas, tables, and views.

## Load

Connection settings are read from `.env` in the project folder. Set `PGPASSWORD` to your PostgreSQL server password, or leave it blank to be prompted. The defaults are host `localhost`, port `5432`, database `olist_dw`, and user `postgres`. The file is ignored by Git to keep local credentials out of commits. Values are literal; you may wrap a password in matching quotes. Command-line parameters override the corresponding `.env` settings.

pgAdmin does not import this `.env` file. Use the same host, port, username, and password in its server connection settings, with `postgres` as the maintenance database. After loading, open the `olist_dw` database.

All nine original CSV files are now in `data/raw`. In PowerShell, from this folder, run:

```powershell
.\setup.ps1
```

Enter the PostgreSQL password if prompted. `setup.ps1` is a short wrapper for `etl.py`. The runner creates `olist_dw` if needed, builds the schema, loads the CSVs, transforms the data, updates reporting views, and validates the result. It can be run again; warehouse tables are rebuilt from the raw files. If geolocation is absent, the load still works, but geographic coordinates and distance features remain empty. Run only one load or reporting refresh at a time.

In pgAdmin, refresh Servers → PostgreSQL → Databases → `olist_dw`. Browse `staging`, `dw`, and `meta`. Start with `dw.v_order_metrics`, `dw.mv_monthly_kpis`, `dw.mv_regional_metrics`, and `meta.etl_log`.

The facts have separate item and payment grains. Use `dw.v_order_metrics` for order-level financial reports to avoid multiplying amounts through joins. Financial summaries exclude canceled and unavailable orders; the base order view retains all statuses for auditing.

The schema includes tables for ML predictions, but model training and Power BI reports are separate next stages. This initial load implements the warehouse and reporting foundation.

## Python setup

The local `.venv` is already prepared on this laptop. It uses a project-local Python runtime under `.tools`, so the MSYS Python on PATH is not needed. Both directories are ignored by Git. You do not need to activate the environment: `setup.ps1` selects its Python automatically.

On another machine with standard Python 3.12 installed, create the environment once:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

PostgreSQL's `psql` must be on PATH or installed at `C:\Program Files\PostgreSQL\18\bin\psql.exe`. Copy the nine CSVs into `data/raw` and create `.env` with the connection settings described above.

You can also run Python directly, which avoids PowerShell script execution-policy issues:

```powershell
.\.venv\Scripts\python.exe etl.py
.\.venv\Scripts\python.exe etl.py --reports-only
```

The code follows six steps: check files, prepare the schema, load CSVs, transform the warehouse, refresh reports, and validate. pandas reads 50,000 rows at a time as strings, preserving postal-code zeros and UTF-8 reviews. SQLAlchemy manages the connection and transaction; the PostgreSQL driver uses COPY to load each chunk efficiently. All staging tables are loaded in one transaction, so a bad CSV rolls back the entire staging load.

`sql/02_load.sql` remains an optional SQL-only loader for manual use; the Python runner does not call it. For audited runs, use `setup.ps1` or `etl.py`.

## ETL audit log

Each Python run inserts a `running` row in `meta.etl_log` before loading starts. It records `success` only after reports and validation finish. On an error, it records `failed`, the failed stage, completion time, and error message, and exits with a failure status. Existing history is retained; older rows may not have the new detail fields.

```sql
SELECT run_id, run_mode, started_at, completed_at,
       completed_at - started_at AS duration,
       status, stage, source_orders, loaded_orders, error_message
FROM meta.etl_log
ORDER BY run_id DESC LIMIT 10;

SELECT row_counts, unknown_counts
FROM meta.etl_log
ORDER BY run_id DESC LIMIT 1;
```

`row_counts` records source and warehouse counts, excluding placeholder dimension rows. `unknown_counts` records real records that reference key `0`. On a failed run, available counts describe the database at failure time, not a successful load. The stages commit separately: an error in reporting does not undo an already completed warehouse transform. Fix the reported problem and rerun. Connection failures before audit storage is available are reported in the terminal; a forcibly terminated process can leave its log row marked `running`.

Run the small Python tests with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

## Reporting

The reporting layer uses ordinary SQL views and three materialized views (stored summaries). No extra application or Python code is needed for this step.

| View | What it provides |
| --- | --- |
| `dw.v_sales_kpis` | One row: eligible orders, GMV, AOV, on-time delivery percentage, average review score, and freight-to-price percentage. |
| `dw.v_monthly_kpis` | Monthly GMV, orders, AOV, review scores, and on-time delivery percentage, using `dw.mv_monthly_kpis`. |
| `dw.mv_regional_metrics` | Customer-state GMV, eligible order counts, and average delivery time. |
| `dw.mv_category_seller_metrics` | Monthly category/seller sales, department labels, item counts, distinct order counts, GMV per order within the group, and freight-to-price percentage. |
| `dw.v_payment_method_metrics` | Monthly payment amounts by method, payment row counts, distinct orders, average installments, and share of the month's payment value. |
| `dw.v_order_metrics` | One row per real order, with item and payment totals aggregated separately. |

Preview the reports in pgAdmin's Query Tool:

```sql
SELECT * FROM dw.v_sales_kpis;
SELECT * FROM dw.v_monthly_kpis ORDER BY month;
SELECT * FROM dw.mv_category_seller_metrics ORDER BY gmv DESC LIMIT 20;
SELECT * FROM dw.v_payment_method_metrics ORDER BY month, payment_total DESC;
```

To update the reporting definitions, refresh the summaries, and validate them without reloading any CSVs, run:

```powershell
.\setup.ps1 -ReportsOnly
```

Normal setup also updates the reports automatically. For a refresh alone, run the three SQL statements in `sql/06_refresh_views.sql` in pgAdmin. Existing materialized views are refreshed concurrently rather than dropped, so their definitions and dependent reports remain intact. Regular views read current data; materialized views show the last refreshed data. Do not run a warehouse rebuild at the same time as a separate reporting refresh.

Financial summaries exclude canceled/unavailable orders and orphan facts. Delivery and review metrics include all real orders; the on-time denominator is delivered orders. AOV is eligible GMV divided by eligible orders, including orders with no items. Freight-to-price percentage is `100 * total freight / total item price`. Percentages use 0-100; a zero denominator returns NULL instead of a misleading percentage. Average installments are calculated per payment row.

GMV and payment totals are different measures and need not match. Do not join item facts directly to payment facts. Do not sum distinct order counts across categories, sellers, or payment methods: an order can appear in several groups. Recalculate ratios from their totals when combining groups rather than averaging percentages.

## Unknown members and product departments

All seven dimensions contain one placeholder with surrogate key `0`. Missing customer, seller, product, category, geography, and date references use that key. Foreign keys have a default of `0` and reject explicit NULLs after the warehouse load. Placeholder natural identifiers are NULL so they cannot collide with real source identifiers.

Unknown calendar dates and coordinates remain NULL. An undelivered order has `delivered_date_key = 0`, `is_delivered = false`, and no invented delivery timestamp or delivery metrics. Dates outside the current 2016-2019 calendar also use key `0`, while their original timestamps remain available.

For source-versus-warehouse dimension counts, exclude the placeholder (`WHERE <dimension_key> <> 0`). The order reporting view excludes the placeholder automatically, and the ETL order count excludes it too. Each dimension therefore contains one extra physical row compared with its real members.

Facts retain `source_order_id` and are unique by source order plus item/payment sequence. This preserves separate orphaned orders even when they all map to `order_key = 0`. Orphan facts remain in financial reconciliation; order-level reports exclude them until a matching order header exists. Source and warehouse item/payment totals are reconciled separately, since the two amounts need not equal each other.

`dw.dim_product_category.macro_department` groups all 73 current nonblank categories into 14 departments. These are project-defined reporting choices, not an official Olist taxonomy. The mapping is maintained in `sql/category_departments.sql` and loaded into `meta.category_departments`. Portuguese names are used as mapping keys, so categories lacking an English translation are still classified. NULL/blank categories use the `Unknown` member; a new nonblank category without a mapping uses `Other`. Update the mapping SQL and rerun setup to change the taxonomy.

## Warehouse validation

Setup runs `sql/05_validate.sql` and fails if row counts, financial totals, unknown-member rules, or department assignments do not reconcile. It reports the number of real records using unknown references separately from NULL violations. Financial checks cover item price, freight, item totals, payments, monthly/regional/category-seller eligible GMV, headline GMV, and payment-method totals.

The integration test below replaces staging and warehouse data inside a transaction, exercises missing references, blank categories, translation fallbacks, orphan facts with matching sequence numbers, reporting totals, constraints, and repeat loads, then rolls back. Run it after setup with no concurrent load or report queries; it locks warehouse tables. Adjust connection arguments for your server (psql does not read `.env` automatically):

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -X -h localhost -U postgres -d olist_dw -v ON_ERROR_STOP=1 -f tests/warehouse_unknown_members.sql
```
