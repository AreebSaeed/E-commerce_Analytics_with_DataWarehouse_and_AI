# Olist Commerce Studio

A small TypeScript dashboard for the PostgreSQL warehouse in this repository. It shows revenue, orders, delivery, regions, categories, payment methods, and the existing ML outputs.

## Run locally

From the project root, export an updated aggregate snapshot after the ETL or ML jobs finish:

```powershell
.\.venv\Scripts\python.exe web\export_snapshot.py
cd web
npm.cmd install
npm.cmd run dev
```

Open the local address shown by Vite. `npm.cmd run build` checks TypeScript and creates `web/dist`.

The UI reads `web/public/dashboard.json`, an aggregate snapshot generated from warehouse views and ML result tables. It does not connect directly to PostgreSQL from the browser. Refresh the snapshot and rebuild after data changes. The AI risk bands are exploratory: the existing late-delivery model's held-out F1 is 0.070, so its predictions should not be treated as dependable warnings.
