/* Short foreground executions use owned keys, explicit quotes and the existing ledger. */
async function dashSandbox() {
  const data = await api('/api/api-keys');
  if (location.pathname !== '/dashboard/sandbox') return;
  const keys = (data.keys || []).filter(k => !k.revoked_at && (!k.expires_at || new Date(k.expires_at) > new Date()) && (k.scopes || []).some(s => s === 'mcp:execute' || s === '*'));
  dashboardShell('sandbox', pageHead('ISOLATED EXECUTION', 'Sandbox',
    'Run a short shell command in an isolated computer. Review credits first; files are temporary.') +
    (keys.length ? `<section class="sandbox-workbench"><form id="sandbox-form">
      <label>Execution key<select id="sandbox-key">${keys.map(k => `<option value="${esc(k.id)}">${esc(k.name)} · ${esc(k.prefix || '')}…</option>`).join('')}</select></label>
      <label>Command<textarea id="sandbox-command" rows="6" maxlength="50000" required spellcheck="false">printf 'opencrawl-sandbox-ok\\n'; printf 'stderr-ok\\n' &gt;&amp;2</textarea></label>
      <label>Timeout (seconds)<input id="sandbox-timeout" type="number" min="1" max="15" value="10" required></label>
      <button type="submit" class="btn primary" id="sandbox-quote">Review credits</button>
      <div id="sandbox-review" role="status" aria-live="polite"></div>
      <button type="button" class="btn primary" id="sandbox-run" disabled>Run command</button>
      </form><section id="sandbox-output" aria-live="polite"><p>stdout, stderr, exit code, cleanup and settled credits appear here.</p></section></section>` :
      `<section class="search-key-lock"><h2>An execution key is required</h2><p>Select an active key with execution access before using Sandbox.</p><a data-link class="btn" href="/dashboard/api-keys">API Keys</a></section>`));
  if (!keys.length) return;
  const form = $('#sandbox-form'), review = $('#sandbox-review'), output = $('#sandbox-output');
  const run = $('#sandbox-run'), quoteButton = $('#sandbox-quote');
  let quote = null, quotedInput = null, busy = false, generation = 0;
  const inputs = () => ({api_key_id: $('#sandbox-key').value, command: $('#sandbox-command').value, timeout_seconds: Number($('#sandbox-timeout').value)});
  const fingerprint = () => JSON.stringify(inputs());
  const present = () => location.pathname === '/dashboard/sandbox' && document.contains(form);
  const invalidate = () => { generation++; quote = null; quotedInput = null; run.disabled = true; review.textContent = 'Review credits for the current inputs before running.'; };
  form.addEventListener('input', invalidate);
  form.addEventListener('change', invalidate);
  const lock = value => {
    busy = value;
    form.querySelectorAll('input,textarea,select').forEach(el => { el.disabled = value; });
    quoteButton.disabled = value;
    run.disabled = value || !quote || !quote.affordable || !quote.allowed || quotedInput !== fingerprint();
  };
  form.onsubmit = async event => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    const version = ++generation, input = fingerprint();
    quote = null; quotedInput = null; lock(true); review.textContent = 'Checking execution access and credits…';
    try {
      const result = await api('/api/sandbox/quote', {method: 'POST', body: inputs()});
      if (!present() || version !== generation || input !== fingerprint()) return;
      quote = result.quote; quotedInput = input;
      review.textContent = `Maximum charge: ${fmt(quote.maximum_charge_credits)} credits · ${fmt(quote.available_credits)} available. ${quote.affordable && quote.allowed ? 'Run sends this command to the isolated computer and uses credits. Only run commands you trust.' : 'Execution is unavailable or the balance is too low.'}`;
    } catch (error) { if (present()) review.textContent = error.message; }
    finally { if (present()) lock(false); }
  };
  run.onclick = async () => {
    if (busy || !quote || quotedInput !== fingerprint()) return;
    const body = {...inputs(), allow_execution: true, max_charge_credits: quote.maximum_charge_credits, quote_revision: quote.quote_revision};
    quote = null; quotedInput = null; generation++; lock(true);
    output.textContent = 'Starting isolated execution…'; review.textContent = 'Run in progress. Do not retry until its result appears.';
    try {
      const result = await api('/api/sandbox/run', {method: 'POST', body});
      if (!present()) return;
      const command = result.result?.data || {}, cleanup = result.result?.cleanup;
      output.innerHTML = `<h2>${result.ok ? 'Command completed' : 'Command failed'}</h2>
        <p>Exit code: ${esc(command.exit_code == null ? 'unknown' : String(command.exit_code))} · ${fmt(result.usage?.credits_charged)} credits charged · ${result.usage?.settled ? 'Settled' : 'Settlement unconfirmed'}</p>
        <h3>stdout</h3><pre>${esc(command.stdout || '(empty)')}</pre><h3>stderr</h3><pre>${esc(command.stderr || '(empty)')}</pre>
        ${command.truncated ? '<p role="alert">Output exceeded the response limit and was truncated.</p>' : ''}
        ${result.result?.error ? `<p role="alert">${esc(result.result.error)}</p>` : ''}
        <p>Cleanup: ${esc(cleanup?.status || 'unconfirmed')}${cleanup?.status === 'stopped' ? ' · compute stopped; named record remains' : ''}</p>
        ${cleanup?.status === 'failed' || !cleanup ? '<p role="alert">Cleanup could not be confirmed. The Sandbox lifetime remains bounded.</p>' : ''}
        <p>Request: <code>${esc(result.request_id)}</code></p><a data-link href="/dashboard/runs?run=${encodeURIComponent(result.request_id)}">View execution ledger</a>`;
      bindCommon(); review.textContent = 'Review a fresh quote before another run.';
    } catch (error) {
      if (present()) { output.textContent = error.message + (error.requestId ? ` Request: ${error.requestId}. Check Runs before retrying.` : ''); review.textContent = 'Execution was not confirmed. Review Runs before retrying.'; }
    } finally { if (present()) lock(false); }
  };
}
