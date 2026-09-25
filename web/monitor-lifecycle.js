/* Goal 3 monitor lifecycle workspace. Composed into the canonical app.js response. */
(() => {
  const monitorState = { selected: null, history: new Map() };
  const isHealthy = status => status === 'healthy' || status === 'ok';
  const statusTone = status => isHealthy(status) ? 'success' : status ? 'warning' : 'neutral';
  const schedule = minutes => minutes < 60 ? `${minutes} min` : minutes === 60 ? '1 hour' : minutes % 1440 === 0 ? `${minutes / 1440} day` : `${minutes / 60} hours`;

  async function preflight(body, signal) {
    return api('/api/monitors/validate', { method:'POST', body, signal });
  }

  function monitorForm(monitor = null, template = '') {
    const type = monitor?.type || template || 'web';
    const types = monitor?.type === 'gaming' ? ['web','api','mcp','gaming'] : ['web','api','mcp'];
    const targetHint = {
      web: ['https://example.com', 'Public page to check over HTTP'],
      api: ['https://api.example.com/health', 'Public API health endpoint'],
      mcp: ['https://example.com/mcp', 'Public MCP endpoint to check over HTTP'],
      gaming: ['provider-specific identity', 'Legacy gaming monitors cannot run on the current HTTP executor. Switch to an HTTP type to resume checks.']
    };
    const wrap = modal(`<div class="modal-head"><span><span class="overline">${monitor ? 'EDIT MONITOR' : 'MONITOR PREFLIGHT'}</span><h2>${monitor ? esc(monitor.name) : 'Create monitor'}</h2></span><button data-close aria-label="Close">×</button></div>
      <form id="monitor-lifecycle-form" class="form-stack">
        <label>Name<input required name="name" maxlength="120" value="${esc(monitor?.name || '')}" placeholder="Production health"></label>
        <div class="field-pair"><label>Type<select name="type">${types.map(x => `<option value="${x}" ${x===type?'selected':''}>${x.toUpperCase()}</option>`).join('')}</select></label><label>Interval<select name="interval_minutes">${[15,60,360,1440].map(x => `<option value="${x}" ${Number(monitor?.interval_minutes || 60)===x?'selected':''}>${schedule(x)}</option>`).join('')}</select></label></div>
        <label>Target<input required name="target" type="${type === 'gaming' ? 'text' : 'url'}" maxlength="2000" value="${esc(monitor?.target || '')}" placeholder="${targetHint[type]?.[0] || targetHint.web[0]}" aria-describedby="monitor-target-hint"><small id="monitor-target-hint">${targetHint[type]?.[1] || targetHint.web[1]}</small></label>
        <div id="monitor-preflight-state" class="notice" role="status" aria-live="polite">Target and schedule are validated before anything is saved.</div>
        <button class="btn primary large" type="submit">${monitor ? 'Validate and save' : 'Validate and create'}</button>
      </form>`);
    const form = $('#monitor-lifecycle-form', wrap), target = form.elements.target;
    form.elements.type.onchange = e => {
      const selected = e.currentTarget.value, hint = targetHint[selected] || targetHint.web;
      target.type = selected === 'gaming' ? 'text' : 'url';
      target.placeholder = hint[0];
      $('#monitor-target-hint', wrap).textContent = hint[1];
      target.setCustomValidity('');
    };
    $('#monitor-lifecycle-form', wrap).onsubmit = async e => {
      e.preventDefault();
      const button = $('button[type=submit]', e.currentTarget);
      const body = Object.fromEntries(new FormData(e.currentTarget));
      body.interval_minutes = Number(body.interval_minutes);
      if (!busy(button, true, 'Validating…')) return;
      const controller = new AbortController();
      wrap.onClose = () => controller.abort();
      try {
        const checked = await preflight(body, controller.signal);
        if (!wrap.isConnected) return;
        $('#monitor-preflight-state', wrap).className = 'notice success';
        $('#monitor-preflight-state', wrap).textContent = 'Preflight passed. Saving monitor…';
        const saved = await api(monitor ? `/api/monitors/${monitor.id}` : '/api/monitors', { method:monitor ? 'PATCH' : 'POST', body:checked.monitor });
        wrap.remove();
        monitorState.selected = saved.id;
        toast(monitor ? 'Monitor updated' : 'Monitor created', 'success');
        if (location.pathname === '/dashboard/monitors') dashMonitors();
      } catch (error) {
        if (!wrap.isConnected) return;
        $('#monitor-preflight-state', wrap).className = 'notice warning';
        $('#monitor-preflight-state', wrap).textContent = error.message;
        busy(button, false);
      }
    };
  }

  async function openMonitor(id, trigger) {
    monitorState.selected = id;
    if (trigger?.disabled) return;
    if (trigger) { trigger.disabled = true; trigger.setAttribute('aria-busy','true'); }
    let monitor, page;
    try {
      [monitor, page] = await Promise.all([
        api(`/api/monitors/${encodeURIComponent(id)}`),
        api(`/api/monitors/${encodeURIComponent(id)}/history?limit=25`)
      ]);
    } finally {
      if (trigger?.isConnected) { trigger.disabled = false; trigger.removeAttribute('aria-busy'); }
    }
    if (location.pathname !== '/dashboard/monitors' || !trigger?.isConnected) return;
    monitorState.history.set(id, page);
    const runs = page.runs || [];
    const wrap = modal(`<div class="modal-head"><span><span class="overline">MONITOR DETAIL</span><h2>${esc(monitor.name)}</h2></span><button data-close aria-label="Close">×</button></div>
      <div class="ih-inspector-status"><span class="badge ${statusTone(monitor.last_status)}">${esc(monitor.last_status || 'Not run')}</span><code>${esc(monitor.id)}</code></div>
      <div class="ih-inspector-grid"><div><small>Target</small><b>${esc(monitor.target)}</b></div><div><small>Schedule</small><b>${esc(schedule(Number(monitor.interval_minutes)))}</b></div><div><small>Last check</small><b>${esc(when(monitor.last_checked_at))}</b></div><div><small>Next check</small><b>${monitor.enabled ? esc(when(monitor.next_check_at)) : 'Paused'}</b></div></div>
      <div class="ih-inspector-section"><span>LIFECYCLE</span><div class="ih-preflight-actions"><button class="btn" id="monitor-edit">Edit</button><button class="btn" id="monitor-toggle">${monitor.enabled ? 'Pause' : 'Resume'}</button></div></div>
      <div class="ih-inspector-section"><span>CHECK HISTORY</span><div id="monitor-history">${historyMarkup(runs)}</div>${page.has_more ? '<button class="btn small" id="monitor-history-more">Load older checks</button>' : ''}</div>
      ${!runs.length ? '<div class="notice">No persisted checks yet. The lifecycle is configured, but execution history will remain empty until the scheduler/executor records a run.</div>' : ''}`, true);
    $('#monitor-edit', wrap).onclick = () => { wrap.remove(); monitorForm(monitor); };
    $('#monitor-toggle', wrap).onclick = async e => {
      const button=e.currentTarget;
      busy(button,true,'Updating…');
      try {
        await api(`/api/monitors/${monitor.id}/toggle`, { method:'POST', body:{enabled:!monitor.enabled} });
        wrap.remove(); toast(monitor.enabled ? 'Monitor paused' : 'Monitor resumed', 'success'); dashMonitors();
      } catch(error) { busy(button,false); toast(error.message,'error'); }
    };
    $('#monitor-history-more', wrap)?.addEventListener('click', async e => {
      const button = e.currentTarget;
      const current = monitorState.history.get(id);
      if (!current?.next_before) return;
      if (!busy(button, true, 'Loading…')) return;
      try {
        const next = await api(`/api/monitors/${encodeURIComponent(id)}/history?limit=25&before=${encodeURIComponent(current.next_before)}`);
        const combined = { runs:[...(current.runs||[]), ...(next.runs||[])], has_more:next.has_more, next_before:next.next_before };
        monitorState.history.set(id, combined);
        $('#monitor-history', wrap).innerHTML = historyMarkup(combined.runs);
        if (!combined.has_more) button.remove(); else busy(button, false);
      } catch(error) { busy(button, false); toast(error.message,'error'); }
    });
  }

  function historyMarkup(runs) {
    if (!runs.length) return '<div class="smart-empty compact"><span><b>No checks recorded</b><p>Persisted monitor executions will appear here.</p></span></div>';
    return `<div class="table-wrap monitor-history-table"><table><thead><tr><th>Time</th><th>Status</th><th>HTTP</th><th>Latency</th><th>Summary</th></tr></thead><tbody>${runs.map(run => `<tr><td data-label="Time">${esc(when(run.created_at))}</td><td data-label="Status"><span class="badge ${statusTone(run.status)}">${esc(run.status)}</span></td><td data-label="HTTP">${run.http_status ?? '—'}</td><td data-label="Latency">${run.latency_ms == null ? '—' : `${fmt(run.latency_ms)} ms`}</td><td data-label="Summary">${esc(run.summary || '—')}</td></tr>`).join('')}</tbody></table></div>`;
  }

  dashMonitors = async function dashMonitorLifecycle() {
    const d = await api('/api/monitors'), items = d.monitors || [];
    const enabled = items.filter(x => x.enabled).length;
    const healthy = items.filter(x => isHealthy(x.last_status)).length;
    const failed = items.filter(x => x.last_status && !isHealthy(x.last_status)).length;
    dashboardShell('monitors', `${pageHead('OBSERVE','Monitors','Create, validate, schedule and inspect persistent checks.','<button class="btn primary" id="new-monitor">New monitor</button>')}
      <section class="stats-grid">${stat('Active',fmt(enabled),`${fmt(items.length)} configured`)}${stat('Healthy',fmt(healthy),'Latest persisted check')}${stat('Needs attention',fmt(failed),'Latest non-OK check')}${stat('Awaiting first run',fmt(items.filter(x=>!x.last_checked_at).length),'No fabricated health')}</section>
      <div class="template-row">${[['Web page','web'],['API endpoint','api'],['MCP endpoint','mcp']].map(x=>`<button data-monitor-template="${x[1]}">${icon('monitor')}<b>${x[0]}</b><small>Validate → schedule → history</small></button>`).join('')}</div>
      <article class="card">${items.length ? `<div class="monitor-list">${items.map(x=>`<button class="monitor-row" data-monitor-id="${esc(x.id)}"><i class="monitor-state ${isHealthy(x.last_status)?'ok':''}"></i><span><b>${esc(x.name)}</b><small>${esc(x.type)} · ${esc(x.target)}</small></span><span><small>Last / next</small><b>${esc(when(x.last_checked_at))}</b><small>${x.enabled ? esc(when(x.next_check_at)) : 'Paused'}</small></span><span class="badge ${statusTone(x.last_status)}">${esc(x.last_status || 'Not run')}</span>${icon('arrow')}</button>`).join('')}</div>` : `<div class="smart-empty">${icon('monitor')}<span><b>Nothing is watching yet</b><p>Create a validated monitor. Health remains unknown until a real check is recorded.</p></span><button class="btn primary" id="empty-monitor">Create monitor</button></div>`}</article>`);
    $('#new-monitor')?.addEventListener('click',()=>monitorForm());
    $('#empty-monitor')?.addEventListener('click',()=>monitorForm());
    $$('[data-monitor-template]').forEach(b=>b.addEventListener('click',()=>monitorForm(null,b.dataset.monitorTemplate)));
    $$('[data-monitor-id]').forEach(b=>b.addEventListener('click',()=>openMonitor(b.dataset.monitorId,b).catch(error=>toast(error.message,'error'))));
  };
})();
