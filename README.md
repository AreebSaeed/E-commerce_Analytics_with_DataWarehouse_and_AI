# Olist data warehouse

This project loads the Olist CSV files into a local PostgreSQL database. A small Python runner uses pandas and SQLAlchemy to load the CSVs, then runs the existing SQL transformations and reports through PostgreSQL's `psql` client. pgAdmin is the graphical client for exploring the resulting schemas, tables, and views.

## Architecture and quick start

The nine CSVs flow through `staging` tables into the `dw` dimensions and facts. SQL views and stored summaries provide reporting metrics. Python trains the delivery-risk and customer-segmentation models, writes their outputs back to `dw`, and saves local model files. Power BI imports the reporting views and ML tables. The TypeScript portal reads an exported aggregate JSON snapshot; its local Python API loads the saved delivery model for what-if predictions.

For a fresh local setup, install PostgreSQL (including `psql`), Python 3.12, and Node.js. Put the nine Olist CSVs in `data/raw`, copy `.env.example` to `.env`, and fill in `PGPASSWORD` for your local PostgreSQL server. Then, from this folder in PowerShell:

```powershell
python run_project.py
```

If the project virtual environment already exists, run `.\.venv\Scripts\python.exe run_project.py`. The command opens the pipeline control panel at `http://127.0.0.1:8765/`. Click **Run** beside each stage as it becomes ready. The panel displays live logs, warehouse row counts, model results, and build output. Use **Open commerce dashboard** after starting the final stage. Keep the terminal open while using either page. Press `Ctrl+C` in the terminal to stop the control panel and any process it started.

Use `python run_project.py --all` to run every stage automatically in the terminal. Both modes reuse the installed dependencies and install missing ones as needed.

To run the same stages directly:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\setup.ps1
.\.venv\Scripts\python.exe train_delivery.py
.\.venv\Scripts\python.exe segment_customers.py
.\.venv\Scripts\python.exe web\export_snapshot.py
cd web
npm.cmd ci
npm.cmd run build
cd ..
.\.venv\Scripts\python.exe web\predict_api.py
```

Open `http://127.0.0.1:8000/`. Open [Olist_PowerBI_Dashboard.pbix](Olist_PowerBI_Dashboard.pbix) separately in Power BI Desktop and refresh its PostgreSQL import. The raw CSVs, `.env`, `.venv`, and trained `.joblib` files are local inputs or generated files; a fresh setup needs to create them. There is no Docker setup because this project is intended to run locally on this computer.

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

The late-delivery model, customer segmentation, Power BI report, and TypeScript portal are implemented.

## Machine learning feature datasets

Step 4 is provided by three SQL views. They update automatically when the warehouse is rebuilt; no separate export is required.

| View | Grain and purpose |
| --- | --- |
| `dw.v_delivery_features` | One row per real order. Purchase-time inputs for the late-delivery model: month and weekday, customer and seller state, item count, price, freight, product weight/volume, and seller-to-customer distance in km. |
| `dw.v_delivery_training` | Delivered orders with an estimated delivery date and purchase time. Adds `label_is_late` for model training and evaluation. |
| `dw.v_customer_features` | One row per permanent `customer_unique_id`: recency, frequency, GMV, log GMV, average review score, and average delivery delay. |

Preview them in pgAdmin:

```sql
SELECT * FROM dw.v_delivery_features LIMIT 10;
SELECT * FROM dw.v_delivery_training LIMIT 10;
SELECT * FROM dw.v_customer_features LIMIT 10;
```

`v_delivery_features` contains no actual delivery date, review score, order status, or late-delivery label. `purchase_timestamp` and `order_id` identify and chronologically split records; they are not model predictors. The label is only in `v_delivery_training`, and `train_delivery.py` excludes it from the input columns. Undelivered, canceled, unavailable, and unestimable orders have no observed training label. The trained model can score rows from `v_delivery_features`, including orders without outcomes.

