(() => {
  // Overview is the first route that emits the Cognitive UI contract directly.
  // Keep the data contract identical to the legacy renderer while the remaining
  // dashboard routes migrate incrementally.
  dashOverview = async function cognitiveOverview() {
    const d = await api('/api/dashboard');
    const a = d.account || {};
    const u = d.usage || {};
    const series = d.series || [];
    const max = Math.max(1, ...series.map(x => Number(x.calls)));
    const greeting = new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening';

    const metric = (label, value, note, tone = '') => `
      <article class="stat-card ih-panel ih-overview-metric ${tone}">
        <span class="ih-metric-label">${label}</span>
        <b class="ih-metric-value">${value}</b>
        <small class="ih-muted">${note}</small>
      </article>`;

    dashboardShell('overview', `
      <section class="ih-page-shell ih-overview">
        <header class="page-head ih-page-header">
          <div class="ih-page-heading">
            <span class="overline ih-eyebrow">MISSION CONTROL</span>
            <h1 class="ih-title">Good ${greeting}.</h1>
            <p class="ih-subtitle">Your gateway, wallet, monitoring and security at a glance.</p>
          </div>
          <span class="badge success ih-status" data-tone="success">${esc(a.plan_name || 'Free')} plan</span>
        </header>

        <section class="stats-grid ih-grid ih-grid--4 ih-overview-metrics">
          ${metric('Available credits', fmt(Number(a.monthly_credits || 0) + Number(a.purchased_credits || 0)), `${fmt(a.monthly_credits)} monthly · ${fmt(a.purchased_credits)} rollover`, 'accent')}
          ${metric('Requests · 24h', fmt(u.calls_24h), `${fmt(u.calls_30d)} in 30 days`)}
          ${metric('Success · 30d', `${Number(u.success_rate ?? 100).toFixed(1)}%`, 'Accepted calls')}
          ${metric('Average latency', `${fmt(u.avg_latency_ms)} ms`, 'Metered work')}
        </section>

        <section class="dashboard-grid ih-grid ih-grid--2 ih-overview-main">
          <article class="card chart-card ih-panel">
            <header><div><span class="overline">REQUEST VOLUME</span><h2>Last 30 days</h2></div><a data-link href="/dashboard/usage">Open usage ${icon('arrow')}</a></header>
            ${series.length ? `<div class="bar-chart">${series.map(x => `<i title="${esc(x.day)} · ${fmt(x.calls)}" style="height:${Math.max(3, Number(x.calls) / max * 100)}%"></i>`).join('')}</div>` : `<div class="smart-empty compact">${icon('activity')}<span><b>No requests yet</b><p>Connect an agent. Your first request appears with latency and cost.</p></span><a class="btn small" data-link href="/dashboard/integrations">Connect</a></div>`}
          </article>

          <article class="card health-card ih-panel">
            <header><span><span class="overline">READINESS</span><h2>Account health</h2></span></header>
            ${[
              ['shield', 'Email verified', 'Privileged actions unlocked', 'Ready'],
              ['key', 'API access', 'Scoped credentials', 'Review'],
              ['monitor', 'Monitoring', `${fmt(a.monitor_limit)} slots`, 'Open'],
            ].map(x => `<div><i>${icon(x[0])}</i><span><b>${x[1]}</b><small>${x[2]}</small></span><em>${x[3]}</em></div>`).join('')}
          </article>
        </section>

        <article class="card quick-card ih-panel ih-overview-quick">
          <header><span><span class="overline">QUICK ACTIONS</span><h2>Move the system</h2></span></header>
          <div>${[
            ['plug', 'Connect an agent', 'OAuth or direct key', 'integrations'],
            ['key', 'Create API key', 'Scoped and shown once', 'api-keys'],
            ['monitor', 'Add monitor', 'Web, API, MCP or gaming', 'monitors'],
          ].map(x => `<a data-link href="/dashboard/${x[3]}">${icon(x[0])}<span><b>${x[1]}</b><small>${x[2]}</small></span>${icon('arrow')}</a>`).join('')}</div>
        </article>
      </section>`);
  };

  if (location.pathname === '/dashboard' || location.pathname === '/dashboard/') renderRoute();
})();
