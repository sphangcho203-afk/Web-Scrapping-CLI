/* Product prices: source preview → saved dataset → recurring field checks. */
let productTrackerView = 0;

async function dashProductTracker() {
  const view = ++productTrackerView;
  clearTimeout(state.productRunTimer);
  state.productController?.abort();
  const controller = new AbortController();
  state.productController = controller;
  const current = () => view === productTrackerView && location.pathname === '/dashboard/products' && !controller.signal.aborted;
  const request = (path, options = {}) => api(path, {...options, signal: controller.signal});
  const query = new URL(location.href).searchParams;
  const runId = query.get('run'), trackerId = query.get('tracker');
  const [keyData, monitorData] = await Promise.all([request('/api/api-keys'), request('/api/monitors')]);
  if (!current()) return;
  const keys = (keyData.keys || []).filter(k => !k.revoked_at && (!k.expires_at || new Date(k.expires_at) > new Date()) && (!k.scopes || k.scopes.includes('*') || k.scopes.includes('mcp:execute')));
  const trackers = (monitorData.monitors || []).filter(m => m.type === 'product');
  const credits = value => fmt(Number(value || 0)) + ' credits';
  const productTable = rows => '<div class="table-wrap"><table><thead><tr><th>Product</th><th>Published price</th><th>Availability</th></tr></thead><tbody>' + rows.map(row => '<tr><td><b>' + esc(row.name) + '</b><small>' + esc(row.sku || row.source_url) + '</small></td><td>' + esc(row.currency) + ' ' + esc(row.price) + '</td><td>' + esc(row.availability || 'Not published') + '</td></tr>').join('') + '</tbody></table></div>';
  dashboardShell('products', pageHeadline('PRICE TRACKER', 'Watch the fields that matter', 'Preview a published product price, keep the dataset, then track price and availability changes.', '<a class="btn" data-link href="/dashboard/datasets">Datasets</a>') +
    '<ol class="product-steps"><li><b>01</b> Review collection cost</li><li><b>02</b> Preview & save products</li><li><b>03</b> Enable change tracking</li></ol>' +
    '<section class="product-workspace"><article class="card product-create"><header><h2>' + (runId ? 'Your product preview' : trackerId ? 'Tracking history' : 'Start with a product page') + '</h2><a data-link href="/dashboard/products">New preview</a></header>' +
    (!runId && !trackerId ? '<form id="product-preview-form" class="form-stack"><label>Product page URL<input name="url" type="url" maxlength="2000" required placeholder="https://shop.example/product"></label><label>Execution key<select name="api_key_id" required>' + keys.map(k => '<option value="' + esc(k.id) + '">' + esc(k.name || k.prefix) + '</option>').join('') + '</select></label>' + (!keys.length ? '<p class="notice">Create an execution key to attribute charges and apply spending limits. <a data-link href="/dashboard/api-keys">Create API key →</a></p>' : '') + '<button class="btn primary" type="submit" ' + (!keys.length ? 'disabled' : '') + '>Review preview cost</button></form><div id="product-quote" aria-live="polite"></div>' : '') +
    '<div id="product-result" aria-live="polite"></div></article><aside class="card product-explainer"><span class="overline">SOURCE FIRST</span><h2>A price you can inspect</h2><p>Reads Product / Offer data published by the page. Prices remain in their original currency, with a source URL and capture time.</p><p>Pages requiring JavaScript, sign-in, or missing a published offer may not work. An unusable product preview releases its credit reservation.</p><p>Only selected product fields trigger a changed snapshot. Checks consume credits even when the product is unchanged. Missing prices preserve the last good baseline.</p><a data-link href="/dashboard/billing">Recover a pending purchase →</a></aside></section>' +
    '<section class="card product-tracker-list"><header><h2>Your trackers</h2><span>' + fmt(trackers.length) + ' saved</span></header>' + (trackers.length ? '<div class="product-trackers">' + trackers.map(m => '<article><div><b>' + esc(m.name) + '</b><small>' + esc(m.target) + '</small></div><span class="badge">' + esc(!m.enabled ? 'Paused' : m.last_status || 'Waiting') + '</span><small>' + credits(m.config?.max_charge_credits) + ' maximum / check</small><a class="btn small" data-link href="/dashboard/products?tracker=' + encodeURIComponent(m.id) + '">Inspect</a></article>').join('') + '</div>' : '<p>No trackers yet. A successful preview becomes the baseline when you enable tracking.</p>') + '</section>');
  const result = $('#product-result');

  async function showRun(data) {
    if (!current()) return;
    const run = data.run, rows = data.products || [], active = ['queued','running'].includes(run.status);
    const messages = {product_price_unavailable:'This page does not publish a usable product price. Try a product detail page with Product / Offer metadata.', ambiguous_product_offers:'The page publishes conflicting offers. No price was selected.', product_data_limit:'The published product data exceeds the preview limits.', invalid_product_data:'The page contains malformed product metadata.', product_page_unavailable:'The product page could not be read.'};
    result.innerHTML = '<div class="product-run-summary"><span class="badge">' + esc(run.status) + '</span><p>' + credits(run.credits_charged) + ' charged · ' + credits(run.credits_reserved) + ' ' + (active ? 'reserved' : 'original reservation') + '</p>' + (!active ? '<p>' + credits(Math.max(0, run.credits_reserved - run.credits_charged)) + ' reservation released.</p>' : '') + '</div>' +
      (active ? '<p role="status">Collecting published product data. You can return to this preview later.</p><button class="btn" id="product-cancel">Cancel preview</button>' : run.status !== 'completed' ? '<p role="alert" class="notice warning">' + esc(messages[run.error_code] || 'The preview did not complete. ' + (run.error_code || run.status).replaceAll('_',' ')) + '</p>' : '') +
      (rows.length ? productTable(rows) + '<p>Source: <span>' + esc(rows[0].source_url) + '</span> · captured ' + esc(when(rows[0].captured_at)) + '</p><div class="product-actions"><a class="btn" data-link href="/dashboard/datasets?dataset=' + encodeURIComponent(run.dataset_id) + '">Open saved dataset</a><a class="btn" href="/api/datasets/' + encodeURIComponent(run.dataset_id) + '/export?format=csv" download>Download CSV</a></div>' +
        '<form id="product-track-form" class="form-stack"><h3>Enable recurring tracking</h3><label>Tracker name<input name="name" required maxlength="120" value="' + esc(rows[0].name) + '"></label><fieldset><legend>Fields to watch</legend><label class="product-check"><input type="checkbox" name="price" checked> Price (including currency)</label><label class="product-check"><input type="checkbox" name="availability" checked> Availability</label></fieldset><div class="field-pair"><label>Check interval<select name="interval_minutes"><option value="1440">Daily</option><option value="360">Every 6 hours</option><option value="60">Hourly</option></select></label><label>Maximum credits per check<input name="maximum" type="number" min="0" max="1000000000" step="1" required value="' + Number(run.credits_reserved) + '"></label></div><p>Schedules are approximate and run through the existing worker. Changes save a new dataset and appear in tracker history. Configure a <a data-link href="/dashboard/datasets?webhooks=1">signed dataset webhook</a> for external alerts.</p><label class="product-check"><input name="consent" type="checkbox" required> I agree to recurring credit charges, including unchanged checks, up to this per-check limit.</label><button class="btn primary" type="submit">Enable tracking</button><p id="product-track-error" role="alert"></p></form>' : run.status === 'completed' ? '<p>The saved preview was deleted. Collect another preview before enabling tracking.</p>' : '');
    const cancel = $('#product-cancel');
    if (cancel) cancel.onclick = async () => {
      if (!busy(cancel, true, 'Cancelling…')) return;
      try { await request('/api/crawl-runs/' + encodeURIComponent(run.id) + '/cancel', {method:'POST'}); await poll(run.id); }
      catch (error) { if (current()) { toast(error.message, 'error'); busy(cancel, false); } }
    };
    const form = $('#product-track-form');
    if (form) form.onsubmit = async event => {
      event.preventDefault();
      const fields = ['price','availability'].filter(f => form.elements[f].checked), maximum = Number(form.elements.maximum.value);
      if (!fields.length || !Number.isSafeInteger(maximum) || maximum < 0) { $('#product-track-error').textContent = 'Select a field and a whole-credit limit.'; return; }
      const button = event.submitter;
      if (!busy(button, true, 'Enabling…')) return;
      try {
        const saved = await request('/api/product-trackers', {method:'POST', body:{run_id:run.id, name:form.elements.name.value, fields, interval_minutes:Number(form.elements.interval_minutes.value), max_charge_credits:maximum, confirm_recurring:form.elements.consent.checked}});
        if (current()) go('/dashboard/products?tracker=' + encodeURIComponent(saved.monitor.id));
      } catch (error) { if (current()) { $('#product-track-error').textContent = error.message; busy(button, false); } }
    };
    if (active) state.productRunTimer = setTimeout(() => poll(run.id), 5000);
  }

  async function poll(id) {
    clearTimeout(state.productRunTimer);
    try { const data = await request('/api/product-tracker/runs/' + encodeURIComponent(id)); await showRun(data); }
    catch (error) { if (current()) { result.innerHTML = '<p role="alert">' + esc(error.message) + '</p><button class="btn" id="product-poll-retry">Retry status check</button>'; $('#product-poll-retry').onclick = () => poll(id); } }
  }

  if (runId) { await poll(runId); return; }
  if (trackerId) {
    const monitor = await request('/api/monitors/' + encodeURIComponent(trackerId));
    if (!current()) return;
    if (monitor.type !== 'product') { result.textContent = 'This monitor is not a product tracker.'; return; }
    let rows = [];
    if (monitor.baseline_dataset_id) {
      try { rows = (await request('/api/datasets/' + encodeURIComponent(monitor.baseline_dataset_id))).rows || []; }
      catch (error) { if (error.status !== 404) throw error; }
    }
    if (!current()) return;
    result.innerHTML = '<h3>' + esc(monitor.name) + '</h3><p>' + esc(monitor.target) + '</p><p>' + (monitor.enabled ? 'Enabled · next check approximately ' + esc(when(monitor.next_check_at)) : 'Paused') + ' · ' + credits(monitor.config.max_charge_credits) + ' maximum / check</p><p>Watching ' + esc(monitor.config.fields.join(' and ')) + '. Last successful capture stays available when a check fails.</p>' +
      (rows.length ? productTable(rows) : '<p>The previous snapshot is unavailable.</p>') + '<div class="product-actions"><button class="btn" id="product-pause">' + (monitor.enabled ? 'Pause tracking' : 'Resume tracking') + '</button><a class="btn" data-link href="/dashboard/monitors">Edit schedule or limits</a></div><h3>Check history</h3>' +
      ((monitor.runs || []).length ? monitor.runs.map(check => '<article class="product-history"><header><b>' + esc(check.status) + '</b><small>' + esc(when(check.created_at)) + ' · ' + credits(check.credits_charged) + '</small></header><p>' + esc(check.summary) + '</p>' + (check.diff?.changes ? '<ul>' + check.diff.changes.map(change => { const name = rows.find(row => row.product_id === change.product_id)?.name || 'Product offer'; const values = value => value ? [value.price != null ? (value.currency || '') + ' ' + value.price : '', value.availability || ''].filter(Boolean).join(' · ') || 'No selected value' : 'Not present'; return '<li>' + esc(name) + ': ' + esc(values(change.before)) + ' → ' + esc(values(change.after)) + '</li>'; }).join('') + '</ul>' : '') + (check.dataset_id ? '<a data-link href="/dashboard/datasets?dataset=' + encodeURIComponent(check.dataset_id) + '">Open snapshot →</a>' : '') + '</article>').join('') : '<p>The preview is your baseline. Scheduled checks will appear here.</p>');
    $('#product-pause').onclick = async event => {
      const button = event.currentTarget;
      if (!busy(button, true, 'Saving…')) return;
      try { await request('/api/monitors/' + encodeURIComponent(monitor.id) + '/toggle', {method:'POST', body:{enabled:!monitor.enabled}}); if (current()) await dashProductTracker(); }
      catch (error) { if (current()) { toast(error.message, 'error'); busy(button, false); } }
    };
    return;
  }

  const form = $('#product-preview-form'), quoteBox = $('#product-quote');
  let quoteBody = null;
  form.oninput = () => { quoteBody = null; quoteBox.innerHTML = ''; };
  form.onsubmit = async event => {
    event.preventDefault();
    const button = event.submitter;
    if (!busy(button, true, 'Reviewing…')) return;
    const body = {url:form.elements.url.value.trim(), api_key_id:form.elements.api_key_id.value};
    try {
      const response = await request('/api/product-tracker/quote', {method:'POST', body});
      if (!current() || body.url !== form.elements.url.value.trim() || body.api_key_id !== form.elements.api_key_id.value) return;
      const quote = response.quote;
      quoteBody = {...body, max_charge_credits:quote.credits, quote_revision:quote.quote_revision};
      quoteBox.innerHTML = '<section class="product-cost-review"><h3>Preview cost reviewed</h3><p>Maximum ' + credits(quote.credits) + ' · ' + credits(quote.available_credits) + ' available.</p><p>This collects one public page and saves usable product records. It does not enable recurring tracking.</p>' + (!quote.affordable ? '<p class="notice warning">More credits are required. <a data-link href="/dashboard/wallet">Get usage credits</a></p>' : '') + '<button class="btn primary" id="product-confirm-preview" ' + (!quote.affordable ? 'disabled' : '') + '>Confirm & collect preview</button><p id="product-preview-error" role="alert"></p></section>';
      $('#product-confirm-preview').onclick = async click => {
        const confirm = click.currentTarget, submitted = quoteBody;
        if (!submitted || !busy(confirm, true, 'Collecting…')) return;
        form.elements.url.disabled = true; form.elements.api_key_id.disabled = true;
        const fingerprint = JSON.stringify(submitted);
        let cached;
        try { cached = JSON.parse(sessionStorage.getItem('opencrawl-product-preview') || 'null'); } catch (_) {}
        const key = cached?.fingerprint === fingerprint ? cached.key : 'product:' + crypto.randomUUID();
        try { sessionStorage.setItem('opencrawl-product-preview', JSON.stringify({fingerprint, key})); } catch (_) {}
        try {
          const data = await request('/api/product-tracker/runs', {method:'POST', body:submitted, headers:{'Idempotency-Key':key}});
          if (current()) { try { sessionStorage.removeItem('opencrawl-product-preview'); } catch (_) {} go('/dashboard/products?run=' + encodeURIComponent(data.run.id)); }
        } catch (error) { if (current()) { $('#product-preview-error').textContent = error.message; busy(confirm, false); form.elements.url.disabled = false; form.elements.api_key_id.disabled = false; } }
      };
    } catch (error) { if (current()) quoteBox.innerHTML = '<p role="alert" class="notice warning">' + esc(error.message) + '</p>'; }
    finally { if (current()) busy(button, false); }
  };
}
