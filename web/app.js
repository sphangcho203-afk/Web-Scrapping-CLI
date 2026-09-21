/* Internet Hands unified browser runtime.
 * Execution order intentionally preserves the former app -> product -> extended -> command stack
 * while shipping one browser asset. New work should edit this file directly instead of adding override scripts.
 */

/* === Core application ==================================================== */
const app = document.getElementById('app');
const state = { me: null, plans: null, sessionChecked: false };
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const fmt = v => new Intl.NumberFormat('en-IN').format(Number(v || 0));
const money = v => `₹${fmt(v)}`;
const when = v => v ? new Date(v).toLocaleString() : 'Never';

const paths = {
  overview:'<path d="M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 9h8V3h-8z"/>',
  activity:'<path d="M3 12h4l2.5-7 5 14 2.5-7h4"/>',
  key:'<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9m-3 3 3 3m-6 0 3 3"/>',
  monitor:'<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',
  plug:'<path d="M8 12h8m-4-4v8M5 3l14 18M19 3 5 21"/>',
  wallet:'<path d="M4 7V5a2 2 0 0 1 2-2h12v4M4 7h16a2 2 0 0 1 2 2v10H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2Z"/><path d="M16 13h3"/>',
  settings:'<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1A8 8 0 0 0 15 6l-.3-2.6h-4L10.4 6A8 8 0 0 0 9 7.1l-2.4-1-2 3.4 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1A8 8 0 0 0 10.4 18l.3 2.6h4L15 18a8 8 0 0 0 1.5-1.1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1Z"/>',
  docs:'<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5zM4 5.5v14A2.5 2.5 0 0 0 6.5 22H20"/>',
  more:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  check:'<path d="m5 12 4 4L19 6"/>', arrow:'<path d="m9 18 6-6-6-6"/>',
  copy:'<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  menu:'<path d="M4 6h16M4 12h16M4 18h16"/>',
  shield:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
};
const icon = (name, label = '') => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" ${label ? `aria-label="${esc(label)}" role="img"` : 'aria-hidden="true"'}>${paths[name] || paths.activity}</svg>`;
const platformPaths = {
  openai:"M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z",
  anthropic:"M17.3041 3.541h-3.6718l6.696 16.918H24Zm-10.6082 0L0 20.459h3.7442l1.3693-3.5527h7.0052l1.3693 3.5528h3.7442L10.5363 3.5409Zm-.3712 10.2232 2.2914-5.9456 2.2914 5.9456Z",
  xai:"M14.234 10.162 22.977 0h-2.072l-7.591 8.824L7.251 0H.258l9.168 13.343L.258 24H2.33l8.016-9.318L16.749 24h6.993zm-2.837 3.299-.929-1.329L3.076 1.56h3.182l5.965 8.532.929 1.329 7.754 11.09h-3.182z",
  github:"M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12",
  mcp:"M13.85 0a4.16 4.16 0 0 0-2.95 1.217L1.456 10.66a.835.835 0 0 0 0 1.18.835.835 0 0 0 1.18 0l9.442-9.442a2.49 2.49 0 0 1 3.541 0 2.49 2.49 0 0 1 0 3.541L8.59 12.97l-.1.1a.835.835 0 0 0 0 1.18.835.835 0 0 0 1.18 0l.1-.098 7.03-7.034a2.49 2.49 0 0 1 3.542 0l.049.05a2.49 2.49 0 0 1 0 3.54l-8.54 8.54a1.96 1.96 0 0 0 0 2.755l1.753 1.753a.835.835 0 0 0 1.18 0 .835.835 0 0 0 0-1.18l-1.753-1.753a.266.266 0 0 1 0-.394l8.54-8.54a4.185 4.185 0 0 0 0-5.9l-.05-.05a4.16 4.16 0 0 0-2.95-1.218c-.2 0-.401.02-.6.048a4.17 4.17 0 0 0-1.17-3.552A4.16 4.16 0 0 0 13.85 0m0 3.333a.84.84 0 0 0-.59.245L6.275 10.56a4.186 4.186 0 0 0 0 5.902 4.186 4.186 0 0 0 5.902 0L19.16 9.48a.835.835 0 0 0 0-1.18.835.835 0 0 0-1.18 0l-6.985 6.984a2.49 2.49 0 0 1-3.54 0 2.49 2.49 0 0 1 0-3.54l6.983-6.985a.835.835 0 0 0 0-1.18.84.84 0 0 0-.59-.245",
  hermes:'M6.6 18.9 12 3l5.4 15.9-5.4-3.2-5.4 3.2Zm2.8-4.8 2.6-1.6 2.6 1.6L12 6.5l-2.6 7.6Z',
  api:'M7 8 3 12l4 4m10-8 4 4-4 4M14 5l-4 14'
};
const platformMark = (name, label = '') => `<svg class="platform-mark mark-${name}" viewBox="0 0 24 24" ${label ? `aria-label="${esc(label)}" role="img"` : 'aria-hidden="true"'}><path d="${platformPaths[name] || platformPaths.api}"/></svg>`;


function toast(message, tone = '') {
  let region = $('#toast-region');
  if (!region) { region = document.createElement('div'); region.id = 'toast-region'; document.body.appendChild(region); }
  const item = document.createElement('div'); item.className = `toast ${tone}`; item.role = 'status'; item.textContent = message; region.appendChild(item);
  setTimeout(() => item.remove(), 3600);
}
async function copyText(text, button) {
  try { await navigator.clipboard.writeText(text); toast('Copied to clipboard', 'success'); if (button) { const old = button.innerHTML; button.innerHTML = `${icon('check')} Copied`; setTimeout(() => button.innerHTML = old, 1400); } }
  catch { toast('Clipboard access was blocked', 'error'); }
}
// Normalize only documented display collections. Do not alter arbitrary run
// metadata, authentication responses, or mutation payloads.
function normalizeCollections(path, data) {
  const endpoint = path.split('?')[0];
  const fields = {
    '/api/public/plans': ['plans', 'credit_packs'],
    '/api/dashboard': ['series'],
    '/api/usage': ['events'],
    '/api/usage/intelligence': ['recent_runs', 'recent_failures', 'series'],
    '/api/api-keys': ['keys'],
    '/api/monitors': ['monitors'],
    '/api/wallet': ['ledger'],
    '/api/billing/payments': ['payments'],
    '/api/account/sessions': ['sessions'],
  }[endpoint] || (/^\/api\/monitors\/[^/]+\/history$/.test(endpoint) ? ['runs'] : null);
  if (!fields) return data;
  const object = (value, field) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      throw new Error(`Expected an object for ${endpoint}: ${field}`);
    }
    return value;
  };
  const collection = (value, field, records = true) => {
    if (value == null) return [];
    if (!Array.isArray(value)) throw new Error(`Expected an array for ${endpoint}: ${field}`);
    if (records) value.forEach((item, index) => object(item, `${field}[${index}]`));
    return value;
  };
  const result = {...object(data, 'response')};
  fields.forEach(field => { result[field] = collection(data[field], field); });
  if (endpoint === '/api/usage/intelligence') {
    const breakdowns = data.breakdowns == null ? {} : object(data.breakdowns, 'breakdowns');
    result.breakdowns = {...breakdowns};
    ['status', 'tool', 'provider'].forEach(field => {
      result.breakdowns[field] = collection(breakdowns[field], `breakdowns.${field}`);
    });
  }
  if (endpoint === '/api/api-keys') {
    result.keys = result.keys.map(key => ({...key, scopes: collection(key.scopes, 'keys.scopes', false)}));
  }
  return result;
}
async function api(path, options = {}) {
  const init = { credentials:'include', cache:'no-store', ...options, headers:{'Content-Type':'application/json', ...(options.headers || {})} };
  if (init.body && typeof init.body !== 'string') init.body = JSON.stringify(init.body);
  const response = await fetch(path, init); let data = {};
  try { data = await response.json(); } catch {}
  if (!response.ok) { const detail = data?.detail; const error = new Error(typeof detail === 'string' ? detail : detail?.message || data?.error || `Request failed (${response.status})`); error.status = response.status; error.code = detail?.code; throw error; }
  return (init.method || 'GET').toUpperCase() === 'GET' ? normalizeCollections(path, data) : data;
}
async function hydrateOptionalSession() {
  if (state.sessionChecked) return;
  state.sessionChecked = true;
  try {
    const current = await api('/api/auth/me');
    if (current?.user?.email_verified) state.me = current;
  } catch {}
}
function clearTransientUi() {
  document.documentElement.classList.remove('ih-overlay-open');
  document.body?.classList.remove('ih-overlay-open');
  document.querySelectorAll('.cos-sidebar.open,.cos-more-sheet.open,[data-sheet-backdrop].open').forEach(el=>el.classList.remove('open'));
  document.querySelectorAll('[data-account-menu]').forEach(el=>{
    const nativePopover = typeof el.hidePopover === 'function' && el.hasAttribute('popover');
    if (nativePopover) {
      try { if (el.matches(':popover-open')) el.hidePopover(); } catch {}
      el.removeAttribute('hidden');
    } else {
      el.setAttribute('hidden','');
    }
  });
  document.querySelectorAll('[aria-expanded="true"]').forEach(el=>el.setAttribute('aria-expanded','false'));
}
function go(path, replace = false) {
  clearTransientUi();
  history[replace ? 'replaceState' : 'pushState']({}, '', path);
  renderRoute();
}
function brand() { return `<a class="brand" data-link href="/" aria-label="Internet Hands home"><img src="/assets/mark.svg" width="38" height="38" alt=""><span>INTERNET <b>HANDS</b></span></a>`; }
function bindCommon() {
  $$('[data-copy]').forEach(b => b.onclick = () => copyText(b.dataset.copy, b));
  const navToggle = $('[data-nav-toggle]');
  const mobileMenu = $('[data-mobile-menu]');
  if (navToggle && mobileMenu) {
    const syncNavState = () => navToggle.setAttribute('aria-expanded', String(mobileMenu.classList.contains('open')));
    navToggle.setAttribute('aria-controls', 'ih-mobile-menu');
    mobileMenu.id = 'ih-mobile-menu';
    syncNavState();
    navToggle.addEventListener('click', () => {
      mobileMenu.classList.toggle('open');
      syncNavState();
    });
  }
}
function codeBlock(code, title = 'Configuration') { return `<div class="code-block"><div><span>${esc(title)}</span><button data-copy="${esc(code)}">${icon('copy')} Copy</button></div><pre><code>${esc(code)}</code></pre></div>`; }
function publicShell(content) {
  const authenticated=!!state.me?.user?.email_verified;
  const desktopActions=authenticated
    ? `<a class="btn primary" data-link href="/dashboard">Dashboard ${icon('arrow')}</a>`
    : `<a class="btn quiet" data-link href="/login">Sign in</a><a class="btn primary" data-link href="/signup">Get started ${icon('arrow')}</a>`;
  const mobileActions=authenticated
    ? '<a data-link href="/dashboard">Back to dashboard</a>'
    : '<a data-link href="/login">Sign in</a><a data-link href="/signup">Create account</a>';
  app.innerHTML = `<header class="site-header"><nav class="site-nav container">${brand()}<div class="nav-links"><a data-link href="/docs">Docs</a><a data-link href="/pricing">Pricing</a><a data-link href="/status">Status</a><a href="https://github.com/sphangcho203-afk/Web-Scrapping-CLI" target="_blank" rel="noreferrer">GitHub</a></div><div class="nav-actions">${desktopActions}</div><button class="icon-btn nav-toggle" data-nav-toggle aria-label="Open navigation">${icon('menu')}</button></nav><div class="mobile-menu" data-mobile-menu><a data-link href="/docs">Documentation</a><a data-link href="/pricing">Pricing</a><a data-link href="/status">Status</a>${mobileActions}</div></header>${content}<footer class="footer"><div class="container footer-grid"><div>${brand()}<p>Infrastructure for agents that need the live internet.</p></div><div><b>Product</b><a data-link href="/docs/mcp">MCP gateway</a><a data-link href="/docs/monitoring">Monitoring</a><a data-link href="/pricing">Pricing</a></div><div><b>Resources</b><a data-link href="/docs/quickstart">Quickstart</a><a data-link href="/status">Status</a></div><div>© ${new Date().getFullYear()} Internet Hands<br>Explicit. Scoped. Auditable.</div></div></footer>`;
  bindCommon();
}
async function getPlans() { if (state.plans) return state.plans; try { state.plans = await api('/api/public/plans'); } catch { state.plans = {plans:[],credit_packs:[]}; } return state.plans; }