For orders with several sellers, the seller with the highest item total supplies the representative state and distance; ties use seller key. The distance uses the average coordinates for each postal prefix and the Haversine formula. Missing or clearly out-of-range coordinates produce NULL, not a fabricated distance. The broad screening box is latitude -34 to 6 and longitude -74 to -34, based on [IBGE's published extreme points of Brazil](https://www.ibge.gov.br/biblioteca/visualizacao/periodicos/2/bn_2023_v31_art02.pdf). This box rejects obvious errors but is not a precise border or state check. Product totals sum known item measurements; `weight_known_items` and `volume_known_items` show how many measurements contributed, so incomplete totals can be identified.

Customer recency uses the latest eligible purchase date in this historical dataset as its reference date. Frequency and GMV include only orders with a purchase timestamp and exclude canceled/unavailable orders. Buyers with no eligible purchases have zero frequency/GMV and NULL recency; missing review or delay information stays NULL. The two model scripts handle missing input values separately.

## Train the late-delivery model

After loading the warehouse, run:

```powershell
.\.venv\Scripts\python.exe train_delivery.py
```

The script trains Logistic Regression and Random Forest using only the columns listed in `train_delivery.py`. Orders are divided by purchase time into an earlier training period (about 70%), a later validation period (about 15%), and the latest test period (about 15%). It fits missing-value rules, state encoding, and scaling on training data only. It compares both models and decision cutoffs on validation F1, refits the selected model on training plus validation, and evaluates it once on the untouched test period. F1 summarizes precision and recall for the late class; the script also prints the four confusion-matrix counts. These periods are [ordered in time to avoid training on later examples than the ones used for evaluation](https://scikit-learn.org/stable/modules/cross_validation.html).

The selected pipeline is saved under `models/` as a `.joblib` file, and its metrics are saved in a neighboring `.json` file. The binary model is ignored by Git and must be regenerated on another machine. The script writes one row per real order into `dw.ml_order_risk_scores` and records validation/test metrics in `meta.ml_runs`. Score replacement and metric inserts occur in one database transaction. Risk bands are based on the validation-selected cutoff: `High` is at or above it, `Medium` is between half the cutoff and the cutoff, and `Low` is below half. These are heuristic bands around an **uncalibrated model score**, not verified delivery probabilities.

The held-out test on this dataset is weak: the selected Random Forest reached precision **0.047**, recall **0.137**, and F1 **0.070** (131 correctly flagged late orders, 2,635 false alarms, and 826 missed late orders). Use the scores as a learning result, not an operational delivery promise. A full warehouse rebuild clears previous predictions and customer segments because they may refer to old data; rerun both model scripts afterward. A reporting-only refresh leaves model outputs intact. The held-out test metrics are separate from the scores written for all historical orders; many of those rows were used to train the model.

Inspect the results in pgAdmin:

```sql
SELECT risk_band, count(*) FROM dw.ml_order_risk_scores GROUP BY risk_band;
SELECT model_name, metric_name, metric_value, notes
FROM meta.ml_runs ORDER BY run_id DESC LIMIT 14;
```

## Segment customers

After loading the warehouse, run:

```powershell
.\.venv\Scripts\python.exe segment_customers.py
```

The script groups customers using recency, order frequency, log-transformed GMV, average review score, and average delivery delay from `dw.v_customer_features`. It fills missing review/delay values with their medians, limits extreme inputs to the 1st and 99th percentiles, and standardizes all five inputs before K-Means. It fits k=2 through k=8 on all buyers with eligible orders and compares their [silhouette scores](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.silhouette_score.html) on a fixed random sample of 2,000 for a quick, reproducible selection. No eligible purchase means recency is undefined, so those buyers receive cluster `-1` and the label `No eligible purchases` rather than a fabricated recency value.

The selected model and its input transformations are saved under `models/`; a JSON file records scores and cluster profiles. One row per permanent buyer ID is written to `dw.ml_customer_segments`, and the silhouette scores, chosen k, and cluster sizes are logged in `meta.ml_runs`. The write is one database transaction. Names describe observed median spending, repeat activity, recency, and delay; they are descriptive groups, not proven loyalty or churn predictions.

On this dataset, k=2 had the highest sampled silhouette (**0.602**). It grouped **92,102 one-time lower-spend buyers** and **2,888 higher-spend repeat buyers**. Another **1,106 buyers** had no eligible purchase and were assigned cluster `-1`. Cluster numbers and names can change when data changes; use the saved version and profile rather than assuming cluster `0` always means the same thing.

```sql
SELECT cluster_id, segment_label, count(*) AS customers
FROM dw.ml_customer_segments
GROUP BY cluster_id, segment_label ORDER BY cluster_id;

SELECT metric_name, metric_value, notes
FROM meta.ml_runs WHERE model_name = 'kmeans'
ORDER BY run_id DESC LIMIT 11;
```

## TypeScript dashboard and prediction page

The `web` folder contains a TypeScript dashboard and a **Try prediction** page. The prediction form calls a local Python server that loads the latest saved delivery model and displays its held-out test metrics. See [web/README.md](web/README.md) for the commands to build and run it.

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
| `dw.v_regional_metrics` | Customer-state GMV, eligible order counts, and average delivery time. |
| `dw.v_category_seller_metrics` | Monthly category/seller sales, department labels, item counts, distinct order counts, GMV per order within the group, and freight-to-price percentage. |
| `dw.v_payment_method_metrics` | Monthly payment amounts by method, payment row counts, distinct orders, average installments, and share of the month's payment value. |
| `dw.v_order_metrics` | One row per real order, with item and payment totals aggregated separately. |

Preview the reports in pgAdmin's Query Tool:

```sql
SELECT * FROM dw.v_sales_kpis;
SELECT * FROM dw.v_monthly_kpis ORDER BY month;
SELECT * FROM dw.v_category_seller_metrics ORDER BY gmv DESC LIMIT 20;
SELECT * FROM dw.v_payment_method_metrics ORDER BY month, payment_total DESC;
```

To update the reporting definitions, refresh the summaries, and validate them without reloading any CSVs, run:

```powershell
.\setup.ps1 -ReportsOnly
```

Normal setup also updates the reports automatically. For a refresh alone, run the three SQL statements in `sql/06_refresh_views.sql` in pgAdmin. Existing materialized views are refreshed concurrently rather than dropped, so their definitions and dependent reports remain intact. Regular views read current data; materialized views show the last refreshed data. Do not run a warehouse rebuild at the same time as a separate reporting refresh.

For Power BI, select the `dw.v_*` reporting views. `v_regional_metrics` and `v_category_seller_metrics` expose the stored `mv_*` summaries as ordinary views, because the materialized views may not appear in Power BI's Navigator. Refresh the connection list after updating the reports.

The three-page Power BI report and its reconciliation instructions are in [powerbi/README.md](powerbi/README.md).

## Performance and spatial checks

Run the read-only SQL benchmark after loading the warehouse:

```powershell
.\.venv\Scripts\python.exe performance\benchmark.py
```

It runs `EXPLAIN (ANALYZE, BUFFERS)` plus three warm client reads for the reporting and portal queries. On this local database, the slowest observed PostgreSQL execution in the final run was the portal's yearly regional query at **1,149 ms**. Its slowest warm client read was **910 ms**. The payment-method report took **504 ms** in PostgreSQL and at most **796 ms** for a warm client read. All tested SQL reads were below the proposal's **1.5-second target** in that run. These are local measurements, not guarantees for another computer or a Power BI visual render.

The plan showed repeated table fetches while aggregating order-item amounts. `ix_items_order_amounts` now covers the order key, price, freight, and item total used by those reports. In the first before/after measurement, the sales KPI query fell from **566 ms to 252 ms** in PostgreSQL. Other full-scan groupings use sequential scans because they read nearly all rows; adding indexes to those grouping columns would not necessarily help.

For a local portal check, start `web/predict_api.py`, then run:

```powershell
.\.venv\Scripts\python.exe performance\portal_benchmark.py
```

In five warm requests, the largest measured times were **24 ms** for dashboard HTML, **17 ms** for its data snapshot, **17 ms** for model metadata, and **124 ms** for a what-if prediction. These timings measure local HTTP responses and model inference, not browser drawing. Power BI uses Import mode, so report interactions read its local model after refresh rather than issuing these PostgreSQL queries on each click.

Power BI Desktop's **View > Performance Analyzer** was also used to time a warm **Refresh visuals** on each page. The slowest individual visual was **518 ms** on Executive & Sales, **255 ms** on Geospatial & Logistics, and **196 ms** on AI & Customer Intelligence. The exports are [executive](performance/powerbi_executive.json), [logistics](performance/powerbi_logistics.json), and [AI](performance/powerbi_ai.json). All warm visual timings were below 1.5 seconds. The first executive refresh after reopening the PBIX included visuals around **1.6 seconds**, so the target was **not met on that initial refresh**. These measurements were made on this computer with imported data; a different machine may behave differently.

Run [performance/spatial_examples.sql](performance/spatial_examples.sql) in pgAdmin to see a bounding-box search and ten nearby postal prefixes around Sao Paulo. The box contained **4,522** prefixes here, and the nearest prefix was `01001` at about **0.08 km**. `EXPLAIN` confirmed both queries use the existing GiST index `ix_geo_point`. Nearest-neighbor candidate ranking uses planar degrees; displayed distances use Haversine kilometers. Postal-prefix centroids and the broad coordinate screening are approximate locations, not street addresses.

The setup commands were also checked in temporary clean Python and TypeScript environments: pinned Python dependencies installed, all eight Python tests passed, SQL reconciliation passed, and a fresh `npm ci` plus TypeScript build succeeded. The temporary environments were removed afterward. This checks the application setup on the current computer; a second computer was not tested.

## Limitations

- The held-out late-delivery F1 is **0.070**. Its risk bands are based on uncalibrated scores, so do not treat them as dependable warnings or verified probabilities.
- Customer segment names describe this historical sample. Cluster labels and profiles can change after retraining.
- The TypeScript portal reads an exported snapshot. Rerun `web/export_snapshot.py` and rebuild after warehouse or model changes; refresh Power BI's imported data separately.
- Spatial coordinates are postal-prefix centroids. The state dashboard uses state summaries rather than a street-level map.
- The 1.5-second checks cover local SQL, HTTP/model responses, and warm Power BI visuals. Browser rendering was not measured, and Power BI's first executive refresh after reopening slightly exceeded the target.

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
