# Power BI dashboard

Open [`../Olist_PowerBI_Dashboard.pbix`](../Olist_PowerBI_Dashboard.pbix) in Power BI Desktop. It imports the reporting views and ML result tables from the local `olist_dw` PostgreSQL database. On another computer, use **Transform data > Data source settings > Change Source** to set the PostgreSQL server and database, then **Refresh**. Sign in with your own PostgreSQL credentials when prompted.

The report has three pages:

| Page | Visuals and filters |
| --- | --- |
| Executive & Sales | GMV, eligible orders, weighted AOV, and weighted on-time delivery cards; monthly GMV line; category revenue treemap; payment-method value donut; month and category filters. |
| Geospatial & Logistics | Customer-state GMV bar chart; state filter; state delivery-days and eligible-order table. |
| AI & Customer Intelligence | Count of scored orders by risk band; count of customers by segment; risk and segment filters. |

The month filter links `dw.v_monthly_kpis.month` to the month columns in the category/seller and payment views. Four DAX measures use the selected months:

```dax
Selected GMV = SUM('dw v_monthly_kpis'[gmv])
Selected Orders = SUM('dw v_monthly_kpis'[order_count])
Selected AOV = DIVIDE([Selected GMV], [Selected Orders])
Selected On-Time % = 100 * DIVIDE(SUM('dw v_monthly_kpis'[on_time_orders]), SUM('dw v_monthly_kpis'[delivered_orders]))
```

Run the read-only reconciliation against the current PostgreSQL database:

```powershell
.\.venv\Scripts\python.exe powerbi\reconcile.py
```

At the time this PBIX was built, the full-range report showed 98,207 eligible orders, 15,735,527.03 GMV, 160.23 AOV, and 91.89% on-time delivery. Monthly, regional, and category GMV each total 15,735,527.03. The payment-method value totals 15,739,137.01; payment value and GMV measure different things. The AI page covers 99,441 scored orders and 96,096 customer segments. Refresh the Power BI import after updating SQL reports or rerunning either model.

Category and state names identify different grains: the category filter applies to the category visual, the state filter applies to regional visuals, and risk and segment filters apply to their respective ML visuals. Category/seller `order_count` and payment-method `order_count` cannot be summed across groups because an order can belong to more than one group. Risk bands come from uncalibrated model scores; they are not verified probabilities.