function gatewayVisual() { return `<div class="gateway-visual"><span class="visual-label">LIVE ROUTING FABRIC</span><div class="agent-node"><i></i>AGENT</div><div class="route a"></div><div class="core-node"><img src="/assets/mark.svg" width="52" height="52" alt=""><b>INTERNET HANDS</b><small>Policy · route · meter</small></div><div class="route b"></div><div class="mesh-nodes"><span>Browser</span><span>Web data</span><span>APIs</span><span>Remote MCP</span><span>Monitors</span><span>Sandbox</span></div><div class="route-event"><i></i>route accepted <b>42 ms</b></div></div>`; }
function feature(kicker, title, body) { return `<article class="feature-card"><span>${kicker}</span><h3>${title}</h3><p>${body}</p><a data-link href="/docs/capabilities">Explore ${icon('arrow')}</a></article>`; }
function integrationTiles() { return `<div class="integration-grid">${[['OpenAI','ChatGPT clients','OAuth MCP'],['Anthropic','Claude clients','OAuth MCP'],['xAI','Grok workflows','API key'],['Hermes','Self-hosted agents','MCP'],['Generic MCP','Streamable HTTP','OAuth / key'],['REST API','Scripts and CI','Bearer key']].map(x => `<article><b>${x[0]}</b><p>${x[1]}</p><span>${x[2]}</span></article>`).join('')}</div>`; }
function planCards(plans) {
  if (!plans.length) return '<div class="notice">Plan data is temporarily unavailable.</div>';
  return `<div class="pricing-grid">${plans.map(p => `<article class="plan-card ${p.slug === 'pro' ? 'featured' : ''}">${p.slug === 'pro' ? '<span class="plan-flag">MOST CAPABLE</span>' : ''}<span class="plan-name">${esc(p.name)}</span><div class="plan-price">${money(p.monthly_price_inr)}<small>/month</small></div><p>${fmt(p.included_credits)} monthly credits</p><ul><li>${icon('check')} ${fmt(p.rpm_limit)} requests / minute</li><li>${icon('check')} ${fmt(p.api_key_limit)} API keys</li><li>${icon('check')} ${fmt(p.monitor_limit)} monitors</li><li>${icon('check')} ${p.browser_enabled ? 'Browser access' : 'Public data tools'}</li><li>${icon('check')} ${p.sandbox_enabled ? 'Sandbox execution' : 'Core execution'}</li></ul><a class="btn ${p.slug === 'pro' ? 'primary' : ''}" data-link href="/signup${p.slug === 'free' ? '' : `?plan=${p.slug}`}">${p.slug === 'free' ? 'Start free' : `Choose ${esc(p.name)}`}</a></article>`).join('')}</div>`;
}
async function renderHome() {
  const plans = await getPlans();
  publicShell(`<main><section class="hero"><div class="container hero-grid"><div class="hero-copy"><span class="eyebrow"><i></i>MCP GATEWAY · CONTROL PLANE · LIVE</span><h1>Give your agent <em>hands</em> on the internet.</h1><p>One authenticated gateway for live web intelligence, browser computers, public APIs, remote MCPs, monitoring and structured evidence—without drowning the model in schemas.</p><div class="hero-actions"><a class="btn primary large" data-link href="/signup">Start building ${icon('arrow')}</a><a class="btn large" data-link href="/docs/quickstart">Read quickstart</a></div><div class="trust-row"><span>${icon('shield')} Scoped access</span><span>Request metering</span><span>One stable endpoint</span></div></div>${gatewayVisual()}</div></section><div class="cap-strip"><div class="container"><span>SEARCH</span><span>SCRAPE</span><span>BROWSE</span><span>EXTRACT</span><span>MONITOR</span><span>EXECUTE</span><span>PROVE</span></div></div><section class="section"><div class="container"><header class="section-heading"><div><span class="eyebrow">ONE ENDPOINT, MANY CAPABILITIES</span><h2>A small interface to a large internet.</h2></div><p>Agents discover only what they need. Policy, credentials, metering and provider routing remain behind the boundary.</p></header><div class="feature-grid">${feature('01 / COLLECT','Web intelligence','Search, fetch, crawl and extract structured evidence with provenance.')}${feature('02 / OPERATE','Cloud computers','Persistent browsers, terminal jobs, files and isolated execution.')}${feature('03 / ROUTE','Tool mesh','Normalize OpenAPI catalogs, connected apps and remote MCP servers.')}${feature('04 / UNDERSTAND','Gaming intelligence','Resolve public profiles, rank, recent form and progression.')}${feature('05 / OBSERVE','Monitoring','Watch webpages, APIs, MCP endpoints and supported identities.')}${feature('06 / GOVERN','Control plane','Scoped keys, credits, request IDs, limits and usage ledgers.')}</div></div></section><section class="section shaded"><div class="container"><header class="section-heading"><div><span class="eyebrow">AGENT INTEGRATIONS</span><h2>Connect the client you already use.</h2></div><p>Interactive clients use OAuth and explicit consent. Servers use scoped API keys.</p></header>${integrationTiles()}</div></section><section class="section"><div class="container split"><div><span class="eyebrow">FAST PATH</span><h2>Connect once. Discover at runtime.</h2><p class="lead">The canonical URL stays fixed while the capability fabric evolves.</p><ol class="steps"><li><b>01</b><span><strong>Create and verify</strong>Identity is confirmed before privileged access.</span></li><li><b>02</b><span><strong>Connect securely</strong>Choose OAuth consent or a scoped server key.</span></li><li><b>03</b><span><strong>Route and execute</strong>Load only the context needed for the task.</span></li></ol></div>${codeBlock(`${location.origin}/mcp\n\nAuthorization: Bearer ih_live_…\n\nmesh_route("what I need")\nmesh_describe(tool_ref)\nmesh_execute(tool_ref, input)`, 'MCP / Streamable HTTP')}</div></section><section class="security-band"><div class="container split"><div><span class="eyebrow">SECURITY BOUNDARY</span><h2>Capability without credential sprawl.</h2><p>Secrets stay server-side. Verified identity gates privileged actions; optional TOTP protects sign-in.</p><a data-link href="/docs/security">Read the security model ${icon('arrow')}</a></div><div class="security-list"><span>${icon('check')} OAuth code + PKCE</span><span>${icon('check')} One-use recovery codes</span><span>${icon('check')} Captured-payment verification</span><span>${icon('check')} Request IDs and ledgers</span></div></div></section><section class="section"><div class="container"><header class="section-heading"><div><span class="eyebrow">PLANS</span><h2>Pay for useful work.</h2></div><a data-link href="/pricing">Compare every limit ${icon('arrow')}</a></header>${planCards(plans.plans.slice(0,3))}</div></section><section class="final-cta"><div class="container"><span class="eyebrow">INTERNET HANDS</span><h2>Build the agent that can actually reach things.</h2><p>Start with one verified account, one key and one successful request.</p><a class="btn primary large" data-link href="/signup">Open the console ${icon('arrow')}</a></div></section></main>`);
}
async function renderPricing() {
  const plans = await getPlans();
  publicShell(`<main class="page"><section class="page-hero container"><span class="eyebrow">PRICING</span><h1>Infrastructure pricing without mystery.</h1><p>Monthly credits refresh. Purchased credits roll over. Provider-heavy jobs spend according to work.</p></section><section class="container">${planCards(plans.plans)}<article class="card comparison"><header><span class="overline">CREDIT MODEL</span><h2>What work costs</h2></header><div class="table-wrap"><table><thead><tr><th>Capability</th><th>Typical base</th><th>Notes</th></tr></thead><tbody><tr><td>Discovery and health</td><td>1 credit</td><td>Metadata and schemas</td></tr><tr><td>Browser or sandbox</td><td>2 credits</td><td>Per bounded action</td></tr><tr><td>Live web search</td><td>3 credits</td><td>Provider usage may apply</td></tr><tr><td>Fetch or scrape</td><td>5 credits</td><td>Single target</td></tr><tr><td>Crawl</td><td>10 + pages</td><td>Policy bounded</td></tr></tbody></table></div></article><div class="faq-grid"><article><h3>Do credits expire?</h3><p>Monthly credits refresh. Purchased credits remain until used.</p></article><article><h3>When does access change?</h3><p>Only after a captured payment matches the server-created order.</p></article><article><h3>Can I start free?</h3><p>Yes. Verification unlocks the Free plan control plane.</p></article></div></section></main>`);
}
async function renderStatus() {
  let s = {}; try { s = await api('/api/status'); } catch {}
  const rows = [['MCP gateway',true,'/mcp'],['Control database',!!s.control_database,'Accounts and usage'],['OAuth authorization',!!s.oauth,'PKCE'],['Billing',!!s.billing,'Razorpay'],['GitHub sign-in',!!s.github_oauth,'OAuth'],['Monitoring',true,'Control plane']];
  publicShell(`<main class="page"><section class="page-hero container"><span class="eyebrow">SYSTEM STATUS</span><h1>Operational state, without exposing secrets.</h1><p>Configuration-level health for the public gateway and control plane.</p></section><section class="container"><div class="card status-panel"><div class="status-summary"><i></i><span><b>Internet Hands is responding</b><small>Checked ${new Date().toLocaleTimeString()}</small></span></div>${rows.map(x => `<div class="status-row"><span><b>${x[0]}</b><small>${x[2]}</small></span><em class="badge ${x[1] ? 'success' : 'warning'}">${x[1] ? 'Operational' : 'Pending config'}</em></div>`).join('')}</div></section></main>`);
}

const docs = {
  introduction:['Introduction','Get started',`<p>Internet Hands gives agents a compact authenticated interface to internet-facing capabilities. The MCP URL is stable while providers evolve behind it.</p><h2 id="model">Operating model</h2><p>Route intent, inspect the selected tool, execute, then retain request IDs and provenance.</p>${codeBlock('mesh_route("research a public company")\nmesh_describe("selected.tool")\nmesh_execute("selected.tool", {...})','Agent pattern')}`],
  concepts:['Core concepts','Get started','<h2 id="gateway">Gateway</h2><p>The gateway authenticates, meters and routes calls without loading every provider schema.</p><h2 id="credits">Credits</h2><p>Monthly and purchased credits are separate wallet buckets.</p><h2 id="provenance">Provenance</h2><p>Collection retains source, timing and request identifiers.</p>'],
  quickstart:['Quickstart','Get started',`<p>Your first request takes four steps: create an account, verify the email, create a scoped key, then connect a client.</p>${codeBlock(`${location.origin}/mcp\nAuthorization: Bearer ih_live_…`,'Connection')}`],
  account:['Account & verification','Get started','<p>Email signup enters a pending state. Privileged actions stay blocked until a link or six-digit code is accepted.</p><div class="callout">Codes expire after 15 minutes. Resends are rate-limited and replace the prior challenge.</div><h2 id="github">GitHub</h2><p>New GitHub-created Internet Hands accounts still complete product verification.</p>'],
  keys:['API keys','Get started',`${codeBlock('Authorization: Bearer ih_live_…\n# or\nX-API-Key: ih_live_…','HTTP auth')}<p>Raw keys appear once. Only hashes persist. Use one key per integration for clean revocation.</p>`],
  mcp:['MCP overview','MCP',`${codeBlock(`${location.origin}/mcp`,'Streamable HTTP')}<h2 id="flow">Recommended flow</h2><p>Call <code>mesh_route</code>, inspect one schema if needed, then execute.</p>`],
  oauth:['OAuth MCP','MCP',`${codeBlock('GET /.well-known/oauth-protected-resource\nGET /.well-known/oauth-authorization-server','Discovery')}<p>Interactive clients use authorization code with PKCE S256, explicit scopes and short-lived tokens.</p>`],
  clients:['Client guides','MCP','<h2 id="openai">OpenAI / ChatGPT</h2><p>Add the public remote MCP URL and complete browser authorization.</p><h2 id="claude">Claude</h2><p>Use Streamable HTTP and finish authorization in the browser.</p><h2 id="grok">Grok</h2><p>Use a server-held scoped key when interactive OAuth is unavailable.</p><h2 id="hermes">Hermes</h2><p>Register the endpoint as a remote MCP server and keep credentials outside prompts.</p>'],
  capabilities:['Capabilities','Platform','<h2 id="web">Web intelligence</h2><p>Search, fetch, extract, map and bounded crawl paths preserve provenance.</p><h2 id="browser">Browser & sandbox</h2><p>Guarded browser and isolated execution handle dynamic targets.</p><h2 id="mesh">Tool mesh</h2><p>Remote MCP, OpenAPI and provider catalogs become discoverable references.</p><h2 id="gaming">Gaming</h2><p>Supported public identity paths resolve profile and progression.</p>'],
  monitoring:['Monitoring','Control plane','<p>Monitors watch webpages, APIs, MCP endpoints and supported public identities.</p><h2 id="templates">Templates</h2><ul><li>Uptime and HTTP status</li><li>Latency threshold</li><li>JSON field value</li><li>Content change</li></ul>'],
  usage:['Usage','Control plane','<p>Each metered call records request ID, tool, provider, status, credit charge and latency.</p><h2 id="debug">Debugging</h2><p>Start with the request ID; it is the correlation key across the gateway and ledger.</p>'],
  billing:['Billing','Control plane','<p>Orders are priced server-side. Entitlements activate only after signature validation and a captured payment matching order, amount and currency.</p><div class="callout">Repeated webhooks are idempotent and cannot double-credit a wallet.</div>'],
  security:['Security','Security','<h2 id="verification">Verification</h2><p>Privileged mutations require verified identity.</p><h2 id="two-factor">Two-factor</h2><p>TOTP secrets are encrypted; replay is rejected; recovery codes are hashed and one-use.</p><h2 id="sessions">Sessions</h2><p>HTTP-only sessions are revoked on password reset or change.</p>'],
  errors:['Errors & limits','Reference','<div class="table-wrap"><table><thead><tr><th>Code</th><th>Meaning</th></tr></thead><tbody><tr><td><code>invalid_api_key</code></td><td>Invalid or revoked</td></tr><tr><td><code>email_verification_required</code></td><td>Identity gate</td></tr><tr><td><code>insufficient_credits</code></td><td>Wallet cannot fund work</td></tr><tr><td><code>rate_limited</code></td><td>Plan limit reached</td></tr><tr><td><code>scope_denied</code></td><td>Scope missing</td></tr></tbody></table></div>'],
  troubleshooting:['Troubleshooting','Reference','<h2 id="401">MCP returns 401</h2><p>Follow protected-resource metadata or send an active Bearer key.</p><h2 id="email">Email did not arrive</h2><p>Check the address, wait for cooldown, then request a new challenge.</p><h2 id="config">Config clips</h2><p>Use the copy control. Code scrolls internally and never widens the page.</p>'],
};
function docsNav(active) {
  return [...new Set(Object.values(docs).map(x => x[1]))].map(group => `<div class="docs-group"><span>${group}</span>${Object.entries(docs).filter(([,x]) => x[1] === group).map(([slug,x]) => `<a class="${slug === active ? 'active' : ''}" data-link href="/docs/${slug}">${x[0]}</a>`).join('')}</div>`).join('');
}
function renderDocs() {
  const slug = location.pathname.split('/')[2] || 'introduction'; const d = docs[slug] || docs.introduction; const keys = Object.keys(docs); const i = keys.indexOf(slug); const prev = i > 0 ? keys[i-1] : null; const next = i >= 0 && i < keys.length-1 ? keys[i+1] : null;
  app.innerHTML = `<div class="docs-layout"><header class="docs-top">${brand()}<button class="btn small" data-docs-toggle>${icon('menu')} Sections</button><a class="btn primary small" data-link href="${state.me?.user?.email_verified?'/dashboard':'/signup'}">${state.me?.user?.email_verified?'Back to dashboard':'Open console'}</a></header><aside class="docs-sidebar" data-docs-sidebar><label>Search docs<input id="docs-search" placeholder="Filter sections…"></label>${docsNav(slug)}</aside><article class="docs-article"><div class="breadcrumb">Docs / ${d[1]}</div><h1>${d[0]}</h1>${d[2]}<nav class="docs-pager">${prev ? `<a data-link href="/docs/${prev}"><small>Previous</small>${docs[prev][0]}</a>` : '<span></span>'}${next ? `<a data-link href="/docs/${next}"><small>Next</small>${docs[next][0]}</a>` : ''}</nav></article><aside class="docs-toc"><b>On this page</b>${[...d[2].matchAll(/<h2 id="([^"]+)">([^<]+)<\/h2>/g)].map(m => `<a href="#${m[1]}">${m[2]}</a>`).join('')}</aside></div>`;
  bindCommon(); $('[data-docs-toggle]').onclick = () => $('[data-docs-sidebar]').classList.toggle('open'); $('#docs-search').oninput = e => $$('.docs-group a').forEach(a => a.hidden = !a.textContent.toLowerCase().includes(e.target.value.toLowerCase()));
}

