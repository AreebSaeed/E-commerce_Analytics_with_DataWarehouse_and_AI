# Olist KPI Cards

This Power BI visual ports the KPI cards from [Olist Commerce Studio](../../web/src/main.ts). It uses vanilla TypeScript, scoped LESS, and embedded DM Sans and Manrope fonts. The visual requests no Power BI privileges and loads no external assets at runtime.

## Import and bind fields

In Power BI Desktop, enable **File > Options and settings > Options > Current File > Report settings > Develop a visual**. In **Visualizations > … > Import a visual from a file**, select the `.pbiviz` file in `dist/`. [Microsoft import instructions](https://learn.microsoft.com/en-us/power-bi/developer/visuals/import-visual)

For the Executive & Sales headline, bind the existing [report measures](../README.md) as follows. You can use any subset.

| Visual field | Existing measure |
| --- | --- |
| Gross merchandise value | `Selected GMV` |
| Orders | `Selected Orders` |
| Average order value | `Selected AOV` |
| On-time delivery (0–100) | `Selected On-Time %` |

The headline measures follow the report's filter context. The visual expects percentage points, so a result of `91.89` displays as `91.9%`. Hover for the full currency amount or more percentage precision.

For a selectable grid, use **Category** and **Value** on a separate instance. Each card uses the category's Power BI selection identity. Click to select a category, Ctrl-click to select multiple categories, and click the selected card again or the visual's background to clear the selection. Cross-filtering depends on the report's model relationships and **Edit interactions** settings. Category mode displays up to 1,000 rows returned by Power BI. [Power BI visual interactions](https://learn.microsoft.com/en-us/power-bi/create-reports/service-reports-visual-interactions)

Add **Comparison value** to show the relative change on each category card. Change is calculated as `(Value − Comparison value) ÷ |Comparison value|`. Cards with a blank value, a blank baseline, or a zero baseline omit the change. Hover over a card to see the bound values.

Under **Format visual > Visual > Card style**, adjust the background, value color, primary teal accent, value font size, and corner radius.

## Build from source

Use Node.js 20.19+ (20.x), 22.13+ (22.x), or 24+. From the repository root in PowerShell, install the locked dependencies, run the TypeScript check, and build the package.

```powershell
Set-Location .\powerbi\olist-kpi-cards
npm.cmd ci
npm.cmd run check
npm.cmd run package
```

For live development, use PowerShell 7 (`pwsh`) on Windows for the SDK's development certificate setup. Enable developer mode in Power BI Service and add its developer visual to an editable report. From the visual folder, start the local server. [Power BI development setup](https://learn.microsoft.com/en-us/power-bi/developer/visuals/environment-setup) · [Development server troubleshooting](https://learn.microsoft.com/en-us/power-bi/developer/visuals/power-bi-custom-visuals-troubleshoot)

```powershell
npm.cmd start
```

The npm scripts invoke `pbiviz package --all-locales --no-stats` and `pbiviz start --all-locales`. The flag keeps Power BI's localized number formats and bypasses the SDK's locale-pruning loader, which cannot parse the current formatting utility's ES module.
