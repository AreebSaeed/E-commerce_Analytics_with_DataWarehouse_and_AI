import './style.css'

type Month = { month: string; order_count: number; gmv: number; on_time_orders: number; delivered_orders: number }
type Region = { year: number; state: string; order_count: number; gmv: number; avg_delivery_days: number | null }
type Category = { year: number; category: string; macro_department: string; gmv: number; item_count: number }
type Payment = { year: number; payment_type: string; amount: number }
type Group = { label: string; count: number; cluster_id?: number }
type Snapshot = {
  headline: { order_count: number; gmv: number; aov: number; on_time_delivery_pct: number; avg_review_score: number }
  monthly: Month[]; regional: Region[]; categories: Category[]; payments: Payment[]
  risks: Group[]; segments: Group[]
}
type Page = 'overview' | 'revenue' | 'operations' | 'intelligence'

const app = document.querySelector<HTMLDivElement>('#app')!
let data: Snapshot
let page: Page = 'overview'
let year = 'all'
let regionSort: 'gmv' | 'order_count' = 'gmv'

const money = (value: number) => `R$ ${new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value / 1_000_000)}M`
const moneyExact = (value: number) => `R$ ${new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value)}`
const number = (value: number) => new Intl.NumberFormat('en-US').format(Math.round(value))
const percent = (value: number) => `${value.toFixed(1)}%`
const safe = (value: string) => value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!)
const active = (rowYear: number) => year === 'all' || String(rowYear) === year
const titleCase = (value: string) => value.replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase())

function icon(name: string) {
  const paths: Record<string, string> = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    revenue: '<path d="M3 17l6-6 4 4 8-9"/><path d="M16 6h5v5"/>',
    operations: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 15l3-4 3 2 4-5"/>',
    brain: '<path d="M12 18V6m0 2a4 4 0 1 0-5 3m5-3a4 4 0 1 1 5 3M12 18a4 4 0 1 1-5-3m5 3a4 4 0 1 0 5-3"/>',
    arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
    download: '<path d="M12 3v12m-4-4 4 4 4-4M4 17v3h16v-3"/>',
  }
  return `<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]}</svg>`
}

function selectedMonths() { return data.monthly.filter(row => active(Number(row.month.slice(0, 4)))) }
function selectedRegions() {
  const groups = new Map<string, { state: string; gmv: number; order_count: number; leadSum: number; leadCount: number }>()
  for (const row of data.regional.filter(row => active(row.year))) {
    const found = groups.get(row.state) ?? { state: row.state, gmv: 0, order_count: 0, leadSum: 0, leadCount: 0 }
    found.gmv += row.gmv; found.order_count += row.order_count
    if (row.avg_delivery_days !== null) { found.leadSum += row.avg_delivery_days * row.order_count; found.leadCount += row.order_count }
    groups.set(row.state, found)
  }
  return [...groups.values()].map(row => ({ ...row, avg_delivery_days: row.leadCount ? row.leadSum / row.leadCount : null }))
    .sort((a, b) => b[regionSort] - a[regionSort])
}
function selectedCategories() {
  const groups = new Map<string, { category: string; macro_department: string; gmv: number; item_count: number }>()
  for (const row of data.categories.filter(row => active(row.year))) {
    const found = groups.get(row.category) ?? { category: row.category, macro_department: row.macro_department, gmv: 0, item_count: 0 }
    found.gmv += row.gmv; found.item_count += row.item_count; groups.set(row.category, found)
  }
  return [...groups.values()].sort((a, b) => b.gmv - a.gmv)
}
function selectedPayments() {
  const groups = new Map<string, number>()
  for (const row of data.payments.filter(row => active(row.year))) groups.set(row.payment_type, (groups.get(row.payment_type) ?? 0) + row.amount)
  return [...groups].map(([label, amount]) => ({ label, amount })).sort((a, b) => b.amount - a.amount)
}
function selectedKpis() {
  const months = selectedMonths()
  const gmv = months.reduce((sum, item) => sum + item.gmv, 0)
  const orders = months.reduce((sum, item) => sum + item.order_count, 0)
  const delivered = months.reduce((sum, item) => sum + item.delivered_orders, 0)
  const ontime = months.reduce((sum, item) => sum + item.on_time_orders, 0)
  return { gmv, orders, aov: orders ? gmv / orders : 0, ontime: delivered ? 100 * ontime / delivered : 0 }
}