function authShell(title, sub, content, story = 'Infrastructure for agents that need reach.') {
  app.innerHTML = `<main class="auth-layout"><section class="auth-story">${brand()}<div class="auth-story-copy"><span class="eyebrow">INTERNET HANDS CONTROL PLANE</span><h1>${story}</h1><p>One secure operating layer for identity, live web access, usage and MCP authorization.</p><div class="auth-capabilities"><span>${icon('shield')} Verified identity</span><span>${icon('key')} Scoped access</span><span>${icon('activity')} Live observability</span></div></div><div class="auth-system-card"><div><span class="live-dot"></span><b>Gateway online</b><small>Policy · route · meter</small></div><div class="auth-system-flow"><span>Agent</span><i></i><strong><img src="/assets/mark.svg" alt="">IH</strong><i></i><span>Internet</span></div></div></section><section class="auth-main"><div class="auth-card"><div class="auth-mobile-brand">${brand()}</div><header><span class="auth-kicker">${title === 'Welcome back' ? 'ACCOUNT ACCESS' : title.includes('Verify') ? 'IDENTITY CHECK' : 'CREATE WORKSPACE'}</span><h2>${title}</h2><p>${sub}</p></header>${content}<footer class="auth-secure">${icon('shield')} Protected with encrypted, HTTP-only sessions</footer></div></section></main>`; bindCommon();
}
function busy(button, on, label) { if (on) { button.dataset.old = button.innerHTML; button.disabled = true; button.textContent = label; } else { button.disabled = false; button.innerHTML = button.dataset.old; } }
function authDestination(result) {
  const next=result.next||(result.verification_required?'/verify-email':'/dashboard');
  if(!result.verification_required)return next;
  const target=new URL(next,location.origin);
  if(result.verification_context)target.searchParams.set('context',result.verification_context);
  if(result.verification_sent===false)target.searchParams.set('delivery','failed');
  return target.pathname+target.search;
}
function renderAuth(mode) {
  const signup = mode === 'signup'; const params = new URLSearchParams(location.search); if (params.get('two_factor') === 'required') return renderTwoFactor(); const github = params.get('github');
  authShell(signup ? 'Create your account' : 'Welcome back', signup ? 'Start with a verified identity and 2,500 monthly credits.' : 'Sign in to the developer control plane.', `${github ? `<div class="notice warning">GitHub: ${esc(github.replaceAll('_',' '))}</div>` : ''}<a class="btn github-btn" href="/api/auth/github/start"><span class="brand-icon github">${platformMark('github','GitHub')}</span><span>Continue with GitHub</span>${icon('arrow')}</a><div class="divider"><span>or use email</span></div><form id="auth-form" class="form-stack">${signup ? '<label>Display name<input name="display_name" maxlength="80" autocomplete="name" placeholder="How should we address you?"></label>' : ''}<label>Email<input required type="email" name="email" autocomplete="email" placeholder="you@example.com"></label><label>Password<div class="password-field"><input id="password" required minlength="8" type="password" name="password" autocomplete="${signup ? 'new-password' : 'current-password'}"><button type="button" data-show>Show</button></div></label>${signup ? '<small>Use at least 8 characters. Verification comes next.</small><p class="ih-auth-policy-note">By creating an account or continuing with GitHub, you agree to the <a data-link href="/legal/terms">Terms</a> and <a data-link href="/legal/acceptable-use">Acceptable Use Policy</a> and acknowledge the <a data-link href="/legal/privacy">Privacy Policy</a>.</p>' : ''}<button class="btn primary large" type="submit">${signup ? 'Create account' : 'Sign in'} ${icon('arrow')}</button></form><div class="auth-links">${signup ? '<span>Already registered? <a data-link href="/login">Sign in</a></span>' : '<a class="btn quiet" data-link href="/forgot-password">Forgot password?</a><span>New here? <a data-link href="/signup">Create account</a></span>'}</div>`);
  $('[data-show]').onclick = e => { const input = $('#password'); input.type = input.type === 'password' ? 'text' : 'password'; e.currentTarget.textContent = input.type === 'password' ? 'Show' : 'Hide'; };
  $('#auth-form').onsubmit = async e => { e.preventDefault(); const button = $('button[type=submit]', e.currentTarget); busy(button,true,signup?'Creating account…':'Signing in…'); try { const result = await api(signup?'/api/auth/signup':'/api/auth/login',{method:'POST',body:Object.fromEntries(new FormData(e.currentTarget))}); if (result.two_factor_required) return renderTwoFactor(); if(result.verification_required){state.me={user:result.user,account:null,verification_required:true};history.pushState({},'',authDestination(result));return renderVerify(state.me);}state.me=null;go(authDestination(result)); } catch(error) { toast(error.message,'error'); busy(button,false); } };
}
function renderTwoFactor() {
  authShell('Two-factor check','Complete the second step before a session is issued.',`<div class="auth-step"><b>1</b><i></i><b class="active">2</b></div><form id="two-factor-form" class="form-stack"><label>Authenticator or recovery code<input required name="code" autocomplete="one-time-code" placeholder="000000 or recovery code"></label><button class="btn primary large">Verify and sign in ${icon('arrow')}</button></form><p class="auth-foot">Challenge expires in 10 minutes. <a data-link href="/login">Start again</a></p>`);
  $('#two-factor-form').onsubmit = async e => { e.preventDefault(); const button=$('button',e.currentTarget); busy(button,true,'Verifying…'); try { const result=await api('/api/auth/2fa/challenge',{method:'POST',body:Object.fromEntries(new FormData(e.currentTarget))}); state.me=null; go(authDestination(result)); } catch(error){toast(error.message,'error');busy(button,false);} };
}
async function renderVerify(seed=null) {
  if(seed) state.me=seed;
  else {
    try { state.me = await api('/api/auth/me'); }
    catch { return go('/login?verify=session_required',true); }
  }
  if (state.me.user.email_verified) return renderOnboarding(); const email=state.me.user.email.replace(/^(.{2}).*(@.*)$/,'$1••••$2'), params=new URLSearchParams(location.search), deliveryFailed=params.get('delivery')==='failed', fromSignin=params.get('context')==='signin';
  const verificationMessage=deliveryFailed?`This account still requires verification, but the email could not be sent. Use Resend code for ${esc(email)}.`:fromSignin?`This account wasn't verified, so we sent a six-digit code to ${esc(email)}. Enter it below to continue.`:`We sent a link and six-digit code to ${esc(email)}.`;
  authShell('Verify your email',verificationMessage,`<div class="verify-mark">${icon('activity')}</div>${deliveryFailed?'<div class="notice warning">Delivery failed. No active account, credits, or subscription will be created until verification succeeds.</div>':''}<form id="verify-form" class="form-stack"><label>Verification code<input class="code-input" required name="code" inputmode="numeric" maxlength="6" pattern="[0-9]{6}" autocomplete="one-time-code" placeholder="000000"></label><button class="btn primary large">Verify account ${icon('arrow')}</button></form><div class="verify-actions"><button id="resend">Resend code <span></span></button><button id="other-account">Use another account</button></div><div class="notice">The newest code replaces older codes and expires after 15 minutes.</div>`,'One small gate before the internet opens up.');
  $('#verify-form').onsubmit=async e=>{e.preventDefault();const button=$('button',e.currentTarget);busy(button,true,'Checking…');try{await api('/api/auth/email-verification/confirm',{method:'POST',body:Object.fromEntries(new FormData(e.currentTarget))});state.me=null;go('/verify-email?verified=1');}catch(error){toast(error.message,'error');busy(button,false);}};
  let seconds=0;const tick=()=>{const b=$('#resend');$('span',b).textContent=seconds?`(${seconds}s)`:'';b.disabled=seconds>0;if(seconds-->0)setTimeout(tick,1000);};
  $('#resend').onclick=async()=>{try{const result=await api('/api/auth/email-verification/send',{method:'POST'});if(!result.sent)throw new Error('Verification email could not be sent. Try again shortly.');seconds=60;tick();toast('New verification email sent','success');}catch(error){toast(error.message,'error');}};
  $('#other-account').onclick=async()=>{await api('/api/auth/logout',{method:'POST'});state.me=null;go('/login');};
  const pollVerification=async()=>{if(location.pathname!=='/verify-email')return;try{const latest=await api('/api/auth/me');if(latest.user.email_verified){state.me=latest;go('/verify-email?verified=1',true);return;}}catch{}setTimeout(pollVerification,3000);};
  setTimeout(pollVerification,3000);
}
function renderOnboarding(){authShell('Email verified','Choose the shortest route to your first successful request.',`<div class="success-orbit">${icon('check')}</div><div class="onboarding-grid"><a data-link href="/dashboard/connections"><b>Connect an agent</b><small>ChatGPT, Claude, Grok or MCP</small>${icon('arrow')}</a><a data-link href="/dashboard/api-keys"><b>Create an API key</b><small>Scripts, servers and CI</small>${icon('arrow')}</a><a data-link href="/dashboard/monitors"><b>Create a monitor</b><small>Watch an endpoint</small>${icon('arrow')}</a><a data-link href="/docs/quickstart"><b>Open quickstart</b><small>Make the first request</small>${icon('arrow')}</a></div><a class="btn quiet onboarding-skip" data-link href="/dashboard">Go to mission control</a>`,'Identity confirmed. Now give your agent reach.');}
function renderRecovery(reset=false){
  const token=new URLSearchParams(location.search).get('token')||'';
  authShell(
    reset?'Choose a new password':'Reset your password',
    reset?'A successful reset signs every web session out.':'Enter the email connected to your account. We will send a secure reset link.',
    `<form id="recovery-form" class="form-stack">${reset?'<label>New password<input required minlength="8" type="password" name="password" autocomplete="new-password"></label><label>Confirm password<input required minlength="8" type="password" name="confirm" autocomplete="new-password"></label>':'<label>Account email<input required type="email" name="email" autocomplete="email" placeholder="you@example.com"></label>'}<button class="btn primary large" ${reset&&!token?'disabled':''}>${reset?'Update password':'Send reset link'} ${icon('arrow')}</button></form>${reset&&!token?'<div class="notice warning">This reset link is missing its security token. Request a new one.</div>':''}<p class="auth-foot"><a data-link href="/login">Back to sign in</a></p>`
  );
  $('#recovery-form').onsubmit=async e=>{
    e.preventDefault();
    const button=$('button',e.currentTarget),values=Object.fromEntries(new FormData(e.currentTarget));
    if(reset&&values.password!==values.confirm)return toast('Passwords do not match','error');
    busy(button,true,reset?'Updating password…':'Sending reset link…');
    try{
      const result=await api(reset?'/api/auth/password-reset/confirm':'/api/auth/password-reset/request',{
        method:'POST',
        body:reset?{token,password:values.password}:values
      });
      if(reset){
        toast('Password updated. Sign in with your new password.','success');
        go('/login');
        return;
      }
      authShell(
        'Check your inbox',
        result.message,
        `<div class="verify-mark">${icon('activity')}</div><div class="notice">The reset link expires after 30 minutes. Only the newest link will work.</div><a class="btn primary large" data-link href="/login">Back to sign in ${icon('arrow')}</a>`,
        'Recover access without weakening account security.'
      );
    }catch(error){
      toast(error.message,'error');
      busy(button,false);
    }
  };
}

