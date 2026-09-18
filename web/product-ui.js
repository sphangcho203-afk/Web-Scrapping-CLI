/* Internet Hands product UI layer.
 * Keeps the existing control-plane/auth/billing implementation intact while
 * replacing the public product story and the primary dashboard experience.
 */
(() => {
  const providerBadge = (mark, brand, detail) => `
    <div class="ih-provider">
      <span class="ih-provider-mark">${platformMark(mark, brand)}</span>
      <span><b>${esc(brand)}</b><small>${esc(detail)}</small></span>
    </div>`;

  const statusDot = (tone = 'ok') => `<i class="ih-status-dot ${tone}"></i>`;

  brand = function brandV2() {
    return `<a class="brand ih-brand ih-logo-only" data-link href="/" aria-label="Internet Hands home">
      <img class="ih-brand-art" src="/assets/internet-hands-logo.webp" alt="Internet Hands">
    </a>`;
  };

  publicShell = function publicShellV2(content) {
    const authenticated = !!state.me?.user?.email_verified;
    const primary = authenticated
      ? `<a class="btn primary ih-nav-cta" data-link href="/dashboard">Open console ${icon('arrow')}</a>`
      : `<a class="btn primary ih-nav-cta" data-link href="/signup">Start free ${icon('arrow')}</a>`;
    const secondary = authenticated
      ? ''
      : `<a class="ih-nav-signin" data-link href="/login">Sign in</a>`;

    app.innerHTML = `<div class="ih-public-shell">
      <header class="site-header ih-site-header">
        <nav class="site-nav container ih-site-nav">
          ${brand()}
          <div class="nav-links ih-nav-links">
            <a data-link href="/docs/capabilities">Platform</a>
            <a data-link href="/docs">Docs</a>
            <a data-link href="/pricing">Pricing</a>
            <a data-link href="/status"><span class="ih-nav-live">${statusDot()}Status</span></a>
          </div>
          <div class="nav-actions ih-nav-actions">${secondary}${primary}</div>
          <button class="icon-btn nav-toggle" data-nav-toggle aria-label="Open navigation">${icon('menu')}</button>
        </nav>
        <div class="mobile-menu" data-mobile-menu>
          <a data-link href="/docs/capabilities">Platform</a>
          <a data-link href="/docs">Documentation</a>
          <a data-link href="/pricing">Pricing</a>
          <a data-link href="/status">Status</a>
          ${authenticated ? '<a data-link href="/dashboard">Open console</a>' : '<a data-link href="/login">Sign in</a><a data-link href="/signup">Start free</a>'}
        </div>
      </header>
      ${content}
      <footer class="footer ih-footer">
        <div class="container ih-footer-grid">
          <div class="ih-footer-brand">${brand()}<p>One operational surface for agents that need the live internet.</p></div>
          <div><b>Operate</b><a data-link href="/docs/capabilities">Capabilities</a><a data-link href="/docs/monitoring">Monitoring</a><a data-link href="/status">System status</a></div>
          <div><b>Build</b><a data-link href="/docs/quickstart">Quickstart</a><a data-link href="/docs/mcp">MCP gateway</a><a href="https://github.com/sphangcho203-afk/Web-Scrapping-CLI" target="_blank" rel="noreferrer">GitHub</a></div>
          <div class="ih-footer-meta">Internet Hands<br><span>Explicit · scoped · auditable</span></div>
        </div>
      </footer>
    </div>`;
    bindCommon();
  };

  const demoRun = () => `
    <div class="ih-run-demo" aria-label="Internet Hands execution preview">
      <div class="ih-run-demo-head">
        <div><span class="ih-window-dot"></span><span class="ih-window-dot"></span><span class="ih-window-dot"></span></div>
        <span>${statusDot()} LIVE EXECUTION</span>
        <em>run_7f2c91</em>
      </div>
      <div class="ih-demo-command">
        <span>${icon('activity')}</span>
        <p>Research <b>acme.dev</b>, map the product, extract pricing and return evidence.</p>
        <kbd>↵</kbd>
      </div>
      <div class="ih-demo-body">
        <div class="ih-demo-timeline">
          ${[
            ['Route','Intent matched','18 ms'],
            ['Discover','12 sources found','142 ms'],
            ['Browse','Dynamic page rendered','1.8 s'],
            ['Extract','Structured fields captured','326 ms'],
            ['Evidence','7 citations retained','94 ms']
          ].map((x,i)=>`<div class="ih-demo-step ${i<5?'done':''}"><span>${statusDot()}</span><div><b>${x[0]}</b><small>${x[1]}</small></div><em>${x[2]}</em></div>`).join('')}
        </div>
        <div class="ih-demo-inspector">
          <div class="ih-demo-tabs"><b>Overview</b><span>Data</span><span>Evidence</span><span>Raw</span></div>
          <div class="ih-demo-result">
            <span>RESULT</span>
            <h3>Pricing model extracted</h3>
            <p>3 public plans · 14 product links · 7 evidence records</p>
          </div>
          <div class="ih-demo-metrics"><span><small>Pages</small><b>18</b></span><span><small>Latency</small><b>2.4s</b></span><span><small>Credits</small><b>11</b></span></div>
          <div class="ih-evidence-row"><i>01</i><span><b>acme.dev/pricing</b><small>HTML · captured now</small></span><em>98%</em></div>
          <div class="ih-evidence-row"><i>02</i><span><b>docs.acme.dev</b><small>Docs · structured</small></span><em>94%</em></div>
        </div>
      </div>
    </div>`;

  renderHome = async function renderHomeV2() {
    publicShell(`<main class="ih-home">
      <section class="ih-hero">
        <div class="container ih-hero-grid">
          <div class="ih-hero-copy">
            <h1>The internet,<br><span>as an executable workspace.</span></h1>
            <p>Search it. Browse it. Extract from it. Monitor it. Route into APIs and remote tools. Internet Hands gives agents one controlled surface for real internet work.</p>
            <div class="ih-hero-actions">
              <a class="btn primary large" data-link href="${state.me?.user?.email_verified ? '/dashboard' : '/signup'}">Open command center ${icon('arrow')}</a>
              <a class="ih-text-link" data-link href="/docs/quickstart">See how it works ${icon('arrow')}</a>
            </div>
            <div class="ih-hero-proof">
              <span>${statusDot()} Gateway online</span><span>Evidence retained</span><span>Scoped execution</span>
            </div>
          </div>
          ${demoRun()}
        </div>
      </section>

      <section class="ih-client-band">
        <div class="container">
          <div class="ih-band-label"><span>BUILT TO SIT BEHIND THE AGENTS YOU ALREADY USE</span><i></i></div>
          <div class="ih-provider-row">
            ${providerBadge('openai','OpenAI','ChatGPT')}
            ${providerBadge('anthropic','Anthropic','Claude')}
            ${providerBadge('xai','xAI','Grok')}
            ${providerBadge('github','GitHub','Automation')}
            ${providerBadge('mcp','MCP','Any compatible client')}
          </div>
        </div>
      </section>

      <section class="ih-section ih-operation-section">
        <div class="container">
          <div class="ih-section-lead">
            <h2>One instruction becomes a traceable operation.</h2>
            <p>Instead of exposing a wall of tools, Internet Hands discovers the capability, executes through the right provider, and keeps the run inspectable.</p>
          </div>
          <div class="ih-operation-grid">
            <article class="ih-operation-primary">
              <div class="ih-panel-head"><span>RUN / 001842</span><em>${statusDot()} complete</em></div>
              <h3>Map every public pricing signal for a target company.</h3>
              <div class="ih-operation-flow">
                ${['Intent','Route','Browser','Extract','Validate','Evidence'].map((x,i)=>`<span><i>${String(i+1).padStart(2,'0')}</i><b>${x}</b></span>`).join('')}
              </div>
              <div class="ih-operation-footer"><span>6 execution stages</span><span>3 providers</span><span>12 credits</span><b>2.81 s</b></div>
            </article>
            <div class="ih-operation-stack">
              <article><span>SEARCH + FETCH</span><h3>Public web intelligence</h3><p>Discover, fetch, crawl and preserve provenance instead of returning a dead blob of text.</p></article>
              <article><span>BROWSER</span><h3>Dynamic web execution</h3><p>Use controlled Chromium sessions for pages that need a real browser, state, clicks or extraction.</p></article>
              <article><span>TOOL MESH</span><h3>APIs and remote MCPs</h3><p>Route to external capabilities without loading every provider schema into the model at once.</p></article>
            </div>
          </div>
        </div>
      </section>

      <section class="ih-section ih-evidence-section">
        <div class="container ih-evidence-grid">
          <div class="ih-section-lead">
            <h2>Power means nothing if the result is impossible to inspect.</h2>
            <p>Every useful run should leave behind enough context to understand what happened: route, provider, latency, cost, status and evidence.</p>
            <a class="ih-text-link" data-link href="/docs/capabilities">Explore the capability fabric ${icon('arrow')}</a>
          </div>
          <div class="ih-ledger">
            <div class="ih-ledger-head"><span>LIVE RUN LEDGER</span><span>PROVIDER</span><span>STATE</span><span>LATENCY</span></div>
            ${[
              ['req_8ca5f2','web.search','ok','184 ms'],
              ['req_63d1a0','browser.open','ok','1.2 s'],
              ['req_a82e19','mesh.execute','ok','426 ms'],
              ['req_1ed34b','extract.structured','ok','307 ms']
            ].map(x=>`<div class="ih-ledger-row"><code>${x[0]}</code><span>${x[1]}</span><em>${statusDot()} ${x[2]}</em><b>${x[3]}</b></div>`).join('')}
          </div>
        </div>
      </section>

      <section class="ih-final">
        <div class="container ih-final-inner">
          <div><h2>Give the agent reach.<br>Keep the operation under control.</h2><p>One endpoint. Real internet capability. Runs you can actually inspect.</p></div>
          <a class="btn primary large" data-link href="${state.me?.user?.email_verified ? '/dashboard' : '/signup'}">Launch Internet Hands ${icon('arrow')}</a>
        </div>
      </section>
    </main>`);
  };

  const dashboardNav = [
    ['Operate', [
      ['overview','overview','Command center'],
      ['usage','activity','Runs'],
      ['monitors','monitor','Monitors']
    ]],
    ['Connect', [
      ['integrations','plug','Integrations'],
      ['api-keys','key','API keys']
    ]],
    ['Account', [
      ['wallet','wallet','Credits'],
      ['billing','wallet','Billing'],
      ['settings','settings','Settings']
    ]]
  ];

  dashboardShell = function dashboardShellV2(active, content) {
    const u = state.me?.user || {};
    const current = dashboardNav.flatMap(x=>x[1]).find(x=>x[0]===active);
    const currentTitle = current?.[2] || 'Console';
    app.innerHTML = `<div class="app-shell ih-app-shell">
      <aside class="sidebar ih-sidebar">
        <div class="ih-sidebar-top">${brand()}<span class="ih-console-tag">CONTROL PLANE</span></div>
        <nav>
          ${dashboardNav.map(([group,items])=>`<div class="nav-group"><span>${group}</span>${items.map(([slug,ico,title])=>`<a class="${slug===active?'active':''}" data-link href="/dashboard${slug==='overview'?'':`/${slug}`}">${icon(ico)}<b>${title}</b>${slug==='overview'?'<kbd>⌘ K</kbd>':''}</a>`).join('')}</div>`).join('')}
        </nav>
        <div class="ih-sidebar-system">
          <div><span>${statusDot()}</span><b>Internet Hands</b><small>Gateway operational</small></div>
          <a data-link href="/status">View status</a>
        </div>
        <div class="sidebar-foot"><a data-link href="/docs">${icon('docs')} Docs</a><button id="logout">Sign out</button></div>
      </aside>
      <section class="workspace ih-workspace">
        <header class="topbar ih-topbar">
          <div class="ih-topbar-title"><button class="icon-btn mobile-sidebar" data-sidebar-toggle>${icon('menu')}</button><span><small>INTERNET HANDS</small><b>${esc(currentTitle)}</b></span></div>
          <div class="top-actions ih-top-actions">
            <button class="ih-new-run" data-new-run>${icon('activity')} New run <kbd>N</kbd></button>
            <span class="verified-chip">${statusDot()} Live</span>
            <button class="account-button"><i>${esc((u.display_name||u.email||'I')[0].toUpperCase())}</i><b>${esc(u.display_name||u.email||'Account')}</b></button>
          </div>
        </header>
        <main class="content ih-content">${content}</main>
      </section>
      <nav class="mobile-bottom ih-mobile-bottom">
        ${[
          ['overview','overview','Command'],
          ['usage','activity','Runs'],
          ['monitors','monitor','Watch'],
          ['integrations','plug','Connect'],
          ['more','more','More']
        ].map(([slug,ico,title])=>`<a ${slug==='more'?'data-more':'data-link'} href="${slug==='more'?'#':`/dashboard${slug==='overview'?'':`/${slug}`}`}" class="${slug===active?'active':''}">${icon(ico)}<span>${title}</span></a>`).join('')}
      </nav>
      <div class="more-sheet" data-more-sheet><i></i><b>More</b>
        ${dashboardNav.flatMap(x=>x[1]).filter(x=>!['overview','usage','monitors','integrations'].includes(x[0])).map(([slug,ico,title])=>`<a data-link href="/dashboard/${slug}">${icon(ico)}${title}</a>`).join('')}
        <a data-link href="/docs">${icon('docs')}Documentation</a><button id="mobile-logout">Sign out</button>
      </div>
      <div class="sheet-backdrop" data-sheet-backdrop></div>
    </div>`;
    bindCommon();
    $('[data-sidebar-toggle]')?.addEventListener('click',()=>$('.sidebar')?.classList.toggle('open'));
    $('[data-more]')?.addEventListener('click',e=>{e.preventDefault();$('[data-more-sheet]')?.classList.add('open');$('[data-sheet-backdrop]')?.classList.add('open');});
    $('[data-sheet-backdrop]')?.addEventListener('click',()=>{$('[data-more-sheet]')?.classList.remove('open');$('[data-sheet-backdrop]')?.classList.remove('open');});
    $('[data-new-run]')?.addEventListener('click',()=>{
      if(location.pathname!=='/dashboard') return go('/dashboard');
      $('#ih-run-input')?.focus();
    });
    const logout = async()=>{await api('/api/auth/logout',{method:'POST'});state.me=null;go('/');};
    $('#logout')?.addEventListener('click',logout);
    $('#mobile-logout')?.addEventListener('click',logout);
  };

  const runStatus = status => ['ok','accepted'].includes(String(status||'').toLowerCase()) ? 'ok' : 'warn';
  const runLabel = e => (e.tool_ref || 'Internet operation').replace(/^.*?:/,'');

  function openRunInspector(event) {
    const wrap = modal(`<div class="ih-run-modal">
      <div class="modal-head"><span><span class="overline">RUN INSPECTOR</span><h2>${esc(runLabel(event))}</h2></span><button data-close aria-label="Close">×</button></div>
      <div class="ih-inspector-status"><span>${statusDot(runStatus(event.status))}<b>${esc(event.status||'unknown')}</b></span><code>${esc(event.request_id||'No request id')}</code></div>
      <div class="ih-inspector-grid">
        <div><small>Provider</small><b>${esc(event.provider||'—')}</b></div>
        <div><small>Credits</small><b>${fmt(event.credits_charged||0)}</b></div>
        <div><small>Latency</small><b>${event.latency_ms==null?'—':`${fmt(event.latency_ms)} ms`}</b></div>
        <div><small>Created</small><b>${esc(when(event.created_at))}</b></div>
      </div>
      <div class="ih-inspector-section"><span>EXECUTION REFERENCE</span><div class="ih-code-line"><code>${esc(event.tool_ref||'—')}</code><button class="btn small" data-copy="${esc(event.request_id||'')}">${icon('copy')} Copy ID</button></div></div>
      <div class="ih-inspector-note"><b>Why this view matters</b><p>This run comes from your real metered request ledger. A future web-run endpoint can attach payload, browser trace and evidence to this same inspector without changing the information architecture.</p></div>
    </div>`, true);
    bindCommon();
    return wrap;
  }

  function bindRunComposer() {
    const form = $('#ih-run-form');
    if (!form) return;
    $$('[data-run-example]').forEach(b=>b.addEventListener('click',()=>{
      const input = $('#ih-run-input');
      input.value = b.dataset.runExample;
      input.focus();
    }));
    form.addEventListener('submit',e=>{
      e.preventDefault();
      const input = $('#ih-run-input');
      const value = input.value.trim();
      if(!value) return input.focus();
      const brief = `mesh_route(${JSON.stringify(value)})`;
      const target = $('#ih-preflight');
      target.innerHTML = `<div class="ih-preflight-card">
        <div><span>${statusDot()} RUN READY</span><h3>${esc(value)}</h3><p>The current web control plane does not expose direct execution yet. Run this intent through your connected MCP client or scoped API key; the request will appear in Runs automatically.</p></div>
        <div class="ih-preflight-actions"><button class="btn primary" data-copy="${esc(brief)}">${icon('copy')} Copy MCP intent</button><a class="btn" data-link href="/dashboard/integrations">Open integrations</a></div>
      </div>`;
      bindCommon();
      target.scrollIntoView({behavior:'smooth',block:'nearest'});
    });
  }

  dashOverview = async function dashOverviewV2() {
    const [d, usageData] = await Promise.all([
      api('/api/dashboard'),
      api('/api/usage?limit=8').catch(()=>({events:[]}))
    ]);
    const a=d.account||{},u=d.usage||{},events=usageData.events||[];
    const credits=Number(a.monthly_credits||0)+Number(a.purchased_credits||0);
    const health=Number(u.success_rate??100);
    dashboardShell('overview',`
      <section class="ih-command-head">
        <div><span>COMMAND CENTER</span><h1>What should Internet Hands do?</h1><p>Describe the outcome. The execution fabric handles capability discovery, routing and metering behind the boundary.</p></div>
        <div class="ih-command-health"><span>${statusDot()} Gateway live</span><b>${health.toFixed(1)}%</b><small>30-day success</small></div>
      </section>

      <section class="ih-run-composer">
        <form id="ih-run-form">
          <div class="ih-run-input-wrap">${icon('activity')}<textarea id="ih-run-input" rows="3" placeholder="Research a company, inspect a site, extract structured data, monitor a target…"></textarea><button class="btn primary" type="submit">Prepare run ${icon('arrow')}</button></div>
          <div class="ih-run-hints"><span>Try</span><button type="button" data-run-example="Research this URL and return the key claims with evidence">Research a URL</button><button type="button" data-run-example="Inspect this site and map its public API surface">Map an API</button><button type="button" data-run-example="Extract the product catalog into structured data">Extract data</button></div>
        </form>
        <div id="ih-preflight"></div>
      </section>

      <section class="ih-command-stats">
        <div><span>AVAILABLE CREDITS</span><b>${fmt(credits)}</b><small>${fmt(a.monthly_credits)} monthly · ${fmt(a.purchased_credits)} rollover</small></div>
        <div><span>REQUESTS · 24H</span><b>${fmt(u.calls_24h)}</b><small>${fmt(u.calls_30d)} in 30 days</small></div>
        <div><span>AVG LATENCY</span><b>${fmt(u.avg_latency_ms)}<em> ms</em></b><small>Metered execution</small></div>
        <div><span>MONITOR SLOTS</span><b>${fmt(a.monitor_limit)}</b><small>Plan allowance</small></div>
      </section>

      <section class="ih-command-grid">
        <article class="ih-runs-panel">
          <header><div><span>RECENT RUNS</span><h2>Execution ledger</h2></div><a data-link href="/dashboard/usage">View all ${icon('arrow')}</a></header>
          <div class="ih-run-list">
            ${events.length ? events.map((e,i)=>`<button class="ih-run-row" data-run-index="${i}"><span>${statusDot(runStatus(e.status))}</span><div><b>${esc(runLabel(e))}</b><small>${esc(e.provider||'Provider pending')} · ${esc(when(e.created_at))}</small></div><code>${esc((e.request_id||'run').slice(0,16))}</code><em>${e.latency_ms==null?'—':`${fmt(e.latency_ms)} ms`}</em>${icon('arrow')}</button>`).join('') : `<div class="ih-empty-run"><span>${icon('activity')}</span><div><b>No runs yet</b><p>Connect an agent and execute your first internet task. Its real request trace will appear here.</p></div><a class="btn" data-link href="/dashboard/integrations">Connect client</a></div>`}
          </div>
        </article>
        <aside class="ih-system-panel">
          <header><span>SYSTEM</span><h2>Capability fabric</h2></header>
          ${[
            ['Web intelligence','Search · fetch · crawl','Online'],
            ['Browser computers','Chromium sessions','Ready'],
            ['Tool mesh','APIs · remote MCP','Ready'],
            ['Monitoring','Web · API · MCP','Online']
          ].map(x=>`<div class="ih-system-row"><span>${statusDot()}</span><div><b>${x[0]}</b><small>${x[1]}</small></div><em>${x[2]}</em></div>`).join('')}
          <a class="ih-system-link" data-link href="/docs/capabilities">Inspect capabilities ${icon('arrow')}</a>
        </aside>
      </section>`);
    bindRunComposer();
    $$('[data-run-index]').forEach(b=>b.addEventListener('click',()=>openRunInspector(events[Number(b.dataset.runIndex)])));
  };

  dashUsage = async function dashRunsV2() {
    const d=await api('/api/usage?limit=250'),events=d.events||[];
    const credits=events.reduce((s,x)=>s+Number(x.credits_charged||0),0);
    const success=events.length ? events.filter(x=>['ok','accepted'].includes(String(x.status).toLowerCase())).length/events.length*100 : 100;
    const latency=events.map(x=>Number(x.latency_ms)).filter(Number.isFinite).sort((a,b)=>a-b);
    const p95=latency.length ? latency[Math.min(latency.length-1,Math.floor(latency.length*.95))] : 0;
    dashboardShell('usage',`
      <section class="ih-runs-head"><div><span>RUNS</span><h1>Every internet operation, traceable.</h1><p>Requests, providers, status, credits and latency from the real metered execution ledger.</p></div><button class="btn primary" data-new-run-inline>${icon('activity')} New run</button></section>
      <section class="ih-runs-summary"><div><span>RUNS LOADED</span><b>${fmt(events.length)}</b></div><div><span>SUCCESS</span><b>${success.toFixed(1)}%</b></div><div><span>CREDITS</span><b>${fmt(credits)}</b></div><div><span>P95 LATENCY</span><b>${fmt(p95)} <small>ms</small></b></div></section>
      <section class="ih-run-table-wrap">
        <div class="ih-run-table-head"><span>STATE</span><span>RUN</span><span>PROVIDER</span><span>CREDITS</span><span>LATENCY</span><span>TIME</span><span></span></div>
        ${events.length ? events.map((e,i)=>`<button class="ih-run-table-row" data-run-index="${i}"><span>${statusDot(runStatus(e.status))}<b>${esc(e.status||'unknown')}</b></span><span><b>${esc(runLabel(e))}</b><code>${esc((e.request_id||'—').slice(0,22))}</code></span><span>${esc(e.provider||'—')}</span><span>${fmt(e.credits_charged||0)}</span><span>${e.latency_ms==null?'—':`${fmt(e.latency_ms)} ms`}</span><span>${esc(when(e.created_at))}</span><span>${icon('arrow')}</span></button>`).join('') : `<div class="ih-empty-run large"><span>${icon('activity')}</span><div><b>Your run ledger is empty</b><p>Requests executed through your connected clients appear here automatically.</p></div><a class="btn primary" data-link href="/dashboard/integrations">Connect a client</a></div>`}
      </section>`);
    $('[data-new-run-inline]')?.addEventListener('click',()=>go('/dashboard'));
    $$('[data-run-index]').forEach(b=>b.addEventListener('click',()=>openRunInspector(events[Number(b.dataset.runIndex)])));
  };

  // Re-render the current route now that the productized renderers are installed.
  renderRoute();
})();