function nav() {
  const items: [Page, string, string][] = [['overview', 'Overview', 'grid'], ['revenue', 'Revenue', 'revenue'], ['operations', 'Operations', 'operations'], ['intelligence', 'AI intelligence', 'brain']]
  return `<aside class="sidebar">
    <div class="brand"><div class="brand-mark"><span></span><span></span><span></span><span></span></div><div><strong>olist<span>.</span></strong><small>COMMERCE STUDIO</small></div></div>
    <div class="workspace-label">WORKSPACE <span>01</span></div>
    <nav aria-label="Main navigation">${items.map(([id, label, glyph]) => `<button class="nav-link ${page === id ? 'selected' : ''}" data-page="${id}" aria-current="${page === id ? 'page' : 'false'}">${icon(glyph)}<span>${label}</span>${page === id ? '<i></i>' : ''}</button>`).join('')}</nav>
    <div class="sidebar-bottom"><div class="status-dot"></div><div><strong>Snapshot ready</strong><small>PostgreSQL · olist_dw</small></div></div>
  </aside>`
}

function topbar() {
  const years = ['all', ...new Set(data.monthly.map(item => item.month.slice(0, 4)))].sort((a, b) => a === 'all' ? -1 : b === 'all' ? 1 : Number(b) - Number(a))
  return `<header class="topbar"><div class="breadcrumb">Analytics <span>/</span> <strong>${page === 'intelligence' ? 'AI intelligence' : titleCase(page)}</strong></div>
    <div class="top-actions">${page === 'intelligence' ? '<span class="snapshot-pill">All historical orders</span>' : `<div class="year-switch" role="group" aria-label="Filter by year">${years.map(item => `<button data-year="${item}" class="${year === item ? 'current' : ''}">${item === 'all' ? 'All time' : item}</button>`).join('')}</div>`}
    <button class="export-button" data-export title="Download the current table as CSV">${icon('download')}<span>Export CSV</span></button></div></header>`
}

function hero() {
  const subtitle = page === 'intelligence' ? 'Explore model outputs with the right context.' : page === 'operations' ? 'See where orders move, and where they slow down.' : page === 'revenue' ? 'Understand the shape of your sales.' : 'A clearer view of every order.'
  const heading = page === 'intelligence' ? 'Customer intelligence' : page === 'operations' ? 'Delivery operations' : page === 'revenue' ? 'Revenue performance' : 'Your commerce, in focus.'
  return `<section class="hero"><div class="hero-content"><div class="eyebrow light"><span></span> OLIST ANALYTICS / ${year === 'all' ? 'ALL YEARS' : year}</div><h1>${heading}</h1><p>${subtitle}</p><div class="hero-foot"><span class="hero-badge">●</span> Historical Olist data · 2016–2018</div></div><div class="hero-art" aria-hidden="true"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><div class="orbit orbit-three"></div><div class="orb"></div><div class="art-bar art-one"></div><div class="art-bar art-two"></div><div class="art-bar art-three"></div></div></section>`
}

function kpiCards() {
  const k = selectedKpis()
  const cards = [
    ['Gross merchandise value', money(k.gmv), 'Eligible item value + freight', '↗', 'teal'],
    ['Orders', number(k.orders), 'Eligible, distinct orders', '↗', 'blue'],
    ['Average order value', moneyExact(k.aov), 'GMV ÷ eligible orders', '↗', 'amber'],
    ['On-time delivery', percent(k.ontime), 'Of delivered orders', '↗', 'coral'],
  ]
  return `<div class="kpi-grid">${cards.map(([label, value, caption, arrow, theme]) => `<article class="kpi-card ${theme}"><div class="kpi-label">${label}<span>${arrow}</span></div><div class="kpi-value">${value}</div><div class="kpi-caption">${caption}</div><div class="kpi-accent"></div></article>`).join('')}</div>`
}

function revenueChart() {
  const rows = selectedMonths()
  const width = 760, height = 230, pad = 18
  const max = Math.max(...rows.map(row => row.gmv), 1)
  const points = rows.map((row, index) => ({ x: pad + index * (width - 2 * pad) / Math.max(rows.length - 1, 1), y: height - pad - row.gmv / max * (height - 2 * pad), row }))
  const line = points.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')
  const area = `${line} L${points.at(-1)?.x ?? pad},${height} L${pad},${height} Z`
  const ticks = rows.filter((_, index) => index === 0 || index === rows.length - 1 || index % Math.max(1, Math.floor(rows.length / 5)) === 0)
  return `<section class="panel chart-panel"><div class="panel-header"><div><span class="eyebrow">PERFORMANCE</span><h2>Revenue over time</h2></div><span class="panel-tag">Monthly GMV</span></div><div class="chart-wrap"><div class="chart-axis"><span>${money(max)}</span><span>${money(max / 2)}</span><span>R$ 0</span></div><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Monthly gross merchandise value trend" preserveAspectRatio="none"><defs><linearGradient id="revenueFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#16b8a6" stop-opacity=".26"/><stop offset="100%" stop-color="#16b8a6" stop-opacity="0"/></linearGradient></defs><path d="${area}" fill="url(#revenueFill)"/><path d="${line}" fill="none" stroke="#08a896" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>${points.map(point => `<circle cx="${point.x}" cy="${point.y}" r="5" fill="#fff" stroke="#08a896" stroke-width="2"><title>${point.row.month.slice(0, 7)} · ${moneyExact(point.row.gmv)}</title></circle>`).join('')}</svg></div><div class="chart-ticks">${ticks.map(point => `<span>${new Date(`${point.month}T00:00:00`).toLocaleDateString('en-US', { month: 'short', year: '2-digit' })}</span>`).join('')}</div><div class="chart-footer"><span><i class="legend-dot teal-dot"></i> Gross merchandise value</span><strong>${money(selectedKpis().gmv)} <small>in selected period</small></strong></div></section>`
}