const navGroups=[['Workspace',[['overview','overview','Overview'],['usage','activity','Usage'],['api-keys','key','API keys'],['monitors','monitor','Monitors'],['integrations','plug','Integrations']]],['Commercial',[['wallet','wallet','Wallet'],['billing','wallet','Billing & plans']]],['Account',[['settings','settings','Settings & security']]]];
function dashboardShell(active,content){const u=state.me?.user||{};const current=navGroups.flatMap(x=>x[1]).find(x=>x[0]===active);app.innerHTML=`<div class="app-shell"><aside class="sidebar">${brand()}<nav>${navGroups.map(([group,items])=>`<div class="nav-group"><span>${group}</span>${items.map(([slug,ico,title])=>`<a class="${slug===active?'active':''}" data-link href="/dashboard${slug==='overview'?'':`/${slug}`}">${icon(ico)}<b>${title}</b></a>`).join('')}</div>`).join('')}</nav><div class="sidebar-foot"><a data-link href="/docs">${icon('docs')} Docs</a><button id="logout">Sign out</button></div></aside><section class="workspace"><header class="topbar"><div><button class="icon-btn mobile-sidebar" data-sidebar-toggle>${icon('menu')}</button><b>${current?.[2]||'Console'}</b></div><div class="top-actions"><span class="verified-chip">${icon('shield')} Verified</span><button class="account-button"><i>${esc((u.display_name||u.email||'I')[0].toUpperCase())}</i><b>${esc(u.display_name||u.email||'Account')}</b></button></div></header><main class="content">${content}</main></section><nav class="mobile-bottom">${[['overview','overview','Overview'],['usage','activity','Usage'],['integrations','plug','Connect'],['billing','wallet','Billing'],['more','more','More']].map(([slug,ico,title])=>`<a ${slug==='more'?'data-more':'data-link'} href="${slug==='more'?'#':`/dashboard${slug==='overview'?'':`/${slug}`}`}" class="${slug===active?'active':''}">${icon(ico)}<span>${title}</span></a>`).join('')}</nav><div class="more-sheet" data-more-sheet><i></i><b>More</b>${navGroups.flatMap(x=>x[1]).filter(x=>!['overview','usage','integrations','billing'].includes(x[0])).map(([slug,ico,title])=>`<a data-link href="/dashboard/${slug}">${icon(ico)}${title}</a>`).join('')}<a data-link href="/docs">${icon('docs')}Documentation</a><button id="mobile-logout">Sign out</button></div><div class="sheet-backdrop" data-sheet-backdrop></div></div>`;bindCommon();$('[data-sidebar-toggle]').onclick=()=>$('.sidebar').classList.toggle('open');$('[data-more]').onclick=e=>{e.preventDefault();$('[data-more-sheet]').classList.add('open');$('[data-sheet-backdrop]').classList.add('open');};$('[data-sheet-backdrop]').onclick=()=>{$('[data-more-sheet]').classList.remove('open');$('[data-sheet-backdrop]').classList.remove('open');};const logout=async()=>{await api('/api/auth/logout',{method:'POST'});state.me=null;go('/');};$('#logout').onclick=logout;$('#mobile-logout').onclick=logout;}
async function ensureMe(){try{state.me=await api('/api/auth/me');if(!state.me.user.email_verified){go('/verify-email',true);return null;}return state.me;}catch(error){if(error.status===401){go('/login',true);return null;}throw error;}}
const pageHead=(k,t,d,a='')=>`<header class="page-head ih-page-header"><div class="ih-page-heading"><span class="overline ih-eyebrow">${k}</span><h1 class="ih-title">${t}</h1><p class="ih-subtitle">${d}</p></div>${a?`<div class="ih-page-actions">${a}</div>`:''}</header>`;
const stat=(l,v,n,t='')=>`<article class="stat-card ih-panel ih-metric-card ${t}"><span class="ih-metric-label">${l}</span><b class="ih-metric-value">${v}</b><small class="ih-muted">${n}</small></article>`;

