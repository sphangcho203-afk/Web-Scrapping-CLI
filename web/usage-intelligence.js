/* Goal 2: telemetry-backed Overview + Usage surfaces. */
(() => {
  const usageWindow = () => sessionStorage.getItem('ih_usage_window') || '30d';
  const setUsageWindow = value => sessionStorage.setItem('ih_usage_window', value);
  const statusTone = status => ['ok','accepted'].includes(String(status || '').toLowerCase()) ? 'ok' : 'bad';
  const metric = (label, value, note='') => `<div><span>${esc(label)}</span><b>${value}</b>${note ? `<small>${esc(note)}</small>` : ''}</div>`;
  const windows = active => `<div class="ih-run-hints" data-usage-windows><span>Window</span>${['24h','7d','30d','90d'].map(w => `<button type="button" data-usage-window="${w}" aria-pressed="${String(w===active)}">${w}</button>`).join('')}</div>`;
  const bindWindows = rerender => $$('[data-usage-window]').forEach(button => button.addEventListener('click', () => { setUsageWindow(button.dataset.usageWindow); rerender(); }));
  const runRows = events => events.length ? events.map((e,i)=>`<button class="ih-run-table-row" data-run-index="${i}"><span>${statusDot(statusTone(e.status))}<b>${esc(e.status||'unknown')}</b></span><span><b>${esc(runLabel(e))}</b><code>${esc((e.request_id||'—').slice(0,22))}</code></span><span data-label="Provider">${esc(e.provider||'—')}</span><span data-label="Credits">${fmt(e.credits_charged||0)}</span><span data-label="Latency">${e.latency_ms==null?'—':`${fmt(e.latency_ms)} ms`}</span><span data-label="Time">${esc(when(e.created_at))}</span><span>${icon('arrow')}</span></button>`).join('') : `<div class="ih-empty-run large"><span>${icon('activity')}</span><div><b>No telemetry in this window</b><p>Nothing is fabricated. Execute a metered request or choose a wider time window.</p></div></div>`;
  const breakdown = (title, rows) => `<article class="ih-system-panel"><header><span>BREAKDOWN</span><h2>${esc(title)}</h2></header>${rows.length ? rows.map(row=>`<div class="ih-system-row"><span>${statusDot(statusTone(row.name))}</span><div><b>${esc(row.name)}</b><small>${fmt(row.requests)} requests · ${fmt(row.credits)} credits</small></div><em>${fmt(row.avg_latency_ms)} ms</em></div>`).join('') : `<div class="ih-empty-run"><div><b>Unavailable</b><p>No metered events in this window.</p></div></div>`}</article>`;

  const trendGlyph = (value, max) => {
    if (!max || !value) return '▁';
    const glyphs = ['▁','▂','▃','▄','▅','▆','▇','█'];
    return glyphs[Math.min(glyphs.length - 1, Math.max(0, Math.ceil((Number(value) / Number(max)) * glyphs.length) - 1))];
  };
  const trend = rows => {
    if (!rows.length) return `<article class="ih-system-panel"><header><span>TREND</span><h2>Usage over time</h2></header><div class="ih-empty-run"><div><b>No trend yet</b><p>Daily telemetry appears here after metered requests run.</p></div></div></article>`;
    const maxRequests = Math.max(...rows.map(row => Number(row.requests || 0)), 1);
    const maxCredits = Math.max(...rows.map(row => Number(row.credits || 0)), 1);
    const requestSpark = rows.map(row => trendGlyph(row.requests, maxRequests)).join('');
    const creditSpark = rows.map(row => trendGlyph(row.credits, maxCredits)).join('');
    const totalSucceeded = rows.reduce((sum,row)=>sum+Number(row.succeeded||0),0);
    const totalRequests = rows.reduce((sum,row)=>sum+Number(row.requests||0),0);
    const reliability = totalRequests ? `${(100*totalSucceeded/totalRequests).toFixed(1)}%` : '—';
    const latest = rows.slice(-7);
    return `<article class="ih-system-panel" aria-labelledby="usage-trend-title"><header><span>TREND</span><h2 id="usage-trend-title">Usage over time</h2></header><div class="ih-inspector-grid"><div><small>Requests</small><b aria-label="Request volume trend">${esc(requestSpark)}</b></div><div><small>Credits</small><b aria-label="Credit burn trend">${esc(creditSpark)}</b></div><div><small>Reliability</small><b>${reliability}</b></div><div><small>Days observed</small><b>${fmt(rows.length)}</b></div></div><div class="ih-run-list" aria-label="Latest daily usage">${latest.map(row=>`<div class="ih-system-row"><span>${statusDot(Number(row.requests||0) ? 'ok' : '')}</span><div><b>${esc(String(row.bucket||'').slice(0,10))}</b><small>${fmt(row.requests||0)} requests · ${fmt(row.credits||0)} credits</small></div><em>${fmt(row.avg_latency_ms||0)} ms</em></div>`).join('')}</div></article>`;
  };

  const metadataRows = metadata => Object.entries(metadata || {}).filter(([,value]) => ['string','number','boolean'].includes(typeof value)).slice(0,12);
  const showRunDetail = async summary => {
    const requestId = summary?.request_id;
    if (!requestId) return openRunInspector(summary || {});
    const previous = new URL(location.href);
    previous.searchParams.set('run', requestId);
    history.replaceState({}, '', `${previous.pathname}${previous.search}${previous.hash}`);
    try {
      const payload = await api(`/api/usage/runs/${encodeURIComponent(requestId)}`);
      const event = payload.run || summary;
      const rows = metadataRows(event.metadata);
      const wrap = modal(`<div class="ih-run-modal">
        <div class="modal-head"><span><span class="overline">RUN DETAIL</span><h2>${esc(runLabel(event))}</h2></span><button data-close aria-label="Close">×</button></div>
        <div class="ih-inspector-status"><span>${statusDot(statusTone(event.status))}<b>${esc(event.status||'unknown')}</b></span><code>${esc(event.request_id)}</code></div>
        <div class="ih-inspector-grid">
          <div><small>Capability</small><b>${esc(event.capability||'—')}</b></div><div><small>Provider</small><b>${esc(event.provider||'—')}</b></div>
          <div><small>Credits</small><b>${fmt(event.credits_charged||0)}</b></div><div><small>Latency</small><b>${event.latency_ms==null?'—':`${fmt(event.latency_ms)} ms`}</b></div>
          <div><small>Input</small><b>${fmt(event.input_bytes||0)} bytes</b></div><div><small>Output</small><b>${fmt(event.output_bytes||0)} bytes</b></div>
          <div><small>Created</small><b>${esc(when(event.created_at))}</b></div><div><small>Credential</small><b>${esc(event.api_key_name ? `${event.api_key_name} · ${event.api_key_prefix||''}…` : 'Session / system')}</b></div>
        </div>
        <div class="ih-inspector-section"><span>EXECUTION REFERENCE</span><div class="ih-code-line"><code>${esc(event.tool_ref||'—')}</code><button class="btn small" data-copy="${esc(event.request_id)}">${icon('copy')} Copy ID</button></div></div>
        ${rows.length ? `<div class="ih-inspector-section"><span>RUN METADATA</span><div class="ih-run-metadata">${rows.map(([key,value])=>`<div><small>${esc(key)}</small><code>${esc(value)}</code></div>`).join('')}</div></div>` : '<div class="ih-inspector-note"><b>No additional execution metadata</b><p>This run is still fully traceable through its request ID, capability, provider, byte counts, latency and credit charge.</p></div>'}
      </div>`, true);
      bindCommon();
      wrap.querySelector('[data-close]')?.addEventListener('click', clearRunDeepLink, {once:true});
      return wrap;
    } catch (error) {
      clearRunDeepLink();
      toast(error?.message || 'Run detail unavailable', 'error');
    }
  };
  const clearRunDeepLink = () => {
    const url = new URL(location.href); url.searchParams.delete('run');
    history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
  };
  const bindRunDetails = events => {
    $$('[data-run-index]').forEach(b=>b.addEventListener('click',()=>showRunDetail(events[Number(b.dataset.runIndex)])));
    const requested = new URL(location.href).searchParams.get('run');
    if (requested && !document.querySelector('.modal-backdrop')) showRunDetail({request_id: requested, tool_ref:'Run'});
  };

  dashOverview = async function dashOverviewIntelligence() {
    const window = usageWindow();
    const data = await api(`/api/usage/intelligence?window=${encodeURIComponent(window)}&recent_limit=8`);
    const t=data.totals||{}, a=data.account||{}, recent=data.recent_runs||[], failures=data.recent_failures||[];
    const credits=Number(a.monthly_credits||0)+Number(a.purchased_credits||0)-Number(a.reserved_credits||0);
    dashboardShell('overview',`
      <section class="ih-command-head"><div><span>COMMAND CENTER</span><h1>Operational intelligence, from real runs.</h1><p>Requests, reliability, latency and credit burn come directly from the metering ledger.</p></div><div class="ih-command-health"><span>${statusDot(t.success_rate==null?'':'ok')} ${t.success_rate==null?'Awaiting telemetry':'Telemetry live'}</span><b>${t.success_rate==null?'—':`${Number(t.success_rate).toFixed(1)}%`}</b><small>${esc(window)} success</small></div></section>
      ${windows(window)}
      <section class="ih-command-stats">${metric('REQUESTS',fmt(t.requests||0),window)}${metric('SUCCESS',t.success_rate==null?'—':`${Number(t.success_rate).toFixed(1)}%`,`${fmt(t.failed||0)} failed`)}${metric('P95 LATENCY',`${fmt(t.p95_latency_ms||0)} ms`,'metered requests')}${metric('CREDITS BURNED',fmt(t.credits||0),`${fmt(credits)} available`)}</section>
      <section class="ih-command-grid"><article class="ih-runs-panel"><header><div><span>RECENT RUNS</span><h2>Execution ledger</h2></div><a data-link href="/dashboard/usage">Open usage ${icon('arrow')}</a></header><div class="ih-run-list">${recent.length ? recent.map((e,i)=>`<button class="ih-run-row" data-run-index="${i}"><span>${statusDot(statusTone(e.status))}</span><div><b>${esc(runLabel(e))}</b><small>${esc(e.provider||'Unattributed')} · ${esc(when(e.created_at))}</small></div><code>${esc((e.request_id||'run').slice(0,16))}</code><em>${e.latency_ms==null?'—':`${fmt(e.latency_ms)} ms`}</em>${icon('arrow')}</button>`).join('') : `<div class="ih-empty-run"><span>${icon('activity')}</span><div><b>No runs in ${esc(window)}</b><p>The dashboard will not invent activity. Choose a wider window or execute a metered request.</p></div></div>`}</div></article>
      <aside class="ih-system-panel"><header><span>FAILURES</span><h2>Needs attention</h2></header>${failures.length ? failures.slice(0,5).map((e,i)=>`<button class="ih-system-row" data-failure-index="${i}"><span>${statusDot('bad')}</span><div><b>${esc(runLabel(e))}</b><small>${esc(e.provider||'Unattributed')} · ${esc(when(e.created_at))}</small></div><em>${esc(e.status||'failed')}</em></button>`).join('') : `<div class="ih-empty-run"><div><b>No failures in this window</b><p>There are no failed metered events to show.</p></div></div>`}</aside></section>`);
    bindWindows(dashOverview); bindRunDetails(recent);
    $$('[data-failure-index]').forEach(b=>b.addEventListener('click',()=>showRunDetail(failures[Number(b.dataset.failureIndex)])));
  };

  dashUsage = async function dashUsageIntelligence() {
    const window=usageWindow();
    const data=await api(`/api/usage/intelligence?window=${encodeURIComponent(window)}&recent_limit=50`);
    const t=data.totals||{}, events=data.recent_runs||[], b=data.breakdowns||{}, series=data.series||[];
    dashboardShell('usage',`
      <section class="ih-runs-head"><div><span>USAGE INTELLIGENCE</span><h1>Metering you can trace.</h1><p>Change the time window, inspect real totals, then drill into the request ledger.</p></div><button class="btn primary" data-new-run-inline>${icon('activity')} New run</button></section>
      ${windows(window)}
      <section class="ih-runs-summary">${metric('REQUESTS',fmt(t.requests||0))}${metric('SUCCESS',t.success_rate==null?'—':`${Number(t.success_rate).toFixed(1)}%`)}${metric('CREDITS',fmt(t.credits||0))}${metric('P95 LATENCY',`${fmt(t.p95_latency_ms||0)} ms`)}</section>
      <section class="ih-command-grid">${trend(series)}${breakdown('By status',b.status||[])}</section>
      <section class="ih-command-grid">${breakdown('By tool',b.tool||[])}${breakdown('By provider',b.provider||[])}</section>
      <section class="ih-run-table-wrap"><div class="ih-run-table-head"><span>STATE</span><span>RUN</span><span>PROVIDER</span><span>CREDITS</span><span>LATENCY</span><span>TIME</span><span></span></div>${runRows(events)}</section>`);
    bindWindows(dashUsage); $('[data-new-run-inline]')?.addEventListener('click',()=>go('/dashboard')); bindRunDetails(events);
  };
})();