function categoryPanel(full = false) {
  const items = selectedCategories().slice(0, full ? 12 : 6)
  const max = Math.max(items[0]?.gmv ?? 1, 1)
  return `<section class="panel category-panel"><div class="panel-header"><div><span class="eyebrow">MERCHANDISING</span><h2>Top categories</h2></div><span class="panel-tag">By GMV</span></div><div class="bar-list">${items.map((item, index) => `<div class="bar-item"><div class="bar-meta"><span><em>${String(index + 1).padStart(2, '0')}</em> ${safe(titleCase(item.category))}</span><strong>${money(item.gmv)}</strong></div><div class="bar-track"><div style="width:${Math.max(3, item.gmv / max * 100)}%"></div></div></div>`).join('')}</div></section>`
}

function paymentPanel() {
  const items = selectedPayments()
  const total = items.reduce((sum, item) => sum + item.amount, 0)
  const colors = ['#0fae9c', '#27465a', '#f2b66b', '#8ca9a9', '#e48f88']
  let cursor = 0
  const stops = items.map((item, index) => { const start = cursor; cursor += total ? item.amount / total * 100 : 0; return `${colors[index % colors.length]} ${start}% ${cursor}%` }).join(', ')
  return `<section class="panel payment-panel"><div class="panel-header"><div><span class="eyebrow">PAYMENTS</span><h2>How customers pay</h2></div><span class="panel-tag">Value share</span></div><div class="payment-body"><div class="donut" style="background:conic-gradient(${stops})" role="img" aria-label="Payment method share"><div><span>TOTAL</span><strong>${money(total)}</strong></div></div><div class="payment-legend">${items.map((item, index) => `<div><i style="background:${colors[index % colors.length]}"></i><span>${safe(titleCase(item.label))}</span><strong>${percent(total ? item.amount / total * 100 : 0)}</strong></div>`).join('')}</div></div></section>`
}

function regionalPanel(full = false) {
  const items = selectedRegions().slice(0, full ? 27 : 5)
  const max = Math.max(items[0]?.gmv ?? 1, 1)
  return `<section class="panel region-panel"><div class="panel-header"><div><span class="eyebrow">GEOGRAPHY</span><h2>Regional performance</h2></div><button class="sort-button" data-sort="${regionSort === 'gmv' ? 'order_count' : 'gmv'}">Sort by ${regionSort === 'gmv' ? 'orders' : 'GMV'} ${icon('arrow')}</button></div><div class="region-table"><div class="region-table-head"><span>STATE</span><span>REVENUE</span><span>ORDERS</span><span>DELIVERY</span></div>${items.map(item => `<div class="region-row"><div class="state-cell"><b>${safe(item.state)}</b><span class="state-bar" style="--bar-width:${Math.max(4, item.gmv / max * 100)}%"></span></div><strong>${money(item.gmv)}</strong><span>${number(item.order_count)}</span><span>${item.avg_delivery_days === null ? '—' : `${item.avg_delivery_days.toFixed(1)}d`}</span></div>`).join('')}</div>${full ? '' : '<p class="panel-note">Showing the top five states. Open Operations for the full list.</p>'}</section>`
}

function riskPanel() {
  const order = ['Low', 'Medium', 'High']
  const colors = ['#0fae9c', '#f0ae5f', '#e58c84']
  const total = data.risks.reduce((sum, group) => sum + group.count, 0)
  return `<section class="panel intelligence-panel"><div class="panel-header"><div><span class="eyebrow">DELIVERY MODEL</span><h2>Risk bands</h2></div><span class="panel-tag warn">Experimental model</span></div><div class="risk-grid">${order.map((label, index) => { const value = data.risks.find(group => group.label === label)?.count ?? 0; return `<div class="risk-card"><span class="risk-symbol" style="background:${colors[index]}"></span><small>${label} risk</small><strong>${number(value)}</strong><span>${percent(total ? value / total * 100 : 0)} of scored orders</span></div>` }).join('')}</div><div class="insight-note"><span>ⓘ</span><p>The late-delivery model has a held-out F1 of <strong>0.070</strong>. Use these bands to explore the data, not as reliable delivery warnings.</p></div></section>`
}