async function dashOverview(){const d=await api('/api/dashboard'),a=d.account||{},u=d.usage||{},series=d.series||[],max=Math.max(1,...series.map(x=>Number(x.calls)));dashboardShell('overview',`${pageHead('MISSION CONTROL',`Good ${new Date().getHours()<12?'morning':new Date().getHours()<18?'afternoon':'evening'}.`,'Your gateway, wallet, monitoring and security at a glance.',`<span class="badge success">${esc(a.plan_name||'Free')} plan</span>`)}<section class="stats-grid">${stat('Available credits',fmt(Number(a.monthly_credits||0)+Number(a.purchased_credits||0)),`${fmt(a.monthly_credits)} monthly · ${fmt(a.purchased_credits)} rollover`,'accent')}${stat('Requests · 24h',fmt(u.calls_24h),`${fmt(u.calls_30d)} in 30 days`)}${stat('Success · 30d',`${Number(u.success_rate??100).toFixed(1)}%`,'Accepted calls')}${stat('Average latency',`${fmt(u.avg_latency_ms)} ms`,'Metered work')}</section><section class="dashboard-grid"><article class="card chart-card"><header><div><span class="overline">REQUEST VOLUME</span><h2>Last 30 days</h2></div><a data-link href="/dashboard/usage">Open usage ${icon('arrow')}</a></header>${series.length?`<div class="bar-chart">${series.map(x=>`<i title="${esc(x.day)} · ${fmt(x.calls)}" style="height:${Math.max(3,Number(x.calls)/max*100)}%"></i>`).join('')}</div>`:`<div class="smart-empty compact">${icon('activity')}<span><b>No requests yet</b><p>Connect an agent. Your first request appears with latency and cost.</p></span><a class="btn small" data-link href="/dashboard/connections">Connect</a></div>`}</article><article class="card health-card"><header><span><span class="overline">READINESS</span><h2>Account health</h2></span></header>${[['shield','Email verified','Privileged actions unlocked','Ready'],['key','API access','Scoped credentials','Review'],['monitor','Monitoring',`${fmt(a.monitor_limit)} slots`,'Open']].map(x=>`<div><i>${icon(x[0])}</i><span><b>${x[1]}</b><small>${x[2]}</small></span><em>${x[3]}</em></div>`).join('')}</article></section><article class="card quick-card"><header><span><span class="overline">QUICK ACTIONS</span><h2>Move the system</h2></span></header><div>${[['plug','Connect an agent','OAuth or direct key','integrations'],['key','Create API key','Scoped and shown once','api-keys'],['monitor','Add monitor','Web, API, MCP or gaming','monitors']].map(x=>`<a data-link href="/dashboard/${x[3]}">${icon(x[0])}<span><b>${x[1]}</b><small>${x[2]}</small></span>${icon('arrow')}</a>`).join('')}</div></article>`);}
async function dashUsage(){const d=await api('/api/usage?limit=250'),events=d.events||[],credits=events.reduce((s,x)=>s+Number(x.credits_charged||0),0),ok=events.length?events.filter(x=>['ok','accepted'].includes(x.status)).length/events.length*100:100,lat=events.map(x=>Number(x.latency_ms)).filter(Number.isFinite).sort((a,b)=>a-b),pct=p=>lat.length?lat[Math.min(lat.length-1,Math.floor(lat.length*p))]:0;dashboardShell('usage',`${pageHead('ANALYTICS','Runs & usage','Requests, credits, provider routing and traceable failures.')}<section class="stats-grid">${stat('Requests',fmt(events.length),'Loaded activity')}${stat('Credits',fmt(credits),'Consumed')}${stat('Success',`${ok.toFixed(1)}%`,'OK and accepted')}${stat('p95 latency',`${fmt(pct(.95))} ms`,`p50 ${fmt(pct(.5))} ms`)}</section><article class="card">${events.length?`<div class="table-wrap"><table><thead><tr><th>Time</th><th>Request</th><th>Tool</th><th>Provider</th><th>Status</th><th>Credits</th><th>Latency</th></tr></thead><tbody>${events.map(x=>`<tr><td>${when(x.created_at)}</td><td><code>${esc(x.request_id||'').slice(0,18)}</code></td><td>${esc(x.tool_ref||'—')}</td><td>${esc(x.provider||'—')}</td><td><span class="badge ${['ok','accepted'].includes(x.status)?'success':'danger'}">${esc(x.status)}</span></td><td>${fmt(x.credits_charged)}</td><td>${x.latency_ms==null?'—':`${fmt(x.latency_ms)} ms`}</td></tr>`).join('')}</tbody></table></div>`:`<div class="smart-empty">${icon('activity')}<span><b>Your request log is ready</b><p>Request ID, route, status, cost and latency will appear here.</p></span><a class="btn primary" data-link href="/docs/quickstart">Make first request</a></div>`}</article>`);}
function modal(content,wide=false){const wrap=document.createElement('div');wrap.className='modal-backdrop';wrap.innerHTML=`<section class="modal ${wide?'wide':''}" role="dialog" aria-modal="true">${content}</section>`;document.body.appendChild(wrap);$$('[data-close]',wrap).forEach(b=>b.onclick=()=>wrap.remove());wrap.onclick=e=>{if(e.target===wrap)wrap.remove();};return wrap;}
async function dashKeys(){const d=await api('/api/api-keys'),keys=d.keys||[];dashboardShell('api-keys',`${pageHead('ACCESS','API keys','Credentials for scripts, servers, CI and direct agents.','<button class="btn primary" id="create-key">Create key</button>')}<div class="security-note">${icon('shield')}<span><b>Secrets are shown once.</b><p>Give every integration its own revocable key.</p></span></div><article class="card">${keys.length?`<div class="table-wrap"><table><thead><tr><th>Name</th><th>Prefix</th><th>Scope</th><th>Created</th><th>Last used</th><th></th></tr></thead><tbody>${keys.map(x=>`<tr><td><b>${esc(x.name)}</b><small>${esc(x.environment)}</small></td><td><code>${esc(x.prefix)}…</code></td><td>${(x.scopes||[]).map(s=>`<span class="mini-tag">${esc(s)}</span>`).join(' ')}</td><td>${when(x.created_at)}</td><td>${when(x.last_used_at)}</td><td><button class="btn danger small" data-revoke-key="${x.id}" ${x.revoked_at?'disabled':''}>${x.revoked_at?'Revoked':'Revoke'}</button></td></tr>`).join('')}</tbody></table></div>`:`<div class="smart-empty">${icon('key')}<span><b>No API keys yet</b><p>Create one for a client that cannot use interactive OAuth.</p></span><button class="btn primary" id="empty-key">Create first key</button></div>`}</article>`);const open=()=>showKeyModal();$('#create-key').onclick=open;$('#empty-key')?.addEventListener('click',open);$$('[data-revoke-key]').forEach(b=>b.onclick=async()=>{if(!confirm('Revoke this key?'))return;await api(`/api/api-keys/${b.dataset.revokeKey}/revoke`,{method:'POST'});toast('Key revoked','success');dashKeys();});}
function showKeyModal(){const wrap=modal(`<div class="modal-head"><span><span class="overline">NEW CREDENTIAL</span><h2>Create API key</h2></span><button data-close>×</button></div><form id="key-form" class="form-stack"><label>Name<input required name="name" maxlength="80" placeholder="Production agent"></label><label>Environment<select name="environment"><option value="live">Live</option><option value="test">Test</option></select></label><fieldset><legend>Scopes</legend>${[['mcp:read','MCP discovery'],['mcp:execute','MCP execution'],['account:read','Account usage'],['monitors:read','Monitor status']].map((x,i)=>`<label class="check"><input type="checkbox" name="scope" value="${x[0]}" ${i<2?'checked':''}>${x[1]}</label>`).join('')}</fieldset><button class="btn primary large">Create secure key</button></form>`);$('#key-form',wrap).onsubmit=async e=>{e.preventDefault();const f=new FormData(e.currentTarget);try{const r=await api('/api/api-keys',{method:'POST',body:{name:f.get('name'),environment:f.get('environment'),scopes:f.getAll('scope')}});$('.modal',wrap).innerHTML=`<div class="modal-head"><span><span class="overline">SAVE NOW</span><h2>Your API key</h2></span></div><div class="notice warning">This secret will not appear again.</div>${codeBlock(r.secret,'Secret')}<label class="ack"><input type="checkbox" id="key-saved"> I saved this key securely.</label><button class="btn primary large" id="finish-key" disabled>Finish</button>`;bindCommon();$('#key-saved').onchange=e=>$('#finish-key').disabled=!e.target.checked;$('#finish-key').onclick=()=>{wrap.remove();dashKeys();};}catch(error){toast(error.message,'error');}};}
async function dashMonitors(){const d=await api('/api/monitors'),items=d.monitors||[];dashboardShell('monitors',`${pageHead('OBSERVE','Monitors','Watch webpages, APIs, MCP endpoints and public identities.','<button class="btn primary" id="new-monitor">New monitor</button>')}<div class="template-row">${[['Web page','HTTP / content','web'],['API endpoint','JSON / status','api'],['MCP endpoint','Streamable HTTP','mcp'],['Gaming identity','Public profile','gaming']].map(x=>`<button data-template="${x[2]}">${icon('monitor')}<b>${x[0]}</b><small>${x[1]}</small></button>`).join('')}</div><article class="card">${items.length?`<div class="monitor-list">${items.map(x=>`<div class="monitor-row"><i class="monitor-state ${x.last_status==='ok'?'ok':''}"></i><span><b>${esc(x.name)}</b><small>${esc(x.type)} · ${esc(x.target)}</small></span><span><small>Last check</small><b>${when(x.last_checked_at)}</b></span><span class="badge ${x.last_status==='ok'?'success':'warning'}">${esc(x.last_status||'Not run')}</span><button class="btn small" data-toggle="${x.id}" data-enabled="${x.enabled}">${x.enabled?'Pause':'Enable'}</button></div>`).join('')}</div>`:`<div class="smart-empty">${icon('monitor')}<span><b>Nothing is watching yet</b><p>Start with a template. Status and incidents collect here.</p></span><button class="btn primary" id="empty-monitor">Create monitor</button></div>`}</article>`);const open=t=>showMonitorModal(t);$('#new-monitor').onclick=()=>open('');$('#empty-monitor')?.addEventListener('click',()=>open(''));$$('[data-template]').forEach(b=>b.onclick=()=>open(b.dataset.template));$$('[data-toggle]').forEach(b=>b.onclick=async()=>{await api(`/api/monitors/${b.dataset.toggle}/toggle`,{method:'POST',body:{enabled:b.dataset.enabled!=='true'}});dashMonitors();});}
function showMonitorModal(template=''){const labels={web:'Web page',api:'API endpoint',mcp:'MCP endpoint',gaming:'Gaming identity'};const wrap=modal(`<div class="modal-head"><span><span class="overline">MONITOR WIZARD</span><h2>${template?esc(labels[template]||template):'Create monitor'}</h2></span><button data-close>×</button></div><div class="mini-stepper"><b>1</b><i></i><span>2</span><i></i><span>3</span></div><form id="monitor-form" class="form-stack"><label>Name<input required name="name" maxlength="120" placeholder="Production health"></label><div class="field-pair"><label>Type<select name="type"><option value="web" ${template==='web'?'selected':''}>Web page</option><option value="api" ${template==='api'?'selected':''}>API endpoint</option><option value="mcp" ${template==='mcp'?'selected':''}>MCP endpoint</option><option value="gaming" ${template==='gaming'?'selected':''}>Gaming identity</option></select></label><label>Interval<select name="interval_minutes"><option value="15">15 min</option><option value="60" selected>1 hour</option><option value="360">6 hours</option><option value="1440">Daily</option></select></label></div><label>Target<input required name="target" placeholder="https://example.com/health"></label><button class="btn primary large">Create monitor</button></form>`);$('#monitor-form',wrap).onsubmit=async e=>{e.preventDefault();const body=Object.fromEntries(new FormData(e.currentTarget));body.interval_minutes=Number(body.interval_minutes);try{await api('/api/monitors',{method:'POST',body});wrap.remove();toast('Monitor created','success');dashMonitors();}catch(error){toast(error.message,'error');}};}
async function dashIntegrations(){
  const endpoint=`${location.origin}/mcp`;
  const clients=[
    {mark:'openai',brand:'OpenAI',name:'ChatGPT',mode:'OAuth MCP',tone:'emerald',steps:['Copy your permanent endpoint.','Add it as a custom MCP server in ChatGPT.','Approve the requested scopes and run a test.']},
    {mark:'anthropic',brand:'Anthropic',name:'Claude',mode:'OAuth MCP',tone:'sand',steps:['Copy your permanent endpoint.','Add the connector in Claude integrations.','Complete OAuth consent, then test a public page.']},
    {mark:'xai',brand:'xAI',name:'Grok',mode:'API key',tone:'mono',steps:['Create a scoped Internet Hands key.','Use the endpoint as your tool gateway.','Send the key as a Bearer token.']},
    {mark:'hermes',brand:'Nous Research',name:'Hermes Agent',mode:'MCP / key',tone:'violet',steps:['Choose OAuth for a user session or a key for automation.','Register the endpoint in Hermes Agent.','Run a capability discovery request.']},
    {mark:'mcp',brand:'Model Context Protocol',name:'Generic MCP client',mode:'OAuth MCP',tone:'orange',steps:['Register the endpoint in any Streamable HTTP client.','Follow protected-resource discovery.','Authorize scopes and test the connection.']},
    {mark:'api',brand:'HTTP API',name:'Direct API',mode:'Bearer key',tone:'cyan',steps:['Create a scoped API key.','Send it in the Authorization header.','Call only the capabilities granted to that key.']}
  ];
  dashboardShell('connections',`${pageHead('CONNECT','Integrations','Connect leading AI clients to one permanent, policy-controlled endpoint.','<span class="badge success">Streamable HTTP · Ready</span>')}
  <section class="connection-hero card">
    <div class="endpoint-copy"><span class="overline">YOUR PERMANENT MCP ENDPOINT</span><h2>${esc(endpoint)}</h2><p>Stable across every client. OAuth discovery and scoped direct access are already enabled.</p></div>
    <button class="btn primary endpoint-button" data-copy="${esc(endpoint)}">${icon('copy')} Copy endpoint</button>
  </section>
  <section class="connection-modes">
    <article><span class="mode-icon">${icon('shield')}</span><div><span>INTERACTIVE</span><h3>OAuth MCP</h3><p>Consent, PKCE and short-lived tokens.</p></div><a data-link href="/docs/oauth">Guide ${icon('arrow')}</a></article>
    <article><span class="mode-icon">${icon('key')}</span><div><span>AUTOMATION</span><h3>Direct key</h3><p>Scoped access for scripts and agents.</p></div><a data-link href="/dashboard/api-keys">Create key ${icon('arrow')}</a></article>
  </section>
  <header class="catalog-head"><div><span class="overline">CLIENT CATALOG</span><h2>Connect your stack</h2></div><p>Choose a platform for exact setup instructions.</p></header>
  <section class="integration-guides">
    ${clients.map((x,i)=>`<article class="integration-card ${x.tone}">
      <button class="integration-summary" aria-expanded="false">
        <span class="brand-icon ${x.mark}">${platformMark(x.mark,x.brand)}</span>
        <span class="integration-name"><small>${esc(x.brand)}</small><b>${esc(x.name)}</b><em>${esc(x.mode)}</em></span>
        <span class="integration-action">Setup ${icon('arrow')}</span>
      </button>
      <div class="integration-detail" hidden>
        <ol>${x.steps.map(step=>`<li>${esc(step)}</li>`).join('')}</ol>
        ${codeBlock(x.mode.includes('key')||x.mode.includes('Bearer')?`Authorization: Bearer ih_live_…\nEndpoint: ${endpoint}`:endpoint,`${x.name} connection`)}
      </div>
    </article>`).join('')}
  </section>`);
  bindCommon();
  $$('.integration-summary').forEach(b=>b.onclick=()=>{
    const card=b.closest('.integration-card'),detail=b.nextElementSibling,opening=detail.hidden;
    detail.hidden=!opening;b.ariaExpanded=String(opening);card.classList.toggle('open',opening);
  });
}
async function dashWallet(){const [d,p]=await Promise.all([api('/api/wallet?limit=150'),getPlans()]),w=d.wallet||{};dashboardShell('wallet',`${pageHead('CREDITS','Wallet','Monthly credits spend first. Purchased credits roll over.')}<div class="wallet-hero">${[['MONTHLY',w.monthly_credits,'Refreshes with plan'],['PURCHASED',w.purchased_credits,'Rollover balance'],['RESERVED',w.reserved_credits,'Work currently held']].map(x=>`<article><span>${x[0]}</span><b>${fmt(x[1])}</b><small>${x[2]}</small></article>`).join('')}</div><header class="subhead"><span><span class="overline">TOP UP</span><h2>Add rollover credits</h2></span></header><div class="pack-grid">${(p.credit_packs||[]).map(x=>`<article><span>${esc(x.name)}</span><b>${fmt(x.credits)} credits</b><em>${money(x.price_inr)}</em><button class="btn primary small" data-buy="${x.slug}">Purchase</button></article>`).join('')||'<div class="notice">Credit packs unavailable.</div>'}</div><article class="card"><header><span><span class="overline">LEDGER</span><h2>Wallet activity</h2></span></header>${d.ledger.length?`<div class="table-wrap"><table><thead><tr><th>Time</th><th>Kind</th><th>Bucket</th><th>Amount</th><th>Source</th></tr></thead><tbody>${d.ledger.map(x=>`<tr><td>${when(x.created_at)}</td><td>${esc(x.kind)}</td><td>${esc(x.bucket)}</td><td class="${Number(x.amount)>=0?'positive':''}">${Number(x.amount)>0?'+':''}${fmt(x.amount)}</td><td>${esc(x.source)}</td></tr>`).join('')}</tbody></table></div>`:'<div class="smart-empty compact"><span><b>No wallet activity yet</b><p>Grants and purchases appear here.</p></span></div>'}</article>`);$$('[data-buy]').forEach(b=>b.onclick=()=>startCheckout('credits',b.dataset.buy));}
async function dashBilling(){const [p,s,pay]=await Promise.all([getPlans(),api('/api/billing/status'),api('/api/billing/payments')]),a=state.me.account||{};dashboardShell('billing',`${pageHead('COMMERCIAL','Billing & plans','Plan limits, renewal state and captured-payment history.',`<span class="badge ${s.configured?'success':'warning'}">Razorpay ${s.configured?'ready':'pending'}</span>`)}<div class="current-plan card"><span><span class="overline">CURRENT PLAN</span><h2>${esc(a.plan_name||'Free')}</h2><p>${fmt(a.monthly_credits)} monthly credits · resets ${when(a.current_period_end)}</p></span><div><span>Keys <b>${fmt(a.api_key_limit)}</b></span><span>Monitors <b>${fmt(a.monitor_limit)}</b></span><span>RPM <b>${fmt(a.rpm_limit)}</b></span></div></div>${planCards(p.plans)}<article class="card"><header><span><span class="overline">PAYMENTS</span><h2>Purchase history</h2></span><em>${icon('shield')} Verified server-side</em></header>${pay.payments.length?`<div class="table-wrap"><table><thead><tr><th>Created</th><th>Purpose</th><th>Amount</th><th>Status</th><th>Reference</th></tr></thead><tbody>${pay.payments.map(x=>`<tr><td>${when(x.created_at)}</td><td>${esc(x.purpose)}</td><td>${money(Number(x.amount_paise)/100)}</td><td><span class="badge ${['paid','captured'].includes(x.status)?'success':'warning'}">${esc(x.status)}</span></td><td><code>${esc(x.order_id||'—')}</code></td></tr>`).join('')}</tbody></table></div>`:'<div class="smart-empty compact"><span><b>No purchases yet</b><p>Captured payments appear here.</p></span></div>'}</article>`);$$('.plan-card a[href*="plan="]').forEach(a=>a.onclick=e=>{e.preventDefault();startCheckout('subscription',new URL(a.href).searchParams.get('plan'));});}
async function startCheckout(purpose,slug){try{const r=await api('/api/billing/create-order',{method:'POST',body:{purpose,slug}});if(!window.Razorpay)await new Promise((ok,no)=>{const s=document.createElement('script');s.src='https://checkout.razorpay.com/v1/checkout.js';s.onload=ok;s.onerror=no;document.head.appendChild(s);});new Razorpay({key:r.key_id,order_id:r.order.id,amount:r.order.amount,currency:'INR',name:'Internet Hands',description:purpose==='credits'?'Credit top-up':'Plan',theme:{color:'#5de1e6'},handler:async response=>{try{await api('/api/billing/verify',{method:'POST',body:response});toast('Payment verified','success');state.me=null;go(`/dashboard/${purpose==='credits'?'wallet':'billing'}`);}catch(error){toast(error.message,'error');}}}).open();}catch(error){toast(error.message,'error');}}
async function dashSettings(){const [s,sessions,phone]=await Promise.all([api('/api/security/status'),api('/api/account/sessions'),api('/api/auth/phone/status')]),u=state.me.user;dashboardShell('settings',`${pageHead('ACCOUNT','Settings & security','Identity, login protection, active sessions and recovery.')}<div class="settings-grid"><section class="card"><header><span><span class="overline">PROFILE</span><h2>Account details</h2></span><span class="badge success">Verified</span></header><form id="profile-form" class="form-stack"><label>Email<input value="${esc(u.email)}" disabled></label><label>Display name<input name="display_name" value="${esc(u.display_name||'')}" maxlength="80" required></label><div class="linked-row"><i>GH</i><span><b>GitHub</b><small>${u.github_connected?'Connected':'Not connected'}</small></span><em class="badge ${u.github_connected?'success':'neutral'}">${u.github_connected?'Linked':'Optional'}</em></div><button class="btn">Save profile</button></form></section><section class="card"><header><span><span class="overline">SECURITY</span><h2>Protection status</h2></span><span class="badge ${s.two_factor_enabled?'success':'warning'}">${s.two_factor_enabled?'2FA enabled':s.two_factor_available?'2FA available':'2FA needs server configuration'}</span></header><div class="security-status"><div>${icon('check')}<span><b>Email verified</b><small>Privileged actions unlocked</small></span><em>On</em></div><div>${icon('shield')}<span><b>Authenticator 2FA</b><small>${s.two_factor_enabled?'Required after primary sign-in':'Add a second factor'}</small></span><button class="btn ${s.two_factor_enabled?'danger':'primary'} small" id="toggle-2fa">${s.two_factor_enabled?'Disable':'Set up'}</button></div>${s.two_factor_enabled?`<div>${icon('activity')}<span><b>Recovery codes</b><small>Regenerate when needed</small></span><button class="btn small" id="regen">Regenerate</button></div>`:''}</div></section><section class="card"><header><span><span class="overline">PHONE IDENTITY</span><h2>Phone ownership</h2></span><span class="badge ${phone.verified?'success':phone.pending?'warning':'neutral'}">${phone.verified?'Verified':phone.pending?'Code sent':'Optional'}</span></header><div class="security-status">${phone.verified?`<div>${icon('check')}<span><b>${esc(phone.masked_phone||phone.phone)}</b><small>${esc([phone.carrier_name,phone.line_type||phone.number_type].filter(Boolean).join(' · ')||'Ownership verified')}</small></span><em>On</em></div><div>${icon('activity')}<span><b>Phone intelligence</b><small>${esc([phone.risk?.location_description,(phone.risk?.timezones||[]).slice(0,2).join(', ')].filter(Boolean).join(' · ')||'Local metadata + configured carrier/risk sources')}</small></span><button class="btn small" id="refresh-phone-intel">Refresh</button></div><div>${icon('plug')}<span><b>Sources</b><small>${esc((phone.risk?.providers_used||['libphonenumber']).join(' → '))}</small></span><em>${phone.risk?.sms_capable_heuristic===false?'Check route':'Ready'}</em></div><button class="btn danger small" id="remove-phone">Remove phone</button>`:`${phone.pending?`<div class="notice">Code sent to ${esc(phone.pending.masked_phone)} via ${esc(phone.pending.channel)}.</div><form id="phone-confirm-form" class="form-stack"><label>Verification code<input name="code" inputmode="numeric" autocomplete="one-time-code" minlength="4" maxlength="10" required></label><button class="btn primary">Verify phone</button></form>`:''}<form id="phone-start-form" class="form-stack"><label>Phone number<input name="phone" type="tel" autocomplete="tel" placeholder="+14155552671" required></label><div class="inline-form"><label>Region <input name="region" maxlength="2" placeholder="US"></label><label>Channel<select name="channel"><option value="sms">SMS</option><option value="voice">Voice</option></select></label></div><button class="btn primary">Send verification code</button><small>Use E.164 (+country code) when possible. Internet Hands verifies possession; it does not identify the subscriber behind a SIM.</small></form>`}</div></section><section class="card full"><header><span><span class="overline">SESSIONS</span><h2>Active web sessions</h2></span><button class="btn danger small" id="revoke-all">Sign out everywhere</button></header><div class="session-list">${sessions.sessions.map(x=>`<div>${icon('activity')}<span><b>${x.current?'This session':'Web session'}</b><small>Created ${when(x.created_at)} · expires ${when(x.expires_at)}</small></span><em class="badge ${x.current?'success':'neutral'}">${x.current?'Current':'Active'}</em><button class="btn small" data-session="${x.id}">Revoke</button></div>`).join('')}</div></section><section class="card full"><header><span><span class="overline">PASSWORD</span><h2>Change password</h2></span></header><form id="password-form" class="inline-form"><label>Current password<input type="password" name="current_password" required></label><label>New password<input type="password" name="new_password" minlength="8" required></label><button class="btn">Change and sign out</button></form></section></div>`);$('#profile-form').onsubmit=async e=>{e.preventDefault();try{const r=await api('/api/account/profile',{method:'PATCH',body:Object.fromEntries(new FormData(e.currentTarget))});state.me.user=r.user;toast('Profile updated','success');}catch(error){toast(error.message,'error');}};$('#toggle-2fa').onclick=()=>s.two_factor_enabled?showDisable2fa():showSetup2fa();$('#regen')?.addEventListener('click',showRegenerate);$('#phone-start-form')?.addEventListener('submit',async e=>{e.preventDefault();const button=$('button',e.currentTarget);busy(button,true,'Sending…');try{const body=Object.fromEntries(new FormData(e.currentTarget));if(!body.region)delete body.region;await api('/api/auth/phone/start',{method:'POST',body});toast('Verification code sent','success');dashSettings();}catch(error){toast(error.message,'error');busy(button,false);}});$('#phone-confirm-form')?.addEventListener('submit',async e=>{e.preventDefault();const button=$('button',e.currentTarget);busy(button,true,'Verifying…');try{await api('/api/auth/phone/confirm',{method:'POST',body:Object.fromEntries(new FormData(e.currentTarget))});toast('Phone verified','success');dashSettings();}catch(error){toast(error.message,'error');busy(button,false);}});$('#refresh-phone-intel')?.addEventListener('click',async e=>{busy(e.currentTarget,true,'Checking…');try{await api('/api/auth/phone/intelligence',{method:'POST'});toast('Phone intelligence refreshed','success');dashSettings();}catch(error){toast(error.message,'error');busy(e.currentTarget,false);}});$('#remove-phone')?.addEventListener('click',async()=>{if(!confirm('Remove the verified phone from this account?'))return;try{await api('/api/auth/phone',{method:'DELETE'});toast('Phone removed','success');dashSettings();}catch(error){toast(error.message,'error');}});$('[data-session]').forEach(b=>b.onclick=async()=>{const r=await api(`/api/account/sessions/${b.dataset.session}/revoke`,{method:'POST'});if(r.signed_out){state.me=null;go('/login');}else dashSettings();});$('#revoke-all').onclick=async()=>{if(!confirm('Sign out every web session?'))return;await api('/api/account/sessions/revoke-all',{method:'POST'});state.me=null;go('/login');};$('#password-form').onsubmit=async e=>{e.preventDefault();try{await api('/api/account/password',{method:'POST',body:Object.fromEntries(new FormData(e.currentTarget))});state.me=null;toast('Password changed; sessions revoked','success');go('/login');}catch(error){toast(error.message,'error');}};}
function showSetup2fa(){api('/api/auth/2fa/setup',{method:'POST'}).then(setup=>{const wrap=modal(`<div class="modal-head"><span><span class="overline">STEP 1 OF 2</span><h2>Set up authenticator</h2></span><button data-close aria-label="Close">×</button></div><div class="setup-panel"><div class="qr-panel"><img src="${esc(setup.qr_data_uri)}" width="176" height="176" alt="Authenticator setup QR code"><small>Scan with your authenticator</small></div><span><p>Add Internet Hands in your authenticator app.</p>${codeBlock(setup.secret,'Manual key')}${codeBlock(setup.otpauth_uri,'Authenticator URI')}</span></div><form id="confirm-2fa" class="form-stack"><label>Current 6-digit code<input class="code-input" name="code" required maxlength="6" pattern="[0-9]{6}" inputmode="numeric" autocomplete="one-time-code"></label><button class="btn primary large">Verify and enable</button></form>`,true);$('#confirm-2fa',wrap).onsubmit=async e=>{e.preventDefault();try{const r=await api('/api/auth/2fa/confirm',{method:'POST',body:Object.fromEntries(new FormData(e.currentTarget))});showCodes(wrap,r.recovery_codes);}catch(error){toast(error.message,'error');}};}).catch(error=>toast(error.message,'error'));}
function showCodes(wrap,codes){$('.modal',wrap).innerHTML=`<div class="modal-head"><span><span class="overline">FINAL STEP</span><h2>Save recovery codes</h2></span></div><div class="notice warning">Each code works once and will not appear again.</div><div class="recovery-grid">${codes.map(x=>`<code>${esc(x)}</code>`).join('')}</div><button class="btn" data-copy="${esc(codes.join('\n'))}">${icon('copy')} Copy all</button><label class="ack"><input type="checkbox" id="codes-saved"> I stored these separately.</label><button class="btn primary large" id="finish-2fa" disabled>Finish</button>`;bindCommon();$('#codes-saved').onchange=e=>$('#finish-2fa').disabled=!e.target.checked;$('#finish-2fa').onclick=()=>{wrap.remove();dashSettings();};}
function showDisable2fa(){const wrap=modal(`<div class="modal-head"><span><span class="overline">SECURITY CHANGE</span><h2>Disable 2FA</h2></span><button data-close>×</button></div><div class="notice warning">Existing recovery codes will be invalidated.</div><form id="disable-2fa" class="form-stack"><label>Authenticator or recovery code<input name="code" required></label><button class="btn danger large">Disable 2FA</button></form>`);$('#disable-2fa',wrap).onsubmit=async e=>{e.preventDefault();try{await api('/api/auth/2fa/disable',{method:'POST',body:Object.fromEntries(new FormData(e.currentTarget))});wrap.remove();dashSettings();}catch(error){toast(error.message,'error');}};}
function showRegenerate(){const wrap=modal(`<div class="modal-head"><span><span class="overline">RECOVERY</span><h2>Regenerate codes</h2></span><button data-close>×</button></div><form id="regen-form" class="form-stack"><label>Authenticator code<input name="code" required maxlength="6"></label><button class="btn primary">Generate new codes</button></form>`);$('#regen-form',wrap).onsubmit=async e=>{e.preventDefault();try{const r=await api('/api/auth/2fa/recovery/regenerate',{method:'POST',body:Object.fromEntries(new FormData(e.currentTarget))});showCodes(wrap,r.recovery_codes);}catch(error){toast(error.message,'error');}};}


