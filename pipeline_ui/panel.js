const byId = id => document.getElementById(id)
const labels = { pending: 'Waiting', running: 'Running', succeeded: 'Complete', failed: 'Failed' }
const markers = { pending: '○', running: '●', succeeded: '✓', failed: '!' }
const modelName = value => ({ logistic_regression: 'Logistic regression', random_forest: 'Random forest' })[value] ?? value

let snapshot
let selected
let stageSignature
let outputSignature
let connected = false
let starting = false

function node(tag, content, className) {
  const element = document.createElement(tag)
  if (content !== undefined) element.textContent = content
  if (className) element.className = className
  return element
}

function showMessage(text) {
  byId('message').textContent = text
  byId('message').hidden = !text
}

function section(title, content) {
  const group = node('section', undefined, 'summary-section')
  group.append(node('h3', title), content)
  return group
}

function metrics(title, entries) {
  const grid = node('div', undefined, 'metric-grid')
  for (const [label, value] of entries) {
    const card = node('div', undefined, 'metric')
    card.append(node('span', label), node('strong', value))
    grid.append(card)
  }
  return section(title, grid)
}

function table(title, headers, entries) {
  const wrap = node('div', undefined, 'table-scroll')
  const table = node('table')
  const head = table.createTHead().insertRow()
  for (const label of headers) {
    const header = node('th', label)
    header.scope = 'col'
    head.append(header)
  }
  const body = table.createTBody()
  for (const entry of entries) {
    const row = body.insertRow()
    for (const value of entry) {
      const cell = row.insertCell()
      if (typeof value === 'string') cell.textContent = value
      else cell.append(value)
    }
  }
  wrap.append(table)
  return section(title, wrap)
}

function artifact(title, path) {
  return section(title, node('p', path, 'artifact'))
}

function matches(lines, pattern) {
  return Array.from(lines.matchAll(pattern), result => result.slice(1))
}

function summarize(stage) {
  const lines = stage.lines.join('\n')
  const cards = []
  if (stage.id === 'warehouse') {
    const run = lines.match(/^Run (\d+) succeeded\. Audit details: (.+)$/m)
    const tables = matches(lines, /^\s+(\w+): ([\d,]+) rows$/gm)
    if (run) cards.push(metrics('Warehouse validation', [['Successful run', run[1]], ['Audit table', run[2]]]))
    if (tables.length) cards.push(table('CSV rows loaded', ['Dataset', 'Rows'], tables.map(([name, total]) => [name.replaceAll('_', ' '), total])))
  }
  if (stage.id === 'delivery') {
    const split = lines.match(/^Labeled orders: train ([\d,]+), validation ([\d,]+), test ([\d,]+)$/m)
    const test = lines.match(/^Selected (\w+); held-out test: precision=([\d.]+), recall=([\d.]+), F1=([\d.]+)$/m)
    const validation = matches(lines, /^(\w+) validation: precision=([\d.]+), recall=([\d.]+), F1=([\d.]+), cutoff=([\d.]+)$/gm)
    const confusion = lines.match(/^Confusion matrix: TN=(\d+), FP=(\d+), FN=(\d+), TP=(\d+)$/m)
    const saved = lines.match(/^Saved ([\d,]+) order scores and model (.+)$/m)
    if (test) cards.push(metrics('Held-out test', [['Model', modelName(test[1])], ['Precision', test[2]], ['Recall', test[3]], ['F1', test[4]]]))
    if (split) cards.push(metrics('Labeled orders', [['Training', split[1]], ['Validation', split[2]], ['Test', split[3]]]))
    if (validation.length) cards.push(table('Validation scores', ['Model', 'Precision', 'Recall', 'F1', 'Cutoff'],
      validation.map(([model, ...scores]) => [modelName(model), ...scores])))
    if (confusion) cards.push(metrics('Confusion matrix', ['True negatives', 'False positives', 'False negatives', 'True positives']
      .map((label, index) => [label, Number(confusion[index + 1]).toLocaleString('en-US')])))
    if (saved) cards.push(artifact(`Model file · ${saved[1]} order scores saved`, saved[2]))
  }
  if (stage.id === 'segments') {
    const chosen = lines.match(/^Selected k=(\d+); saved ([\d,]+) customer segments$/m)
    const scores = matches(lines, /^k=(\d+): sample silhouette=(-?[\d.]+)$/gm)
    const groups = matches(lines, /^\s{2}(.+): ([\d,]+) customers$/gm)
    if (chosen) cards.push(metrics('Segmentation result', [['Selected clusters', chosen[1]], ['Customers segmented', chosen[2]]]))
    if (groups.length) cards.push(table('Customer segments', ['Segment', 'Customers'], groups))
    if (scores.length) cards.push(table('Sample silhouette scores', ['Clusters', 'Score', 'Scale (−1 to 1)'], scores.map(([count, score]) => {
      const bar = node('meter')
      bar.min = -1
      bar.max = 1
      bar.value = Number(score)
      bar.setAttribute('aria-label', `Silhouette score for ${count} clusters`)
      return [count, score, bar]
    })))
  }
  if (stage.id === 'snapshot') {
    const path = lines.match(/^Exported aggregate dashboard snapshot to (.+)$/m)
    if (path) cards.push(artifact('Exported dashboard data', path[1]))
  }
  if (stage.id === 'build') {
    const assets = matches(lines, /^(dist\/\S+)\s+([\d.]+ \wB)(?:\s+│ gzip:\s+([\d.]+ \wB))?$/gm)
    const built = lines.match(/built in (\S+)/)
    if (built) cards.push(metrics('Frontend build', [['Build time', built[1]], ['Files emitted', String(assets.length)]]))
    if (assets.length) cards.push(table('Build output', ['File', 'Size', 'Gzip'], assets.map(([file, size, gzip]) => [file, size, gzip ?? '—'])))
  }
  return cards
}

