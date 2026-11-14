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