const LEGAL_ALIASES={'/terms':'terms','/privacy':'privacy','/acceptable-use':'acceptable-use','/cookies':'cookies','/billing-policy':'billing','/security':'security'};
function legalDocs(){return window.IH_LEGAL_DOCS||{}}
function legalMeta(){return window.IH_LEGAL_META||{}}
function legalHref(slug){return `/legal/${slug}`}
function legalBlock(block){
  if(!block)return '';
  if(block.type==='p')return `<p>${esc(block.text)}</p>`;
  if(block.type==='ul')return `<ul>${(block.items||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`;
  if(block.type==='note')return `<aside class="ih-legal-callout"><b>${esc(block.title||'Note')}</b><p>${esc(block.text)}</p></aside>`;
  if(block.type==='table')return `<div class="ih-legal-table-wrap"><table><thead><tr>${(block.headers||[]).map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${(block.rows||[]).map(row=>`<tr>${row.map(x=>`<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  return '';
}
function legalSideNav(active=''){
  return `<nav class="ih-legal-side" aria-label="Legal documents"><a class="${!active?'active':''}" data-link href="/legal"><b>Legal center</b></a>${Object.entries(legalDocs()).map(([slug,doc])=>`<a class="${slug===active?'active':''}" data-link href="${legalHref(slug)}"><b>${esc(doc.shortTitle||doc.title)}</b></a>`).join('')}</nav>`;
}
function renderLegalHub(){
  const items=legalDocs(),m=legalMeta();document.title='Legal Center — Internet Hands';
  publicShell(`<main class="ih-legal-page"><section class="ih-legal-hero"><div class="container"><span class="ih-legal-kicker">TRUST / POLICY / CONTROL</span><h1>Rules that match the product.</h1><p>Internet Hands can search, browse, extract, monitor, route, and execute. These documents define the boundaries around that power, the data it processes, and how paid usage works.</p><div class="ih-legal-meta"><span>Policy version <b>${esc(m.version||'current')}</b></span><span>Effective <b>${esc(m.effective||'')}</b></span><span>Governing law <b>${esc(m.governingLaw||'')}</b></span></div></div></section><section class="container ih-legal-hub"><div class="ih-legal-principles"><article><span>01</span><b>Authorized access only</b><p>Automation does not create permission you did not already have.</p></article><article><span>02</span><b>Scoped execution</b><p>Credentials, providers, costs, and external actions stay bounded and auditable.</p></article><article><span>03</span><b>Data minimization</b><p>Send connected services only what a requested operation reasonably needs.</p></article><article><span>04</span><b>Verified payment state</b><p>Paid capacity is fulfilled only after server-side confirmation of captured payment state.</p></article></div><div class="ih-legal-card-grid">${Object.entries(items).map(([slug,doc])=>`<a class="ih-legal-card" data-link href="${legalHref(slug)}"><span>${esc(doc.shortTitle||doc.title)}</span><h2>${esc(doc.title)}</h2><p>${esc(doc.summary)}</p><em>Read policy ${icon('arrow')}</em></a>`).join('')}</div><aside class="ih-legal-review"><div>${icon('shield')}<span><b>Implementation-aligned policies</b><p>These pages are versioned against current product behavior. Review them whenever payment behavior, data flows, providers, or the legal operator changes.</p></span></div><a data-link href="/legal/security">Security policy ${icon('arrow')}</a></aside></section></main>`);
}
function renderLegalDocument(slug){
  const items=legalDocs(),doc=items[slug],m=legalMeta();if(!doc)return renderLegalHub();document.title=`${doc.title} — Internet Hands`;
  const toc=(doc.sections||[]).map(s=>`<a href="#${esc(s.id)}">${esc(s.title)}</a>`).join('');
  const related=(doc.related||[]).map(k=>items[k]?`<a data-link href="${legalHref(k)}">${esc(items[k].shortTitle||items[k].title)} ${icon('arrow')}</a>`:'').join('');
  publicShell(`<main class="ih-legal-page ih-legal-doc-page"><section class="container ih-legal-doc-head"><a class="ih-legal-back" data-link href="/legal">${icon('arrow')} Legal center</a><span class="ih-legal-kicker">INTERNET HANDS / POLICY</span><h1>${esc(doc.title)}</h1><p>${esc(doc.summary)}</p><div class="ih-legal-meta"><span>Version <b>${esc(m.version||'current')}</b></span><span>Effective <b>${esc(m.effective||'')}</b></span><span>Updated <b>${esc(m.updated||'')}</b></span></div></section><section class="container ih-legal-layout">${legalSideNav(slug)}<article class="ih-legal-article"><nav class="ih-legal-toc"><b>On this page</b>${toc}</nav>${(doc.sections||[]).map(s=>`<section id="${esc(s.id)}"><h2>${esc(s.title)}</h2>${(s.blocks||[]).map(legalBlock).join('')}</section>`).join('')}<footer class="ih-legal-related"><div><span>RELATED POLICIES</span>${related}</div><p>Policy version ${esc(m.version||'current')} · Last updated ${esc(m.updated||'')}</p></footer></article></section></main>`);
}
function renderLegal(){const path=location.pathname.replace(/\/+$/,'')||'/';const alias=LEGAL_ALIASES[path];if(alias)return renderLegalDocument(alias);if(path==='/legal')return renderLegalHub();const slug=path.startsWith('/legal/')?decodeURIComponent(path.slice(7)):'';return slug?renderLegalDocument(slug):renderLegalHub()}

async function renderDashboard(){if(!await ensureMe())return;const slug=location.pathname.split('/')[2]||'overview';const routes={overview:dashOverview,playground:dashPlayground,usage:dashUsage,'api-keys':dashKeys,monitors:dashMonitors,integrations:dashIntegrations,connections:dashIntegrations,mcp:dashIntegrations,wallet:dashWallet,billing:dashBilling,settings:dashSettings};return (routes[slug]||dashOverview)();}
async function renderRoute(){clearTransientUi();window.scrollTo(0,0);const p=location.pathname;try{if(p==='/'||p==='/pricing'||p==='/status'||p.startsWith('/docs')||p.startsWith('/legal')||LEGAL_ALIASES[p])await hydrateOptionalSession();if(p.startsWith('/dashboard'))return await renderDashboard();if(p==='/verify-email')return await renderVerify();if(p==='/login')return renderAuth('login');if(p==='/signup')return renderAuth('signup');if(p==='/forgot-password')return renderRecovery();if(p==='/reset-password')return renderRecovery(true);if(p.startsWith('/legal')||LEGAL_ALIASES[p])return renderLegal();if(p.startsWith('/docs'))return renderDocs();if(p==='/pricing')return await renderPricing();if(p==='/status')return await renderStatus();return await renderHome();}catch(error){console.error(error);if(error.status===401)return go('/login',true);app.innerHTML=`<main class="fatal"><div>${brand()}<span class="eyebrow">REQUEST FAILED</span><h1>The control plane did not answer cleanly.</h1><p>${esc(error.message)}</p><button class="btn primary" onclick="location.reload()">Try again</button></div></main>`;}}
document.addEventListener('click',e=>{
  if(e.defaultPrevented)return;
  const a=e.target.closest('[data-link]');
  if(!a||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
  e.preventDefault();
  e.stopPropagation();
  const href=a.getAttribute('href');
  if(href)go(href);
});
window.addEventListener('popstate',()=>{clearTransientUi();renderRoute();});
window.addEventListener('pageshow',clearTransientUi);


// Shared by the product and telemetry renderers in this canonical runtime.
const statusDot = (tone = 'ok') => `<i class="ih-status-dot ${tone}"></i>`;
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


/* === Product experience ================================================= */
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
          <div><b>Legal</b><a data-link href="/legal/terms">Terms</a><a data-link href="/legal/privacy">Privacy</a><a data-link href="/legal/acceptable-use">Acceptable use</a><a data-link href="/legal">Legal center</a></div>
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
        <div class="ih-preflight-actions"><button class="btn primary" data-copy="${esc(brief)}">${icon('copy')} Copy MCP intent</button><a class="btn" data-link href="/dashboard/connections">Open integrations</a></div>
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
            ${events.length ? events.map((e,i)=>`<button class="ih-run-row" data-run-index="${i}"><span>${statusDot(runStatus(e.status))}</span><div><b>${esc(runLabel(e))}</b><small>${esc(e.provider||'Provider pending')} · ${esc(when(e.created_at))}</small></div><code>${esc((e.request_id||'run').slice(0,16))}</code><em>${e.latency_ms==null?'—':`${fmt(e.latency_ms)} ms`}</em>${icon('arrow')}</button>`).join('') : `<div class="ih-empty-run"><span>${icon('activity')}</span><div><b>No runs yet</b><p>Connect an agent and execute your first internet task. Its real request trace will appear here.</p></div><a class="btn" data-link href="/dashboard/connections">Connect client</a></div>`}
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
        ${events.length ? events.map((e,i)=>`<button class="ih-run-table-row" data-run-index="${i}"><span>${statusDot(runStatus(e.status))}<b>${esc(e.status||'unknown')}</b></span><span><b>${esc(runLabel(e))}</b><code>${esc((e.request_id||'—').slice(0,22))}</code></span><span>${esc(e.provider||'—')}</span><span>${fmt(e.credits_charged||0)}</span><span>${e.latency_ms==null?'—':`${fmt(e.latency_ms)} ms`}</span><span>${esc(when(e.created_at))}</span><span>${icon('arrow')}</span></button>`).join('') : `<div class="ih-empty-run large"><span>${icon('activity')}</span><div><b>Your run ledger is empty</b><p>Requests executed through your connected clients appear here automatically.</p></div><a class="btn primary" data-link href="/dashboard/connections">Connect a client</a></div>`}
      </section>`);
    $('[data-new-run-inline]')?.addEventListener('click',()=>go('/dashboard'));
    $$('[data-run-index]').forEach(b=>b.addEventListener('click',()=>openRunInspector(events[Number(b.dataset.runIndex)])));
  };

})();