function render() {
  if (!snapshot) return
  const { stages, next, dashboard } = snapshot
  selected ??= next ?? stages.at(-1).id
  const stage = stages.find(item => item.id === selected)
  const count = stages.filter(item => item.status === 'succeeded').length
  byId('progress').max = stages.length
  byId('progress').value = count
  byId('completed').textContent = `${count} / ${stages.length}`

  const newStageSignature = JSON.stringify([selected, next, connected, starting, stages.map(item => item.status)])
  if (newStageSignature !== stageSignature) {
    stageSignature = newStageSignature
    const list = byId('stages')
    const controls = stages.map(item => {
      const row = node('div', undefined, `stage${selected === item.id ? ' selected' : ''}`)
      const view = node('button', undefined, 'stage-control')
      view.type = 'button'
      view.setAttribute('aria-pressed', String(selected === item.id))
      view.addEventListener('click', () => {
        selected = item.id;
        render()
      })
      const marker = node('span', markers[item.status], `stage-marker ${item.status}`)
      marker.setAttribute('aria-hidden', 'true')
      const name = node('span', item.title, 'stage-name')
      name.append(node('span', next === item.id && item.status === 'pending' ? 'Ready' : labels[item.status], 'stage-state'))
      view.append(marker, name)
      row.append(view)
      if (next === item.id && connected && !starting) {
        const run = node('button', item.status === 'failed' ? 'Retry' : 'Run', 'run')
        run.type = 'button'
        run.setAttribute('aria-label', `${run.textContent} — ${item.title}`)
        run.addEventListener('click', () => start(item.id))
        row.append(run)
      }
      return row
    })
    list.replaceChildren(...controls)
  }

  byId('stage-title').textContent = stage.title
  const badge = byId('stage-status')
  const status = next === stage.id && stage.status === 'pending' ? 'Ready' : labels[stage.status]
  if (badge.textContent !== status) badge.textContent = status
  badge.className = `status ${stage.status}`
  const link = byId('dashboard')
  link.hidden = stage.id !== 'dashboard' || !dashboard
  if (dashboard) link.href = dashboard

  const log = byId('log')
  const newOutputSignature = JSON.stringify([stage.id, stage.status, stage.lines])
  if (newOutputSignature !== outputSignature) {
    const wasFollowing = !outputSignature || log.scrollHeight - log.scrollTop - log.clientHeight < 20
    outputSignature = newOutputSignature
    byId('summary').replaceChildren(...summarize(stage))
    byId('line-count').textContent = `${stage.lines.length} ${stage.lines.length === 1 ? 'line' : 'lines'}`
    log.textContent = stage.lines.join('\n') || (stage.status === 'running' ? 'Waiting for process output…' : 'Output will appear here when this stage runs.')
    if (wasFollowing) log.scrollTop = log.scrollHeight
  }
}

async function refresh() {
  const indicator = byId('connection')
  try {
    const response = await fetch('/api/status')
    if (!response.ok) throw new Error('Status unavailable')
    snapshot = await response.json()
    connected = true
    indicator.textContent = 'Local runner connected'
    indicator.classList.remove('offline')
  } catch {
    connected = false
    indicator.textContent = 'Local runner disconnected'
    indicator.classList.add('offline')
  }
  render()
}

async function start(id) {
  starting = true
  selected = id
  showMessage('')
  render()
  try {
    const response = await fetch(`/api/run/${id}`, { method: 'POST', headers: { 'X-Olist-Request': 'stage' } })
    if (!response.ok) throw new Error((await response.json()).message)
  } catch (error) {
    showMessage(error.message)
  } finally {
    await refresh()
    starting = false
    render()
  }
}

async function poll() {
  if (!starting) await refresh()
  setTimeout(poll, 750)
}

poll()
