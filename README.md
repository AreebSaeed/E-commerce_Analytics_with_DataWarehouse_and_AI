# Olist data warehouse

This project loads the Olist CSV files into a local PostgreSQL database. pgAdmin is the graphical client for viewing the resulting schemas, tables, and views. PostgreSQL 18 is installed on this laptop and its server was reachable during project setup.

## Load

Connection settings are read from `.env` in the project folder. Set `PGPASSWORD` to your PostgreSQL server password, or leave it blank to be prompted. The defaults are host `localhost`, port `5432`, database `olist_dw`, and user `postgres`. The file is ignored by Git to keep local credentials out of commits. Values are literal; you may wrap a password in matching quotes. Command-line parameters override the corresponding `.env` settings.

pgAdmin does not import this `.env` file. Use the same host, port, username, and password in its server connection settings, with `postgres` as the maintenance database. After loading, open the `olist_dw` database.

All nine original CSV files are now in `data/raw`. In PowerShell, from this folder, run:

```powershell
.\setup.ps1
```

Enter the PostgreSQL password if prompted. The script creates `olist_dw`, builds the schema, loads the CSVs, transforms the data, and creates reporting views. It can be run again; warehouse tables are rebuilt from the raw files. If geolocation is absent, the load still works, but geographic coordinates and distance features remain empty.

In pgAdmin, refresh Servers → PostgreSQL → Databases → `olist_dw`. Browse `staging`, `dw`, and `meta`. Start with `dw.v_order_metrics`, `dw.mv_monthly_kpis`, `dw.mv_regional_metrics`, and `meta.etl_log`.

The facts have separate item and payment grains. Use `dw.v_order_metrics` for order-level financial reports to avoid multiplying amounts through joins. GMV excludes canceled and unavailable orders only in the reporting materialized views; the base order view retains all statuses for auditing.

The schema includes tables for ML predictions, but model training and Power BI reports are separate next stages. This initial load implements the warehouse and reporting foundation.

## Unknown members and product departments

All seven dimensions contain one placeholder with surrogate key `0`. Missing customer, seller, product, category, geography, and date references use that key. Foreign keys have a default of `0` and reject explicit NULLs after the warehouse load. Placeholder natural identifiers are NULL so they cannot collide with real source identifiers.

Unknown calendar dates and coordinates remain NULL. An undelivered order has `delivered_date_key = 0`, `is_delivered = false`, and no invented delivery timestamp or delivery metrics. Dates outside the current 2016-2019 calendar also use key `0`, while their original timestamps remain available.

For source-versus-warehouse dimension counts, exclude the placeholder (`WHERE <dimension_key> <> 0`). The order reporting view excludes the placeholder automatically, and the ETL order count excludes it too. Each dimension therefore contains one extra physical row compared with its real members.

Facts retain `source_order_id` and are unique by source order plus item/payment sequence. This preserves separate orphaned orders even when they all map to `order_key = 0`. Orphan facts remain in financial reconciliation; order-level reports exclude them until a matching order header exists. Source and warehouse item/payment totals are reconciled separately, since the two amounts need not equal each other.

`dw.dim_product_category.macro_department` groups all 73 current nonblank categories into 14 departments. These are project-defined reporting choices, not an official Olist taxonomy. The mapping is maintained in `sql/category_departments.sql` and loaded into `meta.category_departments`. Portuguese names are used as mapping keys, so categories lacking an English translation are still classified. NULL/blank categories use the `Unknown` member; a new nonblank category without a mapping uses `Other`. Update the mapping SQL and rerun setup to change the taxonomy.

## Warehouse validation

Setup runs `sql/05_validate.sql` and fails if row counts, financial totals, unknown-member rules, or department assignments do not reconcile. It reports the number of real records using unknown references separately from NULL violations. Financial checks cover item price, freight, item totals, payments, and monthly/regional eligible GMV.

The integration test below replaces staging and warehouse data inside a transaction, exercises missing references, blank categories, translation fallbacks, orphan facts with matching sequence numbers, reporting totals, constraints, and repeat loads, then rolls back. Run it after setup with no concurrent load or report queries; it locks warehouse tables. Adjust connection arguments for your server (psql does not read `.env` automatically):

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -X -h localhost -U postgres -d olist_dw -v ON_ERROR_STOP=1 -f tests/warehouse_unknown_members.sql
```