/* === Extended authenticated surfaces ==================================== */
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
          <footer class="ihx-auth-foot">${icon('shield')} Encrypted session · server-side verification · auditable access <span class="ihx-auth-legal"><a data-link href="/legal/terms">Terms</a><a data-link href="/legal/privacy">Privacy</a><a data-link href="/legal/acceptable-use">Acceptable use</a></span></footer>
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
    dashboardShell('connections',`
      ${headline('CONNECTIONS','One gateway. Every client.','Connect the tools you already use without duplicating provider credentials or changing the endpoint.',`<button class="btn primary" data-copy="${esc(endpoint)}">${icon('copy')} Copy MCP endpoint</button>`)}
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

  dashPlayground = async function dashPlaygroundV2() {
    const [keyData, dashboard] = await Promise.all([api('/api/api-keys'), api('/api/dashboard')]);
    const keys=(keyData.keys||[]).filter(x=>!x.revoked_at && (!x.expires_at || new Date(x.expires_at)>new Date()));
    const account=dashboard.account||{}, available=Number(account.monthly_credits||0)+Number(account.purchased_credits||0);

    if(!keys.length){
      dashboardShell('playground',
        headline('METERED TESTING','Playground','Test Internet Hands against the real usage ledger. An active API key is required before execution.','<a class="btn" data-link href="/dashboard/usage">'+icon('activity')+' View runs</a>') +
        '<section class="ihp-key ihp-key-required"><div class="ihp-key-copy">'+icon('key')+'<div><small>API KEY REQUIRED</small><h2>Create an API key before using Playground.</h2><p>Playground does not create special credentials. Create a normal scoped key in API Keys, then return here to run metered tests.</p></div></div><div class="ihp-key-actions"><span class="ihx-state idle">'+dot('warn')+' No active API keys</span><a class="btn primary" data-link href="/dashboard/api-keys">'+icon('key')+' Create API key</a></div></section>' +
        '<section class="ihp-locked"><span>'+icon('shield')+'</span><div><small>PLAYGROUND LOCKED</small><h3>Execution is unavailable until your account has an active API key.</h3><p>Keys define scopes, isolate clients and attach usage to a revocable credential.</p></div></section>');
      return;
    }

    const keyOptions=keys.map((key,index)=>'<option value="'+esc(key.id)+'" '+(index===0?'selected':'')+'>'+esc(key.name)+' · '+esc(key.prefix)+'… · '+esc(key.environment)+'</option>').join('');
    const html =
      headline('METERED TESTING','Playground','Run the real crawler through an active API key. Every test spends credits and appears in Runs.','<a class="btn" data-link href="/dashboard/usage">'+icon('activity')+' View runs</a>') +
      '<section class="ihp-key">' +
        '<div class="ihp-key-copy">'+icon('key')+'<div><small>STEP 01 / API KEY</small><h2>Active API key detected.</h2><p>Choose which normal API key should own this Playground run. No raw secret needs to be pasted here.</p></div></div>' +
        '<div class="ihp-key-actions"><span class="ihx-state on">'+dot('ok')+' '+fmt(keys.length)+' active key'+(keys.length===1?'':'s')+'</span><a class="btn" data-link href="/dashboard/api-keys">Manage keys</a></div>' +
        '<label class="ihp-key-select">Use API key<select id="ihp-key-id">'+keyOptions+'</select><small>Usage and last-used activity are attributed to this key.</small></label>' +
      '</section>' +
      '<section class="ihp-main">' +
        '<form id="ihp-form" class="ihp-form">' +
          '<header><div><small>STEP 02 / CRAWL</small><h2>Web crawl test</h2><p>Public HTTP(S) only · robots respected · SSRF protected · bounded fan-out.</p></div><span class="ihp-cost">2 credits / run</span></header>' +
          '<label>Target URL<input id="ihp-url" type="url" required placeholder="https://example.com"></label>' +
          '<div class="ihp-budgets"><label>Pages<input id="ihp-pages" type="number" min="1" max="50" value="12"></label><label>Depth<input id="ihp-depth" type="number" min="0" max="4" value="2"></label><label>Concurrency<input id="ihp-concurrency" type="number" min="1" max="6" value="4"></label><label>Seconds<input id="ihp-seconds" type="number" min="5" max="45" value="30"></label></div>' +
          '<div class="ihp-paths"><label>Include paths <small>comma-separated globs</small><input id="ihp-include" placeholder="/docs/*, /blog/*"></label><label>Exclude paths <small>comma-separated globs</small><input id="ihp-exclude" placeholder="/private/*, /account/*"></label></div>' +
          '<div class="ihp-options"><label><input id="ihp-subdomains" type="checkbox"> Include subdomains</label><label><input id="ihp-query" type="checkbox"> Preserve query parameters</label><span>'+icon('shield')+' robots.txt always respected</span></div>' +
          '<div class="ihp-presets"><span>Quick budget</span><button type="button" data-preset="5,1,2,15">5 pages</button><button type="button" data-preset="15,2,4,30">15 pages</button><button type="button" data-preset="30,3,5,40">30 pages</button></div>' +
          '<button class="btn primary large ihp-run" type="submit">'+icon('activity')+' Run metered crawl</button>' +
          '<p class="ihp-note">Available balance: <b>'+fmt(available)+'</b> credits. This test is attributed to the selected API key.</p>' +
        '</form>' +
        '<aside class="ihp-boundary"><small>EXECUTION BOUNDARY</small><h3>Real test. Real accounting.</h3><div>'+icon('shield')+'<p><b>Public targets only</b>Private, loopback, link-local and reserved addresses are rejected.</p></div><div>'+icon('monitor')+'<p><b>Bounded crawling</b>Pages, depth, concurrency and time stop runaway jobs.</p></div><div>'+icon('activity')+'<p><b>Usage-visible</b>Request ID, status, latency and credits appear in Runs.</p></div><div>'+icon('key')+'<p><b>Normal API keys</b>Playground uses the same revocable keys created in API Keys.</p></div></aside>' +
      '</section><section id="ihp-result" class="ihp-result" hidden></section>';
    dashboardShell('playground', html);

    $$('[data-preset]').forEach(button=>button.addEventListener('click',()=>{const values=button.dataset.preset.split(',');$('#ihp-pages').value=values[0];$('#ihp-depth').value=values[1];$('#ihp-concurrency').value=values[2];$('#ihp-seconds').value=values[3];}));
    const patterns=value=>String(value||'').split(',').map(x=>x.trim()).filter(Boolean);
    $('#ihp-form')?.addEventListener('submit',async e=>{
      e.preventDefault();
      const button=$('.ihp-run',e.currentTarget), result=$('#ihp-result');
      busy(button,true,'Crawling…');result.hidden=false;result.innerHTML='<div class="ihp-running">'+icon('activity')+'<span><b>Crawl in progress</b><small>Applying your page, depth, concurrency and time budgets…</small></span></div>';
      const body={api_key_id:$('#ihp-key-id').value,operation:'crawl',url:$('#ihp-url').value.trim(),max_pages:Number($('#ihp-pages').value),max_depth:Number($('#ihp-depth').value),concurrency:Number($('#ihp-concurrency').value),max_seconds:Number($('#ihp-seconds').value),include_paths:patterns($('#ihp-include').value),exclude_paths:patterns($('#ihp-exclude').value),include_subdomains:$('#ihp-subdomains').checked,preserve_query:$('#ihp-query').checked};
      try{
        const response=await fetch('/api/playground/run',{method:'POST',credentials:'include',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        let data={};try{data=await response.json();}catch{} if(!response.ok){const detail=data?.detail;throw new Error(typeof detail==='string'?detail:detail?.message||data?.error||('Request failed ('+response.status+')'));}
        const summary=data.summary||{}, pages=data.result?.pages||[];
        const rows=pages.map(page=>'<div class="ihp-row"><span class="ihx-state '+(page.error?'idle':'on')+'">'+dot(page.error?'warn':'ok')+' '+(page.error?'Error':esc(page.status_code||'OK'))+'</span><span>'+fmt(page.depth)+'</span><span><b>'+esc(page.url)+'</b>'+(page.error?'<small>'+esc(page.error)+'</small>':'')+'</span><span>'+fmt(page.links_found)+'</span><span>'+(page.elapsed_ms==null?'—':fmt(Math.round(page.elapsed_ms))+' ms')+'</span></div>').join('');
        result.innerHTML='<header class="ihp-result-head"><div><span>'+dot()+' CRAWL COMPLETE</span><h2>'+esc(body.url)+'</h2><p>Request <code>'+esc(data.request_id)+'</code> · '+fmt(data.usage?.credits_charged||0)+' credits charged</p></div><a class="btn" data-link href="/dashboard/usage">Open in Runs '+icon('arrow')+'</a></header><div class="ihp-stats"><div><small>PAGES</small><b>'+fmt(summary.pages)+'</b></div><div><small>SUCCESS</small><b>'+fmt(summary.successful)+'</b></div><div><small>DISCOVERED</small><b>'+fmt(summary.discovered_urls)+'</b></div><div><small>LINKS</small><b>'+fmt(summary.links_found)+'</b></div><div><small>DURATION</small><b>'+fmt(summary.duration_ms)+'<em> ms</em></b></div></div><div class="ihp-table"><div class="ihp-table-head"><span>STATE</span><span>DEPTH</span><span>URL</span><span>LINKS</span><span>TIME</span></div>'+(rows||'<div class="notice">No pages returned.</div>')+'</div><details class="ihp-raw"><summary>Raw crawl response</summary><pre><code>'+esc(JSON.stringify(data,null,2))+'</code></pre></details>';
        bindCommon();result.scrollIntoView({behavior:'smooth',block:'start'});
      }catch(error){result.innerHTML='<div class="ihp-error">'+icon('activity')+'<span><b>Crawl failed</b><p>'+esc(error.message)+'</p></span></div>';toast(error.message,'error');}
      finally{busy(button,false);}
    });
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
    dashboardShell('settings',`
      ${headline('ACCOUNT','Settings & security','Identity, login protection and active sessions presented as one security surface.')}
      <section class="ihx-settings-grid">
        <article class="ihx-profile-panel"><header><div><span>PROFILE</span><h2>Workspace identity</h2></div><span class="ihx-state on">${dot()} Verified</span></header><form id="profile-form" class="form-stack"><label>Email<input value="${esc(u.email)}" disabled></label><label>Display name<input name="display_name" value="${esc(u.display_name||'')}" maxlength="80" required></label><div class="ihx-linked-account">${clientMark('github','GitHub')}<span><b>GitHub</b><small>${u.github_connected?'Connected to this identity':'Not connected'}</small></span><em>${u.github_connected?'Linked':'Optional'}</em></div><button class="btn">Save profile</button></form></article>
        <article class="ihx-security-panel"><header><div><span>SECURITY POSTURE</span><h2>Protection status</h2></div><span class="ihx-state ${s.two_factor_enabled?'on':'idle'}">${dot(s.two_factor_enabled?'ok':'warn')} ${s.two_factor_enabled?'2FA enabled':s.two_factor_available?'2FA available':'Server configuration required'}</span></header><div class="ihx-security-rail"><div>${icon('check')}<span><b>Email verification</b><small>Privileged actions unlocked</small></span><em>On</em></div><div>${icon('shield')}<span><b>Authenticator 2FA</b><small>${s.two_factor_enabled?'Required after primary sign-in':'Add a second factor to reach full protection'}</small></span><button class="btn ${s.two_factor_enabled?'danger':'primary'} small" id="toggle-2fa">${s.two_factor_enabled?'Disable':'Set up'}</button></div>${s.two_factor_enabled?`<div>${icon('activity')}<span><b>Recovery codes</b><small>One-use emergency access</small></span><button class="btn small" id="regen">Regenerate</button></div>`:''}</div></article>
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

})();


