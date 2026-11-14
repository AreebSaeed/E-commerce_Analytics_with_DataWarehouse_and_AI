type ModelInfo = {
  version: string; selected_model: string; train_rows: number; validation_rows: number
  test: { rows: number; precision: number; recall: number; f1: number }
  threshold: number; training_cutoff: string; test_cutoff: string; states: string[]
}
type Prediction = { late_probability: number; predicted_late: boolean; risk_band: string; threshold: number }

const options = (values: [string, string][], selected: string) => values.map(([value, label]) =>
  `<option value="${value}" ${value === selected ? 'selected' : ''}>${label}</option>`).join('')

function field(name: string, title: string, values: [string, string][], selected: string, hint = '') {
  return `<label class="predict-field"><span>${title}</span><select name="${name}" required>${options(values, selected)}</select>${hint ? `<small>${hint}</small>` : ''}</label>`
}

const numeric = (values: number[], suffix = ''): [string, string][] => values.map(value => [String(value), `${value.toLocaleString()}${suffix}`])

function form(info: ModelInfo) {
  const states: [string, string][] = info.states.map(state => [state, state])
  const months: [string, string][] = ['January','February','March','April','May','June','July','August','September','October','November','December'].map((label, i) => [String(i + 1), label])
  const weekdays: [string, string][] = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map((label, i) => [String(i + 1), label])
  return `<div class="predict-layout"><form class="panel predict-form" id="predict-form">
    <div class="panel-header"><div><span class="eyebrow">TRY THE TRAINED MODEL</span><h2>Order details</h2></div><span class="panel-tag">12 model inputs</span></div>
    <p class="predict-intro">Choose details that would be known when an order is placed.</p>
    <div class="predict-group"><h3>When and where</h3><div class="predict-fields">
      ${field('purchase_month', 'Purchase month', months, '6')}
      ${field('purchase_weekday', 'Purchase weekday', weekdays, '1')}
      ${field('customer_state', 'Customer state', states, info.states.includes('SP') ? 'SP' : info.states[0])}
      ${field('seller_state', 'Seller state', states, info.states.includes('SP') ? 'SP' : info.states[0])}
      ${field('seller_customer_distance_km', 'Seller to customer distance', numeric([0, 50, 200, 500, 1000, 2000, 3000], ' km'), '200', 'Approximate geographic distance')}
    </div></div>
    <div class="predict-group"><h3>Items and price</h3><div class="predict-fields">
      ${field('item_count', 'Number of items', numeric([1, 2, 3, 4, 5, 10]), '1')}
      ${field('item_price', 'Total item price', numeric([25, 50, 100, 200, 500, 1000], ' BRL'), '100')}
      ${field('freight_value', 'Freight value', numeric([0, 10, 20, 40, 80, 150], ' BRL'), '20')}
      ${field('total_weight_g', 'Total known weight', numeric([0, 250, 500, 1000, 3000, 10000], ' g'), '500')}
      ${field('weight_known_items', 'Items with known weight', numeric([0, 1, 2, 3, 4, 5, 10]), '1')}
      ${field('total_volume_cm3', 'Total known volume', numeric([0, 1000, 5000, 10000, 30000, 100000], ' cm³'), '5000')}
      ${field('volume_known_items', 'Items with known volume', numeric([0, 1, 2, 3, 4, 5, 10]), '1')}
    </div></div><div class="predict-actions"><button class="predict-submit" type="submit">Predict delivery risk <span>→</span></button><span>Runs the saved ${info.selected_model.replace('_', ' ')} model locally</span></div>
  </form><div class="predict-side"><section class="panel result-panel" aria-live="polite"><span class="eyebrow">PREDICTION</span><div id="prediction-result" class="result-empty"><div class="result-orb">✦</div><h2>Ready when you are</h2><p>Choose the order details, then select Predict delivery risk.</p></div></section>
  <section class="panel model-context"><span class="eyebrow">MODEL EVALUATION</span><h2>How this model was tested</h2><div class="split-bar"><span style="width:70%"></span><span style="width:15%"></span><span style="width:15%"></span></div><div class="split-labels"><span>70% train</span><span>15% validate</span><span>15% test</span></div>
  <p>Orders were split by purchase time. The final model was fitted on training and validation rows; the later test rows were held out.</p><div class="model-stats"><div><strong>${info.train_rows.toLocaleString()}</strong><span>Training rows</span></div><div><strong>${info.validation_rows.toLocaleString()}</strong><span>Validation rows</span></div><div><strong>${info.test.rows.toLocaleString()}</strong><span>Test rows</span></div></div><div class="model-quality"><div><span>Test precision</span><strong>${(info.test.precision * 100).toFixed(1)}%</strong></div><div><span>Test recall</span><strong>${(info.test.recall * 100).toFixed(1)}%</strong></div><div><span>Test F1</span><strong>${info.test.f1.toFixed(3)}</strong></div></div><p class="model-caution">Test performance is weak. This is a learning demo, not a dependable delivery warning.</p></section></div></div>`
}

export async function mountPredictor(container: HTMLElement) {
  container.innerHTML = '<div class="panel predict-loading">Loading saved model…</div>'
  try {
    const response = await fetch('/api/model')
    if (!response.ok) throw new Error('Prediction server is unavailable.')
    const info = await response.json() as ModelInfo
    if (!container.isConnected) return
    container.innerHTML = form(info)
    const formElement = container.querySelector<HTMLFormElement>('#predict-form')!
    formElement.addEventListener('submit', async event => {
      event.preventDefault()
      const button = formElement.querySelector<HTMLButtonElement>('button[type=submit]')!
      const result = container.querySelector<HTMLDivElement>('#prediction-result')!
      const values = Object.fromEntries(new FormData(formElement).entries())
      const payload = Object.fromEntries(Object.entries(values).map(([key, value]) =>
        [key, key.endsWith('_state') ? value : Number(value)]))
      button.disabled = true
      result.innerHTML = '<p class="result-wait">Calculating prediction…</p>'
      try {
        const response = await fetch('/api/predict', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
        const body = await response.json()
        if (!response.ok) throw new Error(body.error || 'Prediction failed.')
        const prediction = body as Prediction
        const probability = (prediction.late_probability * 100).toFixed(1)
        const resultClass = prediction.predicted_late ? 'high' : 'low'
        result.innerHTML = `<div class="result-complete ${resultClass}"><div class="result-orb">${prediction.predicted_late ? '!' : '✓'}</div><div class="result-kicker">${prediction.risk_band} RISK BAND</div><h2>${prediction.predicted_late ? 'Late delivery flagged' : 'Late delivery not flagged'}</h2><div class="result-number">${probability}%</div><p>Model score for late delivery</p><div class="result-meter"><span style="width:${probability}%"></span></div><div class="result-threshold">Decision cutoff: ${(prediction.threshold * 100).toFixed(0)}%</div></div>`
      } catch (error) {
        result.textContent = error instanceof Error ? error.message : 'Prediction failed.'
      } finally { button.disabled = false }
    })
  } catch {
    container.innerHTML = '<div class="panel predict-loading"><h2>Prediction server unavailable</h2><p>Build the dashboard, then start <code>python web/predict_api.py</code>. See web/README.md for the commands.</p></div>'
  }
}
