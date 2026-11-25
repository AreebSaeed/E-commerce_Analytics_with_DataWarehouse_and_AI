# Olist Commerce Studio

A small TypeScript dashboard for the PostgreSQL warehouse in this repository. It shows revenue, orders, delivery, regions, categories, payment methods, and the existing ML outputs.

## Run locally

From the project root, export an updated aggregate snapshot after the ETL or ML jobs finish, then build and start the local dashboard:

```powershell
.\.venv\Scripts\python.exe web\export_snapshot.py
cd web
npm.cmd install
npm.cmd run build
cd ..
.\.venv\Scripts\python.exe web\predict_api.py
```

Open **http://127.0.0.1:8000/** and choose **Try prediction**. The Python server serves the built TypeScript dashboard and runs the saved model locally. It binds to your computer only.

Use **Revenue** or **Orders** above the trend chart to switch metrics. Hover over or focus a chart mark to preview its details, or select it to keep the details visible. Select it again or press **Escape** to clear it. On **Operations**, the state filter applies to the regional table and CSV export.

For TypeScript development, keep the Python server running and start `npm.cmd run dev` in a second PowerShell window from `web`. Vite proxies `/api` requests to the local Python server.

The dashboard reads `web/public/dashboard.json`, an aggregate snapshot generated from warehouse views and ML result tables. It does not connect directly to PostgreSQL from the browser. Refresh the snapshot and rebuild after data changes.

The prediction page sends the selected input values to the local Python server, which loads the newest `models/delivery_*.joblib` with its matching report. It uses the same features and preprocessing as `train_delivery.py`. Training uses the earliest 70% of orders, validation the next 15%, and testing the latest 15%. The chosen model was refitted on training plus validation, while the test period was held out. The page displays the actual held-out metrics from the model report. Test performance is weak, so predictions are for demonstration rather than dependable delivery warnings.