/* === Command workspace shell ============================================ */
/* Internet Hands Command OS
 * Final visual shell. Keeps all existing route renderers and backend handlers,
 * but replaces the dashboard chrome with an operations-first workspace.
 */
(() => {
  Object.assign(paths, {
    terminal: '<path d="M4 5h16v14H4z"/><path d="m7 9 3 3-3 3m5 0h5"/>',
    billing: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M7 15h4"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    chevron: '<path d="m9 6 6 6-6 6"/>',
    external: '<path d="M14 3h7v7M10 14 21 3"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>'
  });

  const statusDot = () => '<i class="cos-live-dot" aria-hidden="true"></i>';
  const hrefFor = slug => `/dashboard${slug === 'overview' ? '' : `/${slug}`}`;

  brand = function commandBrand() {
    return `<a class="brand ih-brand cos-brand ih-logo-only" data-link href="/" aria-label="Internet Hands home">
      <img class="ih-brand-art" src="/assets/internet-hands-logo.webp" alt="Internet Hands">
    </a>`;
  };

  const nav = [
    ['Build', [
      ['overview','terminal','Overview'],
      ['playground','activity','Playground'],
      ['api-keys','key','API Keys']
    ]],
    ['Observe', [
      ['usage','activity','Runs'],
      ['monitors','monitor','Monitors']
    ]],
    ['Connect', [
      ['connections','plug','Connections']
    ]],
    ['Manage', [
      ['wallet','wallet','Credits'],
      ['billing','billing','Billing & Plans'],
      ['settings','settings','Settings & Security']
    ]]
  ];

  dashboardShell = function commandOsShell(active, content) {
    const u = state.me?.user || {};
    const current = nav.flatMap(x => x[1]).find(x => x[0] === active);
    const title = current?.[2] || 'Overview';
    const initials = esc((u.display_name || u.email || 'I')[0].toUpperCase());

    app.innerHTML = `<div class="cos-app">
      <aside class="cos-sidebar ih-sidebar sidebar">
        <div class="cos-sidebar-head">
          <div class="cos-sidebar-brand">${brand()}</div>
          <button class="cos-sidebar-close" type="button" data-sidebar-close aria-label="Close navigation"><span aria-hidden="true">×</span></button>
        </div>

        <a class="cos-launch ${active === 'overview' ? 'active' : ''}" data-link href="/dashboard">
          <span>${icon('terminal')}</span><b>New run</b><kbd>⌘ K</kbd>
        </a>

        <nav class="cos-nav">
          ${nav.map(([group, items]) => `<div class="cos-nav-group">
            <span>${group}</span>
            ${items.map(([slug, ico, label]) => `<a class="${slug === active ? 'active' : ''}" data-link href="${hrefFor(slug)}">
              <span class="cos-nav-icon">${icon(ico)}</span><b>${label}</b>${slug === active ? '<i></i>' : ''}
            </a>`).join('')}
          </div>`).join('')}
        </nav>

        <div class="cos-sidebar-bottom">
          <a class="cos-gateway" data-link href="/status"><span>${statusDot()}</span><div><b>Gateway online</b><small>All systems operational</small></div>${icon('chevron')}</a>
          <div class="cos-sidebar-links"><a data-link href="/docs">${icon('docs')} Docs</a><a href="https://github.com/sphangcho203-afk/Web-Scrapping-CLI" target="_blank" rel="noreferrer">${icon('external')} GitHub</a></div>
        </div>
      </aside>

      <section class="cos-workspace workspace ih-workspace">
        <header class="cos-topbar topbar ih-topbar">
          <div class="cos-topbar-left">
            <button class="cos-mobile-menu icon-btn" data-sidebar-toggle aria-label="Open navigation">${icon('menu')}</button>
            <div class="cos-breadcrumb"><span>Internet Hands</span><i>/</i><b>${esc(title)}</b></div>
          </div>
          <div class="cos-topbar-right">
            ${active === 'overview' ? '' : `<a class="cos-command-cta" data-link href="/dashboard">${icon('terminal')}<span>Run command</span><kbd>⌘ K</kbd></a>`}
            <a class="cos-docs-link" data-link href="/docs">Docs</a>
            <button class="cos-account" type="button" data-account-toggle popovertarget="ih-account-menu" popovertargetaction="toggle" aria-expanded="false"><i>${initials}</i><span><b>${esc(u.display_name || 'Account')}</b><small>${esc(u.email || '')}</small></span>${icon('chevron')}</button>
          </div>
        </header>

        <div class="cos-account-menu" id="ih-account-menu" data-account-menu popover="auto">
          <div><span class="cos-account-avatar">${initials}</span><span><b>${esc(u.display_name || 'Internet Hands')}</b><small>${esc(u.email || '')}</small></span></div>
          <a data-link href="/dashboard/settings">${icon('settings')} Settings & Security</a>
          <a data-link href="/dashboard/billing">${icon('billing')} Billing & Plans</a>
          <a data-link href="/dashboard/wallet">${icon('wallet')} Credits</a>
          <a data-link href="/docs">${icon('docs')} Documentation</a>
          <button id="account-logout">Sign out</button>
        </div>

        <main class="cos-content content ih-content"><div class="ih-page-shell ih-route-${esc(active)}" data-dashboard-route="${esc(active)}">${content}</div></main>
      </section>

      <nav class="cos-mobile-bottom ih-mobile-bottom mobile-bottom">
        ${[
          ['overview','terminal','Overview'],
          ['playground','activity','Playground'],
          ['usage','activity','Runs'],
          ['connections','plug','Connections'],
          ['more','more','More']
        ].map(([slug, ico, label]) => `<a ${slug === 'more' ? 'data-more' : 'data-link'} href="${slug === 'more' ? '#' : hrefFor(slug)}" class="${slug === active ? 'active' : ''}">${icon(ico)}<span>${label}</span></a>`).join('')}
      </nav>

      <div class="cos-more-sheet more-sheet" data-more-sheet aria-label="More navigation">
        <div class="cos-sheet-handle"></div>
        <div class="cos-sheet-title"><b>More</b><small>Workspace navigation</small></div>
        <span class="cos-sheet-label">Build & observe</span>
        <a data-link href="/dashboard/api-keys">${icon('key')} API Keys</a>
        <a data-link href="/dashboard/monitors">${icon('monitor')} Monitors</a>
        <span class="cos-sheet-label">Account & product</span>
        <a data-link href="/dashboard/wallet">${icon('wallet')} Credits</a>
        <a data-link href="/dashboard/billing">${icon('billing')} Billing & Plans</a>
        <a data-link href="/dashboard/settings">${icon('settings')} Settings & Security</a>
        <a data-link href="/docs">${icon('docs')} Documentation</a>
        <a data-link href="/status">${icon('activity')} System Status</a>
        <button id="mobile-logout">Sign out</button>
      </div>
      <div class="cos-sheet-backdrop sheet-backdrop" data-sheet-backdrop></div>
    </div>`;

    bindCommon();

    const sidebar = $('.cos-sidebar');
    const sheet = $('[data-more-sheet]');
    const backdrop = $('[data-sheet-backdrop]');
    const accountToggle = $('[data-account-toggle]');
    const accountMenu = $('[data-account-menu]');
    const sidebarToggle = $('[data-sidebar-toggle]');
    const moreToggle = $('[data-more]');
    const mobileShell = () => window.matchMedia('(max-width: 900px)').matches;

    const nativeAccountPopover = Boolean(accountMenu && typeof accountMenu.showPopover === 'function' && accountMenu.hasAttribute('popover'));
    const accountOpen = () => Boolean(accountMenu && (nativeAccountPopover ? accountMenu.matches(':popover-open') : !accountMenu.hasAttribute('hidden')));
    const syncOverlayState = () => {
      const modalOpen = Boolean(sidebar?.classList.contains('open') || sheet?.classList.contains('open') || (!nativeAccountPopover && mobileShell() && accountOpen()));
      backdrop?.classList.toggle('open', modalOpen);
      document.documentElement.classList.toggle('ih-overlay-open', modalOpen);
      sidebarToggle?.setAttribute('aria-expanded', String(Boolean(sidebar?.classList.contains('open'))));
      moreToggle?.setAttribute('aria-expanded', String(Boolean(sheet?.classList.contains('open'))));
    };
    const closeAccount = () => {
      if (!accountMenu) return;
      if (nativeAccountPopover) {
        try { if (accountMenu.matches(':popover-open')) accountMenu.hidePopover(); } catch {}
      } else {
        accountMenu.setAttribute('hidden','');
      }
      accountToggle?.setAttribute('aria-expanded','false');
    };
    const closeOverlays = () => {
      sidebar?.classList.remove('open');
      sheet?.classList.remove('open');
      closeAccount();
      syncOverlayState();
    };

    sidebarToggle?.setAttribute('aria-expanded','false');
    moreToggle?.setAttribute('aria-expanded','false');
    $('[data-sidebar-close]')?.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      closeOverlays();
    });

    sidebarToggle?.addEventListener('click', () => {
      const opening = !sidebar?.classList.contains('open');
      sheet?.classList.remove('open');
      closeAccount();
      sidebar?.classList.toggle('open', opening);
      syncOverlayState();
    });

    moreToggle?.addEventListener('click', e => {
      e.preventDefault();
      const opening = !sheet?.classList.contains('open');
      sidebar?.classList.remove('open');
      closeAccount();
      sheet?.classList.toggle('open', opening);
      syncOverlayState();
    });

    if (nativeAccountPopover) {
      accountMenu?.addEventListener('toggle', () => {
        const open = accountMenu.matches(':popover-open');
        accountToggle?.setAttribute('aria-expanded', String(open));
        sidebar?.classList.remove('open');
        sheet?.classList.remove('open');
        syncOverlayState();
      });
    } else {
      accountToggle?.addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        if (!accountMenu) return;
        const opening = accountMenu.hasAttribute('hidden');
        sidebar?.classList.remove('open');
        sheet?.classList.remove('open');
        if (opening) accountMenu.removeAttribute('hidden'); else accountMenu.setAttribute('hidden','');
        accountToggle?.setAttribute('aria-expanded', String(opening));
        syncOverlayState();
      });
    }

    const blockOverlayPointer = e => {
      e.preventDefault();
      e.stopPropagation();
    };
    const dismissOverlayPointer = e => {
      e.preventDefault();
      e.stopPropagation();
      closeOverlays();
    };
    backdrop?.addEventListener('pointerdown', blockOverlayPointer);
    backdrop?.addEventListener('pointerup', dismissOverlayPointer);
    backdrop?.addEventListener('click', dismissOverlayPointer);

    if (window.__ihAccountCloser) document.removeEventListener('click', window.__ihAccountCloser);
    window.__ihAccountCloser = e => {
      if (nativeAccountPopover || !accountOpen()) return;
      if (!accountMenu.contains(e.target) && !accountToggle?.contains(e.target)) {
        closeAccount();
        syncOverlayState();
      }
    };
    document.addEventListener('click', window.__ihAccountCloser);

    [sidebar,sheet,accountMenu].filter(Boolean).forEach(region=>{
      region.addEventListener('click',e=>{
        const link=e.target.closest('[data-link]');
        if(!link)return;
        clearTransientUi();
      });
    });

    if (window.__ihShellResize) window.removeEventListener('resize', window.__ihShellResize);
    window.__ihShellResize = () => {
      if (!mobileShell()) closeOverlays();
    };
    window.addEventListener('resize', window.__ihShellResize);

    if (window.__ihShellEscape) document.removeEventListener('keydown', window.__ihShellEscape);
    window.__ihShellEscape = e => { if (e.key === 'Escape') closeOverlays(); };
    document.addEventListener('keydown', window.__ihShellEscape);

    const logout = async () => {
      await api('/api/auth/logout', { method:'POST' });
      state.me = null;
      go('/login');
    };
    $('#account-logout')?.addEventListener('click', logout);
    $('#mobile-logout')?.addEventListener('click', logout);

    if (window.__ihCommandShortcut) document.removeEventListener('keydown', window.__ihCommandShortcut);
    window.__ihCommandShortcut = e => {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== 'k') return;
      e.preventDefault();
      if (location.pathname !== '/dashboard') return go('/dashboard');
      $('#ih-run-input')?.focus();
    };
    document.addEventListener('keydown', window.__ihCommandShortcut);
  };

  // Initial render happens once, after every canonical renderer and shell is installed.
  renderRoute();
})();
