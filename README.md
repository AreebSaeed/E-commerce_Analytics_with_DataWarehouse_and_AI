# Olist data warehouse

This project loads the Olist CSV files into a local PostgreSQL database. pgAdmin is the graphical client for viewing the resulting schemas, tables, and views. PostgreSQL 18 is installed on this laptop and its server was reachable during project setup.

## Load

All nine original CSV files are now in `data/raw`. In PowerShell, from this folder, run:

```powershell
.\setup.ps1 -Database olist_dw -User postgres
```

Enter the PostgreSQL password if prompted. The script creates `olist_dw`, builds the schema, loads the CSVs, transforms the data, and creates reporting views. It can be run again; warehouse tables are rebuilt from the raw files. If geolocation is absent, the load still works, but geographic coordinates and distance features remain empty.

In pgAdmin, refresh Servers → PostgreSQL → Databases → `olist_dw`. Browse `staging`, `dw`, and `meta`. Start with `dw.v_order_metrics`, `dw.mv_monthly_kpis`, `dw.mv_regional_metrics`, and `meta.etl_log`.

The facts have separate item and payment grains. Use `dw.v_order_metrics` for order-level financial reports to avoid multiplying amounts through joins. GMV excludes canceled and unavailable orders only in the reporting materialized views; the base order view retains all statuses for auditing.

The schema includes tables for ML predictions, but model training and Power BI reports are separate next stages. This initial load implements the warehouse and reporting foundation.
