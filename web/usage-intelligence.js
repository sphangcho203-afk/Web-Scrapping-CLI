/* Goal 2: telemetry-backed Overview + Usage surfaces. */
(() => {
  const allowedWindows = ['24h','7d','30d','90d'];
  const usageWindow = () => {
    const value = new URL(location.href).searchParams.get('window') || sessionStorage.getItem('ih_usage_window');
    return allowedWindows.includes(value) ? value : '30d';
  };
  const setUsageWindow = value => {
    sessionStorage.setItem('ih_usage_window', value);
    const url = new URL(location.href); url.searchParams.set('window', value);
    history.replaceState({}, '', url.pathname + url.search + url.hash);
  };
  const statusTone = status => ['ok','accepted'].includes(String(status || '').toLowerCase()) ? 'ok' : 'bad';
  const metric = (label, value, note='') => `<div><span>${esc(label)}</span><b>${value}</b>${note ? `<small>${esc(note)}</small>` : ''}</div>`;
  const windows = active => `<div class="ih-run-hints usage-controls" data-usage-windows><span>Window</span>${allowedWindows.map(w => `<button type="button" data-usage-window="${w}" aria-pressed="${String(w===active)}">${w}</button>`).join('')}<button type="button" data-usage-refresh>Refresh data</button><span data-usage-freshness aria-live="polite"></span></div>`;
  const bindWindows = rerender => $$('[data-usage-window]').forEach(button => button.addEventListener('click', () => { setUsageWindow(button.dataset.usageWindow); rerender(); }));
  const runRows = events => events.length ? events.map((e,i)=>`<button class="ih-run-table-row" data-run-index="${i}"><span>${statusDot(statusTone(e.status))}<b>${esc(e.status||'unknown')}</b></span><span><b>${esc(runLabel(e))}</b><code>${esc((e.request_id||'—').slice(0,22))}</code></span><span data-label="Workflow">${esc(runWorkflow(e))}</span><span data-label="Credits">${fmt(e.credits_charged||0)}</span><span data-label="Latency">${e.latency_ms==null?'—':`${fmt(e.latency_ms)} ms`}</span><span data-label="Time">${esc(when(e.created_at))}</span><span>${icon('arrow')}</span></button>`).join('') : `<div class="ih-empty-run large"><span>${icon('activity')}</span><div><b>No recent request rows</b><p>Nothing is fabricated. Execute a metered request or choose a wider time window.</p></div></div>`;
  const breakdown = (title, rows, total=0) => `<article class="ih-system-panel usage-breakdown"><header><span>REQUEST DISTRIBUTION</span><h2>${esc(title)}</h2></header>${rows.length ? rows.map(row=>`<div class="usage-bar-row"><div><b>${esc(title==='By status'?({ok:'Succeeded',accepted:'Pending',reserved:'Reserved / pending'}[row.name]||row.name):row.name)}</b><span>${fmt(row.requests)} requests · ${fmt(row.credits||0)} credits</span></div><div class="usage-bar-track"><span class="${row.name==='ok'?'success':['accepted','reserved'].includes(row.name)?'pending':title==='By status'?'failure':'neutral'}" style="width:${total?Math.min(100,100*Number(row.requests||0)/total):0}%"></span></div><small>${total?(100*Number(row.requests||0)/total).toFixed(1):'0'}% of requests</small></div>`).join('') : `<div class="ih-empty-run"><div><b>No recorded activity</b><p>Run a metered request or choose a wider window.</p></div></div>`}</article>`;
  // One SVG instance per page; native controls and the exact table own interaction.
  const chartMetrics = {
    requests: {label:'Requests', field:'requests', unit:'requests'},
    credits: {label:'Credit spend', field:'credits', unit:'credits'},
    latency: {label:'Average latency', field:'avg_latency_ms', unit:'ms'},
    success: {label:'Success rate', field:'success_rate', unit:'%'}
  };
  const activeMetric = () => {
    const value=new URL(location.href).searchParams.get('metric');
    return Object.hasOwn(chartMetrics,value) ? value : 'requests';
  };
  const utcDate = value => {
    const date=new Date(value);
    return Number.isFinite(date.getTime()) ? date.toISOString().replace('T',' ').replace('.000Z',' UTC') : 'Unknown time';
  };
  const trend = data => {
    const rows=data.series||[];
    return `<article class="ih-system-panel ih-usage-chart" aria-labelledby="usage-trend-title">
      <header><span>LEDGER HISTORY · UTC</span><h2 id="usage-trend-title">Usage over time</h2><p>Every ${data.range?.granularity==='hour'?'hour':'day'} in the selected window, including quiet periods.</p></header>
      <div class="usage-chart-tabs" role="group" aria-label="Chart metric">${Object.entries(chartMetrics).map(([key,m])=>`<button type="button" data-usage-metric="${key}" aria-pressed="${key===activeMetric()}">${m.label}</button>`).join('')}</div>
      ${rows.length ? `<div class="usage-chart-canvas" data-usage-chart></div>
        <label class="usage-bucket-control">Inspect time bucket<input type="range" min="0" max="${rows.length-1}" value="${rows.length-1}" step="1" aria-label="Inspect time bucket"></label>
        <div class="usage-bucket-detail" data-bucket-detail aria-live="polite"></div>
        <p class="usage-chart-note">${Number(data.totals?.requests||0)?'Tap a point or use the slider to inspect it.':'No requests recorded in this window.'} Edge buckets may cover part of an hour or day. Missing measurements stay blank. Success excludes pending requests.</p>
        <details class="usage-chart-table"><summary>Exact bucket data</summary><div class="usage-table-scroll"><table><thead><tr><th>Bucket start (UTC)</th><th>Requests</th><th>Credits</th><th>Success / failed / pending</th><th>Average latency</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(utcDate(r.bucket_start||r.bucket))}${r.partial?' · partial':''}</td><td>${fmt(r.requests||0)}</td><td>${fmt(r.credits||0)}</td><td>${fmt(r.succeeded||0)} / ${fmt(r.failed||0)} / ${fmt(r.pending||0)}</td><td>${r.avg_latency_ms==null?'—':fmt(r.avg_latency_ms)+' ms'}</td></tr>`).join('')}</tbody></table></div></details>
        <button class="btn small" type="button" data-usage-export>Export chart CSV</button>` : `<div class="ih-empty-run"><div><b>No trend data available</b><p>Choose a wider window or run a metered request.</p></div></div>`}
    </article>`;
  };
  let chartCleanup=()=>{};
  const bindTrend = data => {
    chartCleanup();
    const host=$('[data-usage-chart]'), rows=data.series||[];
    if(!host||!rows.length)return;
    const panel=host.closest('.ih-usage-chart'), slider=panel.querySelector('input[type=range]');
    let metric=activeMetric(), selected=rows.length-1;
    const finite=value=>value!=null&&Number.isFinite(Number(value));
    const tick=value=>Intl.NumberFormat('en',{notation:value>=10000?'compact':'standard',maximumFractionDigits:2}).format(value);
    const detail=()=>{
      const row=rows[selected];slider.value=String(selected);
      panel.querySelector('[data-bucket-detail]').innerHTML=`<b>${esc(utcDate(row.bucket_start||row.bucket))}${row.partial?' · partial bucket':''}</b><small>Until ${esc(utcDate(row.bucket_end||row.bucket))}</small><div><span>${fmt(row.requests||0)} requests</span><span>${fmt(row.credits||0)} credits</span><span>${fmt(row.succeeded||0)} successful · ${fmt(row.failed||0)} failed · ${fmt(row.pending||0)} pending</span><span>${row.avg_latency_ms==null?'No latency measurement':fmt(row.avg_latency_ms)+' ms average latency'}</span><span>${row.success_rate==null?'No completed requests':Number(row.success_rate).toFixed(1)+'% success'}</span></div>`;
    };
    const draw=()=>{
      if(!host.isConnected)return;
      const width=Math.max(180,Math.floor(host.clientWidth)), height=250, left=48,right=18,top=20,bottom=40;
      const plotWidth=width-left-right, plotHeight=height-top-bottom, m=chartMetrics[metric];
      const values=rows.map(r=>finite(r[m.field])?Number(r[m.field]):null);
      const max=Math.max(0,...values.filter(v=>v!=null)), rough=Math.max(1,max)/4;
      const power=Math.pow(10,Math.floor(Math.log10(rough))), step=[1,2,5,10].find(v=>v*power>=rough)*power;
      const unitStep=(metric==='requests'||metric==='credits')?Math.max(1,Math.ceil(step)):step;
      const domain=metric==='success'?100:Math.max(unitStep*4,Math.ceil(max/(unitStep*4))*unitStep*4);
      const x=i=>left+(i+.5)*plotWidth/rows.length, y=v=>top+plotHeight*(1-v/domain);
      const axis=Array.from({length:5},(_,i)=>{const value=domain*i/4, yy=y(value);return `<line x1="${left}" x2="${width-right}" y1="${yy}" y2="${yy}" class="usage-grid"/><text x="${left-8}" y="${yy+4}" text-anchor="end">${esc(tick(value))}</text>`;}).join('');
      const count=width<480?3:6;
      const indexes=[...new Set(Array.from({length:Math.min(count,rows.length)},(_,i)=>Math.round(i*(rows.length-1)/Math.max(1,Math.min(count,rows.length)-1))))];
      const labels=indexes.map(i=>{const date=new Date(rows[i].bucket);const text=Number.isFinite(date.getTime())?Intl.DateTimeFormat('en',{timeZone:'UTC',month:'short',day:'numeric',...(data.range?.granularity==='hour'?{hour:'2-digit',hour12:false}:{})}).format(date):String(rows[i].bucket);return `<text x="${x(i)}" y="${height-14}" text-anchor="${i===0?'start':i===rows.length-1?'end':'middle'}">${esc(text)}</text>`;}).join('');
      let marks='';
      if(metric==='requests'||metric==='credits'){
        const barWidth=Math.max(1,plotWidth/rows.length*.7);
        marks=values.map((v,i)=>v==null?'':`<rect data-value="${v}" x="${x(i)-barWidth/2}" y="${y(v)}" width="${barWidth}" height="${Math.max(0,y(0)-y(v))}" rx="2" class="usage-mark"/>`).join('');
      }else{
        let path='',connected=false;
        values.forEach((v,i)=>{if(v==null){connected=false;return;}path+=(connected?' L':' M')+x(i)+' '+y(v);connected=true;});
        marks=`<path d="${path.trim()}" class="usage-data-line"/>`+values.map((v,i)=>v==null?'':`<circle data-value="${v}" cx="${x(i)}" cy="${y(v)}" r="3" class="usage-mark"/>`).join('');
      }
      host.dataset.metric=metric;
      host.innerHTML=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(m.label)} over time in UTC; exact values in the table below" data-domain-max="${domain}"><title>${esc(m.label)} · ${esc(data.window||usageWindow())}</title>${axis}${marks}${values.every(v=>v==null)?`<text x="${left+plotWidth/2}" y="${top+plotHeight/2}" text-anchor="middle">No measurements in this window</text>`:''}<line x1="${x(selected)}" x2="${x(selected)}" y1="${top}" y2="${height-bottom}" class="usage-selection"/>${labels}<text x="${left}" y="12">${esc(m.unit)}</text></svg>`;
      const inspect=event=>{
        const rect=host.getBoundingClientRect();
        const index=Math.max(0,Math.min(rows.length-1,Math.floor((event.clientX-rect.left-left)/plotWidth*rows.length)));
        if(index!==selected){selected=index;detail();const line=host.querySelector('.usage-selection');line.setAttribute('x1',x(index));line.setAttribute('x2',x(index));}
      };
      host.onpointermove=event=>{if(event.pointerType==='mouse')inspect(event);};host.onclick=inspect;
    };
    slider.oninput=()=>{selected=Number(slider.value);detail();draw();};
    panel.querySelectorAll('[data-usage-metric]').forEach(button=>button.onclick=()=>{
      metric=button.dataset.usageMetric;const url=new URL(location.href);url.searchParams.set('metric',metric);history.replaceState({},'',url.pathname+url.search+url.hash);
      panel.querySelectorAll('[data-usage-metric]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));draw();
    });
    panel.querySelector('[data-usage-export]').onclick=()=>{
      const fields=['bucket_start','bucket_end','requests','credits','succeeded','failed','pending','avg_latency_ms','success_rate','partial'];
      const csv=fields.join(',')+'\n'+rows.map(row=>fields.map(field=>JSON.stringify(String(row[field]??(field==='bucket_start'?row.bucket:'')))).join(',')).join('\n');
      const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})), link=document.createElement('a');link.href=url;link.download='opencrawl-usage-'+usageWindow()+'.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
    const observer=new ResizeObserver(()=>{if(host.isConnected)draw();else observer.disconnect();});observer.observe(host);
    chartCleanup=()=>observer.disconnect();detail();draw();
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
      let receipt = null;
      try { receipt = await api(`/api/runs/${encodeURIComponent(requestId)}`); } catch (_) { /* Older deployments still expose the usage inspector. */ }
      const canonical = receipt?.run;
      const timeline = receipt?.events || [];
      const rows = metadataRows(event.metadata);
      const wrap = modal(`<div class="ih-run-modal">
        <div class="modal-head"><span><span class="overline">RUN DETAIL</span><h2>${esc(runLabel(event))}</h2></span><button data-close aria-label="Close">×</button></div>
        <div class="ih-inspector-status"><span>${statusDot(statusTone(event.status))}<b>${esc(event.status||'unknown')}</b></span><code>${esc(event.request_id)}</code></div>
        <div class="ih-inspector-grid">
          <div><small>Workflow</small><b>${esc(runWorkflow(event))}</b></div><div><small>Operation</small><b>${esc(runLabel(event))}</b></div>
          <div><small>Credits</small><b>${fmt(event.credits_charged||0)}</b></div><div><small>Latency</small><b>${event.latency_ms==null?'—':`${fmt(event.latency_ms)} ms`}</b></div>
          <div><small>Input</small><b>${fmt(event.input_bytes||0)} bytes</b></div><div><small>Output</small><b>${fmt(event.output_bytes||0)} bytes</b></div>
          <div><small>Created</small><b>${esc(when(event.created_at))}</b></div><div><small>Credential</small><b>${esc(event.api_key_name ? `${event.api_key_name} · ${event.api_key_prefix||''}…` : 'Session / system')}</b></div>
        </div>
        <div class="ih-inspector-section"><span>REQUEST REFERENCE</span><div class="ih-code-line"><code>${esc(event.request_id||'—')}</code><button class="btn small" data-copy="${esc(event.request_id)}">${icon('copy')} Copy ID</button></div></div>
        <div class="ih-inspector-section" data-run-receipt><span>CANONICAL RECEIPT</span>${canonical ? `<div class="ih-inspector-grid"><div><small>Reserved credits</small><b>${fmt(canonical.credits_reserved)}</b></div><div><small>Charged credits</small><b>${fmt(canonical.credits_charged)}</b></div><div><small>Execution state</small><b>${esc(canonical.execution?.status || 'No specialized job')}</b></div><div><small>Attempts</small><b>${canonical.execution?.attempts == null ? 'Not recorded' : fmt(canonical.execution.attempts)}</b></div></div>${canonical.execution?.cancel_requested ? '<p>Cancellation requested; the worker has not yet confirmed completion.</p>' : ''}${canonical.output_dataset_id ? `<a class="btn small" data-link href="/dashboard/datasets?dataset=${encodeURIComponent(canonical.output_dataset_id)}">Open saved dataset</a>` : '<p>No saved dataset linked.</p>'}<h3>Recorded run transitions</h3>${timeline.length ? `<ol>${timeline.map(item => `<li><b>${esc(item.status)}</b> · ${esc(when(item.timestamp))} · ${esc(item.type)}</li>`).join('')}</ol>` : '<p>Historical receipt: no recorded timeline events.</p>'}` : '<p>Canonical receipt unavailable. Existing usage details remain available.</p>'}</div>
        <details class="ih-run-diagnostics"><summary>Technical routing and provenance</summary><div><span>Execution reference</span><code>${esc(event.tool_ref||'—')}</code><span>Adapter</span><code>${esc(event.provider||'—')}</code>${event.capability?`<span>Capability ID</span><code>${esc(event.capability)}</code>`:''}</div>${rows.length?`<section><h3>RUN METADATA</h3><div class="ih-run-metadata">${rows.map(([key,value])=>`<div><small>${esc(key)}</small><code>${esc(value)}</code></div>`).join('')}</div></section>`:''}</details>
      </div>`, true);
      bindCommon();
      wrap.onClose=clearRunDeepLink;
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

  let loadGeneration=0;
  const loadUsage = async (recentLimit) => {
    const generation=++loadGeneration, path=location.pathname;
    const freshness=$('[data-usage-freshness]');
    if(freshness)freshness.textContent='Updating…';
    try{
      const data=await api(`/api/usage/intelligence?window=${encodeURIComponent(usageWindow())}&recent_limit=${recentLimit}`);
      return generation===loadGeneration&&location.pathname===path?data:null;
    }catch(error){
      if(generation!==loadGeneration||location.pathname!==path)return null;
      if(freshness){freshness.textContent='Update failed · showing previous snapshot';toast(error?.message||'Usage update failed','error');}
      else{dashboardShell(path.endsWith('/usage')?'usage':'overview','<section class="card"><h1>Usage data is unavailable</h1><p>Your ledger could not be loaded. Try again.</p><button class="btn" data-usage-retry>Retry usage</button></section>');$('[data-usage-retry]').onclick=()=>path.endsWith('/usage')?dashUsage():dashOverview();}
      return null;
    }
  };
  const bindUsage = (data, rerender) => {
    bindWindows(rerender);bindTrend(data);
    $('[data-usage-refresh]').onclick=rerender;
    $('[data-usage-freshness]').textContent=data.generated_at?'Updated '+utcDate(data.generated_at):'Snapshot time unavailable';
  };

  dashOverview = async function dashOverviewIntelligence() {
    const window = usageWindow();
    const data = await loadUsage(8); if(!data)return;
    const t=data.totals||{}, a=data.account||{}, recent=data.recent_runs||[], failures=data.recent_failures||[];
    const credits=Number(a.monthly_credits||0)+Number(a.purchased_credits||0)-Number(a.reserved_credits||0);
    dashboardShell('overview',`
      <section class="ih-command-head"><div><span>COMMAND CENTER</span><h1>Operational intelligence, from real runs.</h1><p>Requests, reliability, latency and credit burn come directly from the metering ledger.</p></div><div class="ih-command-health"><span>${statusDot(t.success_rate==null?'':'ok')} ${t.success_rate==null?'Awaiting telemetry':'Telemetry live'}</span><b>${t.success_rate==null?'—':`${Number(t.success_rate).toFixed(1)}%`}</b><small>${esc(window)} success</small></div></section>
      ${windows(window)}
      <section class="ih-command-stats">${metric('REQUESTS',fmt(t.requests||0),window)}${metric('SUCCESS',t.success_rate==null?'—':`${Number(t.success_rate).toFixed(1)}%`,`${fmt(t.failed||0)} failed · ${fmt(t.pending||0)} pending`)}${metric('P95 LATENCY',t.p95_latency_ms==null?'—':`${fmt(t.p95_latency_ms)} ms`,'measured requests')}${metric('CREDITS BURNED',fmt(t.credits||0),`${fmt(credits)} available`)}</section>
      <section class="usage-overview-trend">${trend(data)}</section>
      <section class="ih-command-grid"><article class="ih-runs-panel"><header><div><span>RECENT RUNS</span><h2>Execution ledger</h2></div><a data-link href="/dashboard/usage">Open usage ${icon('arrow')}</a></header><div class="ih-run-list">${recent.length ? recent.map((e,i)=>`<button class="ih-run-row" data-run-index="${i}"><span>${statusDot(statusTone(e.status))}</span><div><b>${esc(runLabel(e))}</b><small>${esc(runWorkflow(e))} · ${esc(when(e.created_at))}</small></div><code>${esc((e.request_id||'run').slice(0,16))}</code><em>${e.latency_ms==null?'—':`${fmt(e.latency_ms)} ms`}</em>${icon('arrow')}</button>`).join('') : `<div class="ih-empty-run"><span>${icon('activity')}</span><div><b>No runs in ${esc(window)}</b><p>The dashboard will not invent activity. Choose a wider window or execute a metered request.</p></div></div>`}</div></article>
      <aside class="ih-system-panel"><header><span>FAILURES</span><h2>Needs attention</h2></header>${failures.length ? failures.slice(0,5).map((e,i)=>`<button class="ih-system-row" data-failure-index="${i}"><span>${statusDot('bad')}</span><div><b>${esc(runLabel(e))}</b><small>${esc(runWorkflow(e))} · ${esc(when(e.created_at))}</small></div><em>${esc(e.status||'failed')}</em></button>`).join('') : `<div class="ih-empty-run"><div><b>No failures in this window</b><p>There are no failed metered events to show.</p></div></div>`}</aside></section>`);
    bindUsage(data,dashOverview); bindRunDetails(recent);
    $$('[data-failure-index]').forEach(b=>b.addEventListener('click',()=>showRunDetail(failures[Number(b.dataset.failureIndex)])));
  };

  dashUsage = async function dashUsageIntelligence() {
    const window=usageWindow();
    const data=await loadUsage(50); if(!data)return;
    const t=data.totals||{}, events=data.recent_runs||[], b=data.breakdowns||{};
    dashboardShell('usage',`
      <section class="ih-runs-head"><div><span>USAGE INTELLIGENCE</span><h1>Metering you can trace.</h1><p>Change the time window, inspect real totals, then drill into the request ledger.</p></div><button class="btn primary" data-new-run-inline>${icon('activity')} New run</button></section>
      ${windows(window)}
      <section class="ih-runs-summary">${metric('REQUESTS',fmt(t.requests||0))}${metric('SUCCESS',t.success_rate==null?'—':`${Number(t.success_rate).toFixed(1)}%`,`${fmt(t.pending||0)} pending excluded`)}${metric('CREDITS',fmt(t.credits||0))}${metric('P95 LATENCY',t.p95_latency_ms==null?'—':`${fmt(t.p95_latency_ms)} ms`)}</section>
      <section class="ih-command-grid usage-charts-grid">${trend(data)}${breakdown('By status',b.status||[],t.requests)}</section>
      <section class="usage-operations">${breakdown('Top operations by request volume',(b.tool||[]).map(row=>({...row,name:row.is_remainder?'Other operations':runLabel({tool_ref:row.name})})),t.requests)}</section>
      <p class="usage-chart-note">Charts cover the full window. The ledger below shows the latest ${fmt(events.length)} requests.</p>
      <section class="ih-run-table-wrap"><div class="ih-run-table-head"><span>STATE</span><span>RUN</span><span>WORKFLOW</span><span>CREDITS</span><span>LATENCY</span><span>TIME</span><span></span></div>${runRows(events)}</section>`);
    bindUsage(data,dashUsage); $('[data-new-run-inline]')?.addEventListener('click',()=>go('/dashboard/playground')); bindRunDetails(events);
  };
})();