function segmentsPanel() {
  const total = data.segments.reduce((sum, group) => sum + group.count, 0)
  return `<section class="panel segments-panel"><div class="panel-header"><div><span class="eyebrow">CUSTOMER BEHAVIOR</span><h2>Buyer segments</h2></div><span class="panel-tag">K-Means · 2 clusters</span></div><div class="segment-list">${data.segments.slice().sort((a, b) => b.count - a.count).map((group, index) => `<div class="segment-row"><div class="segment-icon s${index}">${index === 0 ? '01' : index === 1 ? '02' : '—'}</div><div><strong>${safe(group.label.replace(/ \(Cluster \d+\)/, ''))}</strong><span>${group.cluster_id === -1 ? 'No purchase history to classify' : `Cluster ${group.cluster_id} · observed behavior`}</span></div><div class="segment-stat"><strong>${number(group.count)}</strong><span>${percent(group.count / total * 100)}</span></div></div>`).join('')}</div></section>`
}

function operationTrend() {
  const rows = selectedMonths().filter(row => row.delivered_orders > 0)
  return `<section class="panel ops-trend"><div class="panel-header"><div><span class="eyebrow">FULFILLMENT</span><h2>On-time delivery by month</h2></div><span class="panel-tag">Delivered orders only</span></div><div class="ops-bars">${rows.map(row => { const value = row.on_time_orders / row.delivered_orders * 100; return `<div class="ops-col" title="${row.month.slice(0, 7)} · ${percent(value)}"><div style="height:${value}%"></div></div>` }).join('')}</div><div class="ops-labels"><span>${rows[0]?.month.slice(0, 7) ?? ''}</span><span>${rows.at(-1)?.month.slice(0, 7) ?? ''}</span></div></section>`
}

function render() {
  const content = page === 'intelligence'
    ? `<div class="section-title"><div><span class="eyebrow">MODEL OUTPUTS</span><h2>Signals from the warehouse</h2></div><p>Explore the predictions and behavioral groups.</p></div><div class="content-grid ai-layout">${riskPanel()}${segmentsPanel()}</div>`
    : page === 'operations'
      ? `${kpiCards()}<div class="content-grid ops-layout">${operationTrend()}${regionalPanel(true)}</div>`
      : page === 'revenue'
        ? `${kpiCards()}<div class="content-grid"><div class="main-column">${revenueChart()}${categoryPanel(true)}</div><div class="side-column">${paymentPanel()}</div></div>`
        : `${kpiCards()}<div class="content-grid"><div class="main-column">${revenueChart()}${regionalPanel()}</div><div class="side-column">${categoryPanel()}${paymentPanel()}</div></div>`
  app.innerHTML = `${nav()}<div class="main-shell">${topbar()}<main>${hero()}${content}<footer><span>OLIST COMMERCE STUDIO <b>·</b> HISTORICAL SNAPSHOT</span><span>Built on PostgreSQL warehouse metrics</span></footer></main></div>`
  app.querySelectorAll<HTMLButtonElement>('[data-page]').forEach(button => button.addEventListener('click', () => { page = button.dataset.page as Page; render(); window.scrollTo(0, 0) }))
  app.querySelectorAll<HTMLButtonElement>('[data-year]').forEach(button => button.addEventListener('click', () => { year = button.dataset.year!; render() }))
  app.querySelector<HTMLButtonElement>('[data-sort]')?.addEventListener('click', event => { regionSort = (event.currentTarget as HTMLButtonElement).dataset.sort as typeof regionSort; render() })
  app.querySelector<HTMLButtonElement>('[data-export]')?.addEventListener('click', exportCurrent)
}

function exportCurrent() {
  const rows: Record<string, string | number | null>[] = page === 'intelligence'
    ? data.segments.map(row => ({ segment: row.label, customers: row.count }))
    : page === 'operations' ? selectedRegions()
    : page === 'revenue' ? selectedCategories() : selectedMonths()
  if (!rows.length) return
  const headers = Object.keys(rows[0])
  const csv = [headers.join(','), ...rows.map(row => headers.map(key => `"${String(row[key] ?? '').replace(/"/g, '""')}"`).join(','))].join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = `olist-${page}-${year}.csv`; anchor.click()
  URL.revokeObjectURL(url)
}

fetch('/dashboard.json').then(response => {
  if (!response.ok) throw new Error('Dashboard snapshot unavailable')
  return response.json() as Promise<Snapshot>
}).then(snapshot => { data = snapshot; render() }).catch(() => {
  app.innerHTML = '<div class="load-error"><h1>Dashboard data unavailable</h1><p>Run the snapshot export and reload this page.</p></div>'
})
