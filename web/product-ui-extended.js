/* Internet Hands extended product UI.
 * Second-stage presentation layer for the remaining control-plane surfaces.
 * Reuses the existing API/security/billing handlers instead of duplicating backend logic.
 */
(() => {
  const dot = (tone='ok') => `<i class="ihx-dot ${tone}"></i>`;
  const headline = (kicker, title, body, action='') => `<header class="ihx-page-head"><div><span>${kicker}</span><h1>${title}</h1><p>${body}</p></div>${action}</header>`;
  const empty = (ico,title,body,action='') => `<div class="ihx-empty">${icon(ico)}<div><b>${title}</b><p>${body}</p></div>${action}</div>`;
  const clientMark = (mark, brand) => `<span class="ihx-client-mark ${mark}">${platformMark(mark,brand)}</span>`;

  authShell = function authShellV3(title, sub, content, story='Infrastructure for agents that need reach.') {
    const isVerify = /verify|two-factor|email/i.test(title);
    app.innerHTML = `<main class="auth-layout ihx-auth-layout">
      <section class="auth-story ihx-auth-story">
        <div class="ihx-auth-top">${brand()}<span>${dot()} CONTROL PLANE ONLINE</span></div>
        <div class="ihx-auth-copy">
          <span>INTERNET HANDS / SECURE ACCESS</span>
          <h1>${esc(story)}</h1>
          <p>Identity, permissions, execution and evidence stay inside one auditable boundary.</p>
        </div>
        <div class="ihx-auth-console">
          <div class="ihx-auth-console-head"><span>${dot()} AUTHENTICATED EDGE</span><code>/mcp</code></div>
          <div class="ihx-auth-route"><span>Agent</span><i></i><strong><img src="/assets/mark.svg" alt="">IH</strong><i></i><span>Internet</span></div>
          <div class="ihx-auth-console-foot"><span>${icon('shield')} Verified identity</span><span>${icon('key')} Scoped access</span><span>${icon('activity')} Request ledger</span></div>
        </div>
      </section>
      <section class="auth-main ihx-auth-main">
        <div class="auth-card ihx-auth-card">
          <div class="auth-mobile-brand">${brand()}</div>
          <header><span class="ihx-auth-kicker">${isVerify?'SECURITY CHECK':'WORKSPACE ACCESS'}</span><h2>${title}</h2><p>${sub}</p></header>
          ${content}
          <footer class="ihx-auth-foot">${icon('shield')} Encrypted session · server-side verification · auditable access</footer>
        </div>
      </section>
    </main>`;
    bindCommon();
  };

  dashIntegrations = async function dashIntegrationsV3() {
    const endpoint = `${location.origin}/mcp`;
    const clients = [
      {mark:'openai',brand:'OpenAI',name:'ChatGPT',mode:'OAuth MCP',desc:'Give ChatGPT a stable remote MCP endpoint with explicit scopes.',steps:['Copy the permanent endpoint.','Add it as a remote/custom MCP server.','Approve requested scopes and run a public-web test.']},
      {mark:'anthropic',brand:'Anthropic',name:'Claude',mode:'OAuth MCP',desc:'Connect Claude through Streamable HTTP and browser authorization.',steps:['Copy the permanent endpoint.','Add it under Claude integrations.','Complete OAuth consent and test the connection.']},
      {mark:'xai',brand:'xAI',name:'Grok',mode:'Scoped key',desc:'Use a server-held bearer key when an interactive OAuth flow is not available.',steps:['Create a scoped Internet Hands key.','Use the MCP endpoint as your tool gateway.','Send the key as a Bearer token.']},
      {mark:'hermes',brand:'Nous Research',name:'Hermes Agent',mode:'MCP / key',desc:'Register the same gateway in self-hosted agent runtimes.',steps:['Choose OAuth for user sessions or a scoped key for automation.','Register the endpoint in Hermes.','Run capability discovery before execution.']},
      {mark:'mcp',brand:'Model Context Protocol',name:'Generic MCP client',mode:'OAuth MCP',desc:'Any compatible Streamable HTTP client can use the same gateway.',steps:['Register the endpoint.','Follow protected-resource discovery.','Authorize scopes and test mesh_route.']},
      {mark:'api',brand:'HTTP API',name:'Direct automation',mode:'Bearer key',desc:'Scripts, CI and servers can use scoped credentials directly.',steps:['Create an API key.','Send it through Authorization: Bearer.','Keep one key per integration for clean revocation.']}
    ];
    dashboardShell('integrations',`
      ${headline('CONNECTION FABRIC','One gateway. Every client.','Connect the tools you already use without duplicating provider credentials or changing the endpoint.',`<button class="btn primary" data-copy="${esc(endpoint)}">${icon('copy')} Copy MCP endpoint</button>`)}
      <section class="ihx-endpoint-hero">
        <div><span>${dot()} PERMANENT ENDPOINT</span><h2>${esc(endpoint)}</h2><p>OAuth discovery, scoped access and metered execution live behind this address.</p></div>
        <div class="ihx-endpoint-meta"><span><small>Transport</small><b>Streamable HTTP</b></span><span><small>Identity</small><b>OAuth / key</b></span><span><small>State</small><b>Operational</b></span></div>
      </section>
      <section class="ihx-connection-modes">
        <article><span>${icon('shield')}</span><div><small>INTERACTIVE CLIENTS</small><h3>OAuth MCP</h3><p>Consent + PKCE + short-lived bearer tokens.</p></div><a data-link href="/docs/oauth">OAuth guide ${icon('arrow')}</a></article>
        <article><span>${icon('key')}</span><div><small>AUTOMATION</small><h3>Scoped API keys</h3><p>Independent credentials for scripts, CI and servers.</p></div><a data-link href="/dashboard/api-keys">Manage keys ${icon('arrow')}</a></article>
      </section>
      <section class="ihx-catalog">
        <header><div><span>CLIENT CATALOG</span><h2>Your existing stack, connected properly.</h2></div><p>No raw provider-name wall. Each integration keeps its identity, mode and exact setup path.</p></header>
        <div class="ihx-client-grid">
          ${clients.map((x,i)=>`<article class="ihx-client-card" data-client-card>
            <button class="ihx-client-main" data-client-toggle aria-expanded="false">
              ${clientMark(x.mark,x.brand)}
              <span class="ihx-client-copy"><small>${esc(x.brand)}</small><b>${esc(x.name)}</b><p>${esc(x.desc)}</p></span>
              <span class="ihx-client-mode">${esc(x.mode)}</span>${icon('arrow')}
            </button>
            <div class="ihx-client-detail" hidden>
              <ol>${x.steps.map((step,n)=>`<li><i>${String(n+1).padStart(2,'0')}</i><span>${esc(step)}</span></li>`).join('')}</ol>
              <div class="ihx-client-code"><code>${esc(x.mode.includes('key')||x.mode.includes('Bearer')?`Authorization: Bearer ih_live_…\nEndpoint: ${endpoint}`:endpoint)}</code><button data-copy="${esc(x.mode.includes('key')||x.mode.includes('Bearer')?`Authorization: Bearer ih_live_…\nEndpoint: ${endpoint}`:endpoint)}">${icon('copy')} Copy</button></div>
            </div>
          </article>`).join('')}
        </div>
      </section>`);
    bindCommon();
    $$('[data-client-toggle]').forEach(b=>b.addEventListener('click',()=>{
      const card=b.closest('[data-client-card]'), detail=card.querySelector('.ihx-client-detail'), open=detail.hidden;
      detail.hidden=!open; b.setAttribute('aria-expanded',String(open)); card.classList.toggle('open',open);
    }));
  };

  dashKeys = async function dashKeysV3() {
    const d=await api('/api/api-keys'), keys=d.keys||[], active=keys.filter(x=>!x.revoked_at).length;
    dashboardShell('api-keys',`
      ${headline('ACCESS CONTROL','API keys','Separate credentials by integration. Keep scopes narrow, rotate cleanly and never expose raw secrets twice.',`<button class="btn primary" id="create-key">${icon('key')} Create key</button>`)}
      <section class="ihx-key-summary"><div><span>${icon('shield')}</span><small>ACTIVE KEYS</small><b>${fmt(active)}</b><p>${fmt(keys.length-active)} revoked</p></div><div><span>${icon('key')}</span><small>DEFAULT SCOPE</small><b>MCP</b><p>Read + execute</p></div><div><span>${icon('activity')}</span><small>SECRET POLICY</small><b>Once</b><p>Raw values never reappear</p></div></section>
      <section class="ihx-security-banner">${icon('shield')}<div><b>Credentials are infrastructure.</b><p>Create one key per client or environment so compromise and rotation stay isolated.</p></div><a data-link href="/docs/keys">Read key policy ${icon('arrow')}</a></section>
      <section class="ihx-key-inventory">
        <header><div><span>KEY INVENTORY</span><h2>Scoped credentials</h2></div><small>${fmt(keys.length)} total</small></header>
        ${keys.length?`<div class="ihx-key-table"><div class="ihx-key-table-head"><span>NAME</span><span>PREFIX</span><span>SCOPES</span><span>LAST USED</span><span>STATE</span><span></span></div>${keys.map(x=>`<div class="ihx-key-row"><span><b>${esc(x.name)}</b><small>${esc(x.environment)}</small></span><code>${esc(x.prefix)}…</code><span class="ihx-scope-list">${(x.scopes||[]).map(s=>`<em>${esc(s)}</em>`).join('')}</span><span>${esc(when(x.last_used_at))}</span><span class="ihx-state ${x.revoked_at?'off':'on'}">${dot(x.revoked_at?'warn':'ok')} ${x.revoked_at?'Revoked':'Active'}</span><button class="btn ${x.revoked_at?'':'danger'} small" data-revoke-key="${x.id}" ${x.revoked_at?'disabled':''}>${x.revoked_at?'Revoked':'Revoke'}</button></div>`).join('')}</div>`:empty('key','No API keys yet','Create a scoped credential for a script, server, CI job or non-OAuth client.','<button class="btn primary" id="empty-key">Create first key</button>')}
      </section>`);
    const open=()=>showKeyModal();
    $('#create-key')?.addEventListener('click',open); $('#empty-key')?.addEventListener('click',open);
    $$('[data-revoke-key]').forEach(b=>b.addEventListener('click',async()=>{if(!confirm('Revoke this key?'))return;await api(`/api/api-keys/${b.dataset.revokeKey}/revoke`,{method:'POST'});toast('Key revoked','success');dashKeys();}));
  };

  dashMonitors = async function dashMonitorsV3() {
    const d=await api('/api/monitors'), items=d.monitors||[], enabled=items.filter(x=>x.enabled).length, healthy=items.filter(x=>x.last_status==='ok').length;
    dashboardShell('monitors',`
      ${headline('OBSERVE','Monitors','Turn important public targets into persistent signals instead of repeating the same checks manually.',`<button class="btn primary" id="new-monitor">${icon('monitor')} New monitor</button>`)}
      <section class="ihx-monitor-summary"><div><small>ACTIVE</small><b>${fmt(enabled)}</b><p>of ${fmt(items.length)} monitors</p></div><div><small>HEALTHY</small><b>${fmt(healthy)}</b><p>latest successful checks</p></div><div><small>TEMPLATES</small><b>04</b><p>uptime · latency · JSON · content</p></div></section>
      <section class="ihx-monitor-templates">
        ${[['Uptime','HTTP status','monitor'],['Latency','Threshold','activity'],['JSON field','Value check','docs'],['Content','Change detection','overview']].map(x=>`<button data-template="${x[0]}">${icon(x[2])}<span><b>${x[0]}</b><small>${x[1]}</small></span>${icon('arrow')}</button>`).join('')}
      </section>
      <section class="ihx-monitor-board">
        <header><div><span>WATCHLIST</span><h2>Persistent targets</h2></div><small>${fmt(items.length)} configured</small></header>
        ${items.length?`<div class="ihx-monitor-list">${items.map(x=>`<article class="ihx-monitor-row"><span class="ihx-monitor-orb ${x.last_status==='ok'?'ok':''}"></span><div class="ihx-monitor-target"><b>${esc(x.name)}</b><small>${esc(x.type)} · ${esc(x.target)}</small></div><div><small>LAST CHECK</small><b>${esc(when(x.last_checked_at))}</b></div><span class="ihx-state ${x.last_status==='ok'?'on':'idle'}">${dot(x.last_status==='ok'?'ok':'warn')} ${esc(x.last_status||'Not run')}</span><button class="btn small" data-toggle="${x.id}" data-enabled="${x.enabled}">${x.enabled?'Pause':'Enable'}</button></article>`).join('')}</div>`:empty('monitor','Nothing is watching yet','Create a monitor from a template and Internet Hands will keep the target in view.','<button class="btn primary" id="empty-monitor">Create monitor</button>')}
      </section>`);
    const open=t=>showMonitorModal(t||'');
    $('#new-monitor')?.addEventListener('click',()=>open('')); $('#empty-monitor')?.addEventListener('click',()=>open(''));
    $$('[data-template]').forEach(b=>b.addEventListener('click',()=>open(b.dataset.template)));
    $$('[data-toggle]').forEach(b=>b.addEventListener('click',async()=>{await api(`/api/monitors/${b.dataset.toggle}/toggle`,{method:'POST',body:{enabled:b.dataset.enabled!=='true'}});dashMonitors();}));
  };

  dashWallet = async function dashWalletV3() {
    const [d,p]=await Promise.all([api('/api/wallet?limit=150'),getPlans()]), w=d.wallet||{}, ledger=d.ledger||[];
    const available=Number(w.monthly_credits||0)+Number(w.purchased_credits||0)-Number(w.reserved_credits||0);
    dashboardShell('wallet',`
      ${headline('CAPACITY','Credits','See exactly how much execution capacity is available, reserved and persistent across billing cycles.')}
      <section class="ihx-credit-hero"><div><span>${dot()} AVAILABLE NOW</span><b>${fmt(available)}</b><p>credits ready for execution</p></div><div class="ihx-credit-split"><span><small>MONTHLY</small><b>${fmt(w.monthly_credits)}</b><em>refreshes with plan</em></span><span><small>PURCHASED</small><b>${fmt(w.purchased_credits)}</b><em>rolls over</em></span><span><small>RESERVED</small><b>${fmt(w.reserved_credits)}</b><em>held by active work</em></span></div></section>
      <section class="ihx-credit-packs"><header><div><span>ROLLOVER CAPACITY</span><h2>Add credits without changing plan.</h2></div><p>Purchased credits persist until used.</p></header><div>${(p.credit_packs||[]).map(x=>`<article><span>${esc(x.name)}</span><b>${fmt(x.credits)}</b><small>credits</small><em>${money(x.price_inr)}</em><button class="btn primary small" data-buy="${x.slug}">Purchase</button></article>`).join('')||'<div class="notice">Credit packs unavailable.</div>'}</div></section>
      <section class="ihx-ledger-panel"><header><div><span>LEDGER</span><h2>Wallet activity</h2></div><small>${fmt(ledger.length)} entries loaded</small></header>${ledger.length?`<div class="ihx-ledger-table"><div class="ihx-ledger-table-head"><span>TIME</span><span>KIND</span><span>BUCKET</span><span>SOURCE</span><span>AMOUNT</span></div>${ledger.map(x=>`<div><span>${esc(when(x.created_at))}</span><span>${esc(x.kind)}</span><span>${esc(x.bucket)}</span><span>${esc(x.source)}</span><b class="${Number(x.amount)>=0?'positive':'negative'}">${Number(x.amount)>0?'+':''}${fmt(x.amount)}</b></div>`).join('')}</div>`:empty('wallet','No wallet activity yet','Grants, reservations and purchases will appear here.')}</section>`);
    $$('[data-buy]').forEach(b=>b.addEventListener('click',()=>startCheckout('credits',b.dataset.buy)));
  };

  dashBilling = async function dashBillingV3() {
    const [p,s,pay]=await Promise.all([getPlans(),api('/api/billing/status'),api('/api/billing/payments')]), a=state.me.account||{}, payments=pay.payments||[];
    dashboardShell('billing',`
      ${headline('COMMERCIAL','Billing & plans','Plan capacity, renewal state and payment history without hiding the operational limits behind marketing.',`<span class="ihx-provider-status">${dot(s.configured?'ok':'warn')} Razorpay ${s.configured?'ready':'pending'}</span>`)}
      <section class="ihx-plan-current"><div><span>CURRENT PLAN</span><h2>${esc(a.plan_name||'Free')}</h2><p>${fmt(a.monthly_credits)} monthly credits · resets ${esc(when(a.current_period_end))}</p></div><div><span><small>API KEYS</small><b>${fmt(a.api_key_limit)}</b></span><span><small>MONITORS</small><b>${fmt(a.monitor_limit)}</b></span><span><small>RATE LIMIT</small><b>${fmt(a.rpm_limit)}<em> rpm</em></b></span></div></section>
      <section class="ihx-plan-grid">${(p.plans||[]).map(plan=>`<article class="${plan.slug==='pro'?'featured':''}"><header><span>${esc(plan.name)}</span>${plan.slug==='pro'?'<em>RECOMMENDED</em>':''}</header><div class="ihx-plan-price">${money(plan.monthly_price_inr)}<small>/month</small></div><p>${fmt(plan.included_credits)} monthly credits</p><ul><li>${icon('check')} ${fmt(plan.rpm_limit)} requests / minute</li><li>${icon('check')} ${fmt(plan.api_key_limit)} API keys</li><li>${icon('check')} ${fmt(plan.monitor_limit)} monitors</li><li>${icon('check')} ${plan.browser_enabled?'Browser access':'Public data tools'}</li><li>${icon('check')} ${plan.sandbox_enabled?'Sandbox execution':'Core execution'}</li></ul>${plan.slug==='free'?'<span class="ihx-current-label">Base tier</span>':`<button class="btn ${plan.slug==='pro'?'primary':''}" data-plan="${plan.slug}">Choose ${esc(plan.name)}</button>`}</article>`).join('')}</section>
      <section class="ihx-payment-panel"><header><div><span>PAYMENTS</span><h2>Captured purchase history</h2></div><small>${icon('shield')} server verified</small></header>${payments.length?`<div class="ihx-payment-table"><div class="ihx-payment-head"><span>CREATED</span><span>PURPOSE</span><span>AMOUNT</span><span>STATUS</span><span>REFERENCE</span></div>${payments.map(x=>`<div><span>${esc(when(x.created_at))}</span><span>${esc(x.purpose)}</span><b>${money(Number(x.amount_paise)/100)}</b><span class="ihx-state ${['paid','captured'].includes(x.status)?'on':'idle'}">${dot(['paid','captured'].includes(x.status)?'ok':'warn')} ${esc(x.status)}</span><code>${esc(x.order_id||'—')}</code></div>`).join('')}</div>`:empty('wallet','No purchases yet','Captured payments will appear here after server verification.')}</section>`);
    $$('[data-plan]').forEach(b=>b.addEventListener('click',()=>startCheckout('subscription',b.dataset.plan)));
  };

  dashSettings = async function dashSettingsV3() {
    const [s,sessions]=await Promise.all([api('/api/security/status'),api('/api/account/sessions')]), u=state.me.user, list=sessions.sessions||[];
    const score=s.two_factor_enabled?100:72;
    dashboardShell('settings',`
      ${headline('ACCOUNT','Settings & security','Identity, login protection and active sessions presented as one security surface.')}
      <section class="ihx-settings-grid">
        <article class="ihx-profile-panel"><header><div><span>PROFILE</span><h2>Workspace identity</h2></div><span class="ihx-state on">${dot()} Verified</span></header><form id="profile-form" class="form-stack"><label>Email<input value="${esc(u.email)}" disabled></label><label>Display name<input name="display_name" value="${esc(u.display_name||'')}" maxlength="80" required></label><div class="ihx-linked-account">${clientMark('github','GitHub')}<span><b>GitHub</b><small>${u.github_connected?'Connected to this identity':'Not connected'}</small></span><em>${u.github_connected?'Linked':'Optional'}</em></div><button class="btn">Save profile</button></form></article>
        <article class="ihx-security-panel"><header><div><span>SECURITY POSTURE</span><h2>Protection status</h2></div><b class="ihx-score">${score}<small>/100</small></b></header><div class="ihx-security-rail"><div>${icon('check')}<span><b>Email verification</b><small>Privileged actions unlocked</small></span><em>On</em></div><div>${icon('shield')}<span><b>Authenticator 2FA</b><small>${s.two_factor_enabled?'Required after primary sign-in':'Add a second factor to reach full protection'}</small></span><button class="btn ${s.two_factor_enabled?'danger':'primary'} small" id="toggle-2fa">${s.two_factor_enabled?'Disable':'Set up'}</button></div>${s.two_factor_enabled?`<div>${icon('activity')}<span><b>Recovery codes</b><small>One-use emergency access</small></span><button class="btn small" id="regen">Regenerate</button></div>`:''}</div></article>
        <article class="ihx-sessions-panel"><header><div><span>SESSIONS</span><h2>Active web sessions</h2></div><button class="btn danger small" id="revoke-all">Sign out everywhere</button></header><div>${list.map(x=>`<div class="ihx-session-row">${icon('activity')}<span><b>${x.current?'This session':'Web session'}</b><small>Created ${esc(when(x.created_at))} · expires ${esc(when(x.expires_at))}</small></span><em class="ihx-state ${x.current?'on':'idle'}">${dot(x.current?'ok':'warn')} ${x.current?'Current':'Active'}</em><button class="btn small" data-session="${x.id}">Revoke</button></div>`).join('')||'<div class="notice">No active sessions found.</div>'}</div></article>
        <article class="ihx-password-panel"><header><div><span>PASSWORD</span><h2>Change primary credential</h2></div><p>Changing your password revokes existing sessions.</p></header><form id="password-form" class="ihx-password-form"><label>Current password<input type="password" name="current_password" required></label><label>New password<input type="password" name="new_password" minlength="8" required></label><button class="btn">Change and sign out</button></form></article>
      </section>`);
    $('#profile-form').onsubmit=async e=>{e.preventDefault();try{const r=await api('/api/account/profile',{method:'PATCH',body:Object.fromEntries(new FormData(e.currentTarget))});state.me.user=r.user;toast('Profile updated','success');}catch(error){toast(error.message,'error');}};
    $('#toggle-2fa').onclick=()=>s.two_factor_enabled?showDisable2fa():showSetup2fa(); $('#regen')?.addEventListener('click',showRegenerate);
    $$('[data-session]').forEach(b=>b.onclick=async()=>{const r=await api(`/api/account/sessions/${b.dataset.session}/revoke`,{method:'POST'});if(r.signed_out){state.me=null;go('/login');}else dashSettings();});
    $('#revoke-all').onclick=async()=>{if(!confirm('Sign out every web session?'))return;await api('/api/account/sessions/revoke-all',{method:'POST'});state.me=null;go('/login');};
    $('#password-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/account/password',{method:'POST',body:Object.fromEntries(new FormData(e.currentTarget))});state.me=null;toast('Password changed; sessions revoked','success');go('/login');}catch(error){toast(error.message,'error');}};
  };

  renderPricing = async function renderPricingV3() {
    const data=await getPlans();
    publicShell(`<main class="ihx-pricing-page"><section class="container ihx-pricing-hero"><span>PRICING / EXECUTION CAPACITY</span><h1>Pay for useful work.<br><em>See the limits before you hit them.</em></h1><p>Monthly capacity refreshes. Purchased credits roll over. Provider-heavy work spends according to the operation performed.</p></section><section class="container ihx-public-plan-grid">${(data.plans||[]).map(plan=>`<article class="${plan.slug==='pro'?'featured':''}"><header><b>${esc(plan.name)}</b>${plan.slug==='pro'?'<em>RECOMMENDED</em>':''}</header><div>${money(plan.monthly_price_inr)}<small>/month</small></div><p>${fmt(plan.included_credits)} monthly credits</p><ul><li>${fmt(plan.rpm_limit)} requests / minute</li><li>${fmt(plan.api_key_limit)} API keys</li><li>${fmt(plan.monitor_limit)} monitors</li><li>${plan.browser_enabled?'Browser execution':'Public data tools'}</li><li>${plan.sandbox_enabled?'Sandbox execution':'Core execution'}</li></ul><a class="btn ${plan.slug==='pro'?'primary':''}" data-link href="/signup${plan.slug==='free'?'':`?plan=${plan.slug}`}">${plan.slug==='free'?'Start free':`Choose ${esc(plan.name)}`}</a></article>`).join('')}</section><section class="container ihx-pricing-note"><div><span>CREDIT MODEL</span><h2>Meter the operation, not the mystery.</h2></div><p>Request IDs, provider routing, credit charges and latency are visible in Runs so usage is inspectable after execution.</p></section></main>`);
  };

  renderRoute();
})();
