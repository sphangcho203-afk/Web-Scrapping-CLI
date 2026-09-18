/* Goal 2: telemetry-backed Overview + Usage surfaces.
 * Kept as a bounded feature module so the canonical app runtime can consume the
 * new read model without duplicating metering calculations in the browser.
 */
(() => {
  const usageWindow = () => sessionStorage.getItem('ih_usage_window') || '30d';
  const setUsageWindow = value => sessionStorage.setItem('ih_usage_window', value);
  const statusTone = status => ['ok','accepted'].includes(String(status || '').toLowerCase()) ? 'ok' : 'bad';
  const metric = (label, value, note='') => `<div><span>${esc(label)}</span><b>${value}</b>${note ? `<small>${esc(note)}</small>` : ''}</div>`;
  const windows = active => `<div class="ih-run-hints" data-usage-windows><span>Window</span>${['24h','7d','30d','90d'].map(w => `<button type="button" data-usage-window="${w}" aria-pressed="${String(w===active)}">${w}</button>`).join('')}</div>`;
  const bindWindows = rerender => $$('[data-usage-window]').forEach(button => button.addEventListener('click', () => {
    setUsageWindow(button.dataset.usageWindow);
    rerender();
  }));
  const runRows = events => events.length ? events.map((e,i)=>`<button class="ih-run-table-row" data-run-index="${i}"><span>${statusDot(statusTone(e.status))}<b>${esc(e.status||'unknown')}</b></span><span><b>${esc(runLabel(e))}</b><code>${esc((e.request_id||'—').slice(0,22))}</code></span><span>${esc(e.provider||'—')}</span><span>${fmt(e.credits_charged||0)}</span><span>${e.latency_ms==null?'—':`${fmt(e.latency_ms)} ms`}</span><span>${esc(when(e.created_at))}</span><span>${icon('arrow')}</span></button>`).join('') : `<div class="ih-empty-run large"><span>${icon('activity')}</span><div><b>No telemetry in this window</b><p>Nothing is fabricated. Execute a metered request or choose a wider time window.</p></div></div>`;
  const breakdown = (title, rows) => `<article class="ih-system-panel"><header><span>BREAKDOWN</span><h2>${esc(title)}</h2></header>${rows.length ? rows.map(row=>`<div class="ih-system-row"><span>${statusDot()}</span><div><b>${esc(row.name)}</b><small>${fmt(row.requests)} requests · ${fmt(row.credits)} credits</small></div><em>${fmt(row.avg_latency_ms)} ms</em></div>`).join('') : `<div class="ih-empty-run"><div><b>Unavailable</b><p>No metered events in this window.</p></div></div>`}</article>`;

  dashOverview = async function dashOverviewIntelligence() {
    const window = usageWindow();
    const data = await api(`/api/usage/intelligence?window=${encodeURIComponent(window)}&recent_limit=8`);
    const t=data.totals||{}, a=data.account||{}, recent=data.recent_runs||[], failures=data.recent_failures||[];
    const credits=Number(a.monthly_credits||0)+Number(a.purchased_credits||0);
    dashboardShell('overview',`
      <section class="ih-command-head"><div><span>COMMAND CENTER</span><h1>Operational intelligence, from real runs.</h1><p>Requests, reliability, latency and credit burn come directly from the metering ledger.</p></div><div class="ih-command-health"><span>${statusDot(t.success_rate==null?'':'ok')} ${t.success_rate==null?'Awaiting telemetry':'Telemetry live'}</span><b>${t.success_rate==null?'—':`${Number(t.success_rate).toFixed(1)}%`}</b><small>${esc(window)} success</small></div></section>
      ${windows(window)}
      <section class="ih-command-stats">${metric('REQUESTS',fmt(t.requests||0),window)}${metric('SUCCESS',t.success_rate==null?'—':`${Number(t.success_rate).toFixed(1)}%`,`${fmt(t.failed||0)} failed`)}${metric('P95 LATENCY',`${fmt(t.p95_latency_ms||0)} ms`,'metered requests')}${metric('CREDITS BURNED',fmt(t.credits||0),`${fmt(credits)} available`)}</section>
      <section class="ih-command-grid"><article class="ih-runs-panel"><header><div><span>RECENT RUNS</span><h2>Execution ledger</h2></div><a data-link href="/dashboard/usage">Open usage ${icon('arrow')}</a></header><div class="ih-run-list">${recent.length ? recent.map((e,i)=>`<button class="ih-run-row" data-run-index="${i}"><span>${statusDot(statusTone(e.status))}</span><div><b>${esc(runLabel(e))}</b><small>${esc(e.provider||'Unattributed')} · ${esc(when(e.created_at))}</small></div><code>${esc((e.request_id||'run').slice(0,16))}</code><em>${e.latency_ms==null?'—':`${fmt(e.latency_ms)} ms`}</em>${icon('arrow')}</button>`).join('') : `<div class="ih-empty-run"><span>${icon('activity')}</span><div><b>No runs in ${esc(window)}</b><p>The dashboard will not invent activity. Choose a wider window or execute a metered request.</p></div></div>`}</div></article>
      <aside class="ih-system-panel"><header><span>FAILURES</span><h2>Needs attention</h2></header>${failures.length ? failures.slice(0,5).map(e=>`<div class="ih-system-row"><span>${statusDot('bad')}</span><div><b>${esc(runLabel(e))}</b><small>${esc(e.provider||'Unattributed')} · ${esc(when(e.created_at))}</small></div><em>${esc(e.status||'failed')}</em></div>`).join('') : `<div class="ih-empty-run"><div><b>No failures in this window</b><p>There are no failed metered events to show.</p></div></div>`}</aside></section>`);
    bindWindows(dashOverview);
    $$('[data-run-index]').forEach(b=>b.addEventListener('click',()=>openRunInspector(recent[Number(b.dataset.runIndex)])));
  };

  dashUsage = async function dashUsageIntelligence() {
    const window=usageWindow();
    const data=await api(`/api/usage/intelligence?window=${encodeURIComponent(window)}&recent_limit=50`);
    const t=data.totals||{}, events=data.recent_runs||[], b=data.breakdowns||{};
    dashboardShell('usage',`
      <section class="ih-runs-head"><div><span>USAGE INTELLIGENCE</span><h1>Metering you can trace.</h1><p>Change the time window, inspect real totals, then drill into the request ledger.</p></div><button class="btn primary" data-new-run-inline>${icon('activity')} New run</button></section>
      ${windows(window)}
      <section class="ih-runs-summary">${metric('REQUESTS',fmt(t.requests||0))}${metric('SUCCESS',t.success_rate==null?'—':`${Number(t.success_rate).toFixed(1)}%`)}${metric('CREDITS',fmt(t.credits||0))}${metric('P95 LATENCY',`${fmt(t.p95_latency_ms||0)} ms`)}</section>
      <section class="ih-command-grid">${breakdown('By tool',b.tool||[])}${breakdown('By provider',b.provider||[])}</section>
      <section class="ih-run-table-wrap"><div class="ih-run-table-head"><span>STATE</span><span>RUN</span><span>PROVIDER</span><span>CREDITS</span><span>LATENCY</span><span>TIME</span><span></span></div>${runRows(events)}</section>`);
    bindWindows(dashUsage);
    $('[data-new-run-inline]')?.addEventListener('click',()=>go('/dashboard'));
    $$('[data-run-index]').forEach(b=>b.addEventListener('click',()=>openRunInspector(events[Number(b.dataset.runIndex)])));
  };
})();
