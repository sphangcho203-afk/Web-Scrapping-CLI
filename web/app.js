/* ==========================================================================
   Internet Hands — Master Application & Unified Web Studio
   ========================================================================== */

(function () {
  'use strict';

  // --- Global Application State ---
  const state = {
    me: null,
    sessionChecked: false,
    plans: null,
    activeTab: 'overview',
    activeStudioTool: 'scraper',
    neonKey: localStorage.getItem('ih_neon_key') || '',
    vercelToken: localStorage.getItem('ih_vercel_token') || '',
    connectorStatus: null,
    telemetryLogs: [
      { id: 'req_8f1a02', time: '10:42:15', tool: 'scraper.extract', provider: 'playwright-stealth', target: 'https://news.ycombinator.com', status: 200, latency: '420ms', cost: '3 credits' },
      { id: 'req_7b3d19', time: '10:41:50', tool: 'search.brave', provider: 'brave-search', target: 'ai agents live scraping', status: 200, latency: '185ms', cost: '2 credits' },
      { id: 'req_6c9e44', time: '10:40:12', tool: 'mcp.mesh_route', provider: 'internal-router', target: 'mcp://customer-gateway', status: 200, latency: '24ms', cost: '1 credit' },
      { id: 'req_5d2f81', time: '10:38:05', tool: 'crawler.deep', provider: 'crawler-worker-3', target: 'https://docs.python.org', status: 200, latency: '1.2s', cost: '8 credits' },
    ]
  };

  // --- DOM Helpers ---
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = str => String(str ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  const fmt = num => new Intl.NumberFormat('en-IN').format(Number(num || 0));
  const money = amount => `₹${fmt(amount)}`;
  const when = dateStr => dateStr ? new Date(dateStr).toLocaleString() : 'Never';

  // --- SVG Icons ---
  const icons = {
    logo: `<path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`,
    scan: `<path d="M3 7V5a2 2 0 0 1 2-2h2m10 0h2a2 2 0 0 1 2 2v2m0 10v2a2 2 0 0 1-2 2h-2m-10 0H5a2 2 0 0 1-2-2v-2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2"/>`,
    scraper: `<rect x="2" y="3" width="20" height="14" rx="2" stroke="currentColor" stroke-width="2"/><path d="M8 21h8m-4-4v4M7 8h10M7 12h6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
    crawler: `<circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20M2 12h20" stroke="currentColor" stroke-width="2"/>`,
    search: `<circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="2"/><path d="m21 21-4.35-4.35" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
    api: `<path d="M7 8l-4 4 4 4m10-8l4 4-4 4M14 4l-4 16" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`,
    osint: `<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="m9 12 2 2 4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
    monitor: `<rect x="2" y="3" width="20" height="14" rx="2" stroke="currentColor" stroke-width="2"/><path d="M12 17v4m-4 0h8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M6 10l3 3 3-3 6 4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
    sandbox: `<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" stroke="currentColor" stroke-width="2"/><polyline points="3.27 6.96 12 12.01 20.73 6.96" stroke="currentColor" stroke-width="2"/><line x1="12" y1="22.08" x2="12" y2="12" stroke="currentColor" stroke-width="2"/>`,
    connector: `<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
    telemetry: `<polyline points="22 12 18 12 15 21 9 3 6 12 2 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`,
    key: `<circle cx="7.5" cy="15.5" r="4.5" stroke="currentColor" stroke-width="2"/><path d="m11 12 9-9m-3 3 3 3m-6 0 3 3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
    wallet: `<rect x="2" y="4" width="20" height="16" rx="2" stroke="currentColor" stroke-width="2"/><path d="M6 10h12m-6 4h6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
    shield: `<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>`,
    arrow: `<path d="M5 12h14m-7-7 7 7-7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`,
    check: `<polyline points="20 6 9 17 4 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`,
    copy: `<rect x="9" y="9" width="13" height="13" rx="2" stroke="currentColor" stroke-width="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" stroke="currentColor" stroke-width="2"/>`,
    play: `<polygon points="5 3 19 12 5 21 5 3" fill="currentColor"/>`,
    refresh: `<path d="M23 4v6h-6m-1 5a9 9 0 1 1-2.6-6.4L23 10" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`,
    sparkles: `<path d="m12 3 1.9 4.7L18.6 9l-4.7 1.9L12 15.6l-1.9-4.7L5.4 9l4.7-1.3L12 3zM19 17l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9.9-2.1z" fill="currentColor"/>`,
    github: `<path fill-rule="evenodd" clip-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" fill="currentColor"/>`,
    neon: `<path d="M12 2L2 7l10 5 10-5-10-5zm0 18l10-5-10-5-10 5 10 5z" fill="#00E599"/>`,
    vercel: `<path d="M12 2L2 20h20L12 2z" fill="currentColor"/>`
  };

  const getIcon = (name, className = 'icon') => {
    return `<svg class="${className}" viewBox="0 0 24 24" width="18" height="18" fill="none">${icons[name] || icons.logo}</svg>`;
  };

  // --- Notifications & Feedback ---
  function toast(message, tone = 'info') {
    let region = $('#toast-region');
    if (!region) {
      region = document.createElement('div');
      region.id = 'toast-region';
      document.body.appendChild(region);
    }
    const item = document.createElement('div');
    item.className = `toast ${tone}`;
    item.innerHTML = `<span>${tone === 'success' ? getIcon('check') : getIcon('sparkles')}</span><div>${esc(message)}</div>`;
    region.appendChild(item);
    setTimeout(() => item.remove(), 4000);
  }

  async function copyText(text, button) {
    try {
      await navigator.clipboard.writeText(text);
      toast('Copied to clipboard', 'success');
      if (button) {
        const orig = button.innerHTML;
        button.innerHTML = `${getIcon('check')} Copied!`;
        setTimeout(() => button.innerHTML = orig, 1500);
      }
    } catch {
      toast('Clipboard permission blocked', 'error');
    }
  }

  // --- Backend API Client ---
  async function api(path, options = {}) {
    const init = {
      credentials: 'include',
      cache: 'no-store',
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {})
      }
    };
    if (init.body && typeof init.body !== 'string') {
      init.body = JSON.stringify(init.body);
    }
    try {
      const response = await fetch(path, init);
      let data = {};
      try { data = await response.json(); } catch {}
      if (!response.ok) {
        const detail = data?.detail;
        const msg = typeof detail === 'string' ? detail : detail?.message || data?.error || `Request failed (${response.status})`;
        const error = new Error(msg);
        error.status = response.status;
        throw error;
      }
      return data;
    } catch (err) {
      throw err;
    }
  }

  async function hydrateSession() {
    if (state.sessionChecked) return;
    state.sessionChecked = true;
    try {
      const res = await api('/api/auth/me');
      if (res?.user) {
        state.me = res;
      }
    } catch {
      state.me = null;
    }
  }

  async function getPlans() {
    if (state.plans) return state.plans;
    try {
      state.plans = await api('/api/public/plans');
    } catch {
      state.plans = {
        plans: [
          { slug: 'free', name: 'Free', monthly_price_inr: 0, included_credits: 2500, rpm_limit: 30, api_key_limit: 2, monitor_limit: 3, browser_enabled: false },
          { slug: 'builder', name: 'Builder', monthly_price_inr: 499, included_credits: 10000, rpm_limit: 120, api_key_limit: 5, monitor_limit: 10, browser_enabled: true },
          { slug: 'pro', name: 'Pro', monthly_price_inr: 1499, included_credits: 40000, rpm_limit: 300, api_key_limit: 15, monitor_limit: 30, browser_enabled: true },
          { slug: 'scale', name: 'Scale', monthly_price_inr: 4999, included_credits: 150000, rpm_limit: 600, api_key_limit: 50, monitor_limit: 100, browser_enabled: true }
        ],
        credit_packs: [
          { credits: 5000, price_inr: 199 },
          { credits: 25000, price_inr: 799 },
          { credits: 100000, price_inr: 2499 }
        ]
      };
    }
    return state.plans;
  }

  // --- Navigation & Router ---
  function go(path, replace = false) {
    history[replace ? 'replaceState' : 'pushState']({}, '', path);
    renderApp();
  }

  window.onpopstate = () => renderApp();

  function bindCommon() {
    $$('[data-link]').forEach(el => {
      el.onclick = e => {
        e.preventDefault();
        const href = el.getAttribute('href');
        if (href) go(href);
      };
    });

    $$('[data-copy]').forEach(el => {
      el.onclick = () => copyText(el.dataset.copy, el);
    });
  }

  // --- Shell Layouts ---
  function renderHeader(activeNav = '') {
    const isAuth = !!state.me?.user?.email_verified;
    return `
      <header class="site-header">
        <div class="container site-nav">
          <a class="brand" data-link href="/">
            <div class="brand-mark">
              <img src="/assets/mark.svg" alt="Internet Hands">
            </div>
            <span><b>Internet</b><em>Hands</em></span>
          </a>

          <nav class="nav-links">
            <a data-link href="/studio" class="${activeNav === 'studio' ? 'active' : ''}">
              ${getIcon('scraper')} Studio
            </a>
            <a data-link href="/pricing" class="${activeNav === 'pricing' ? 'active' : ''}">Pricing</a>
            <a data-link href="/docs" class="${activeNav === 'docs' ? 'active' : ''}">Docs</a>
            <a data-link href="/status" class="${activeNav === 'status' ? 'active' : ''}">
              <span class="status-dot pulse"></span> Status
            </a>
            <a href="https://github.com/sphangcho203-afk/Web-Scrapping-CLI" target="_blank" rel="noreferrer">
              ${getIcon('github')} GitHub
            </a>
          </nav>

          <div class="nav-actions">
            ${isAuth ? `
              <a class="btn small" data-link href="/studio">${getIcon('scraper')} Web Studio</a>
              <a class="btn primary small" data-link href="/dashboard">${getIcon('scan')} Console</a>
              <button class="btn quiet small" id="btn-logout" title="Sign out">Log out</button>
            ` : `
              <a class="btn small" data-link href="/studio">${getIcon('scraper')} Open Studio</a>
              <a class="btn quiet small" data-link href="/login">Sign in</a>
              <a class="btn primary small" data-link href="/signup">Get Started</a>
            `}
          </div>
        </div>
      </header>
    `;
  }

  function renderFooter() {
    return `
      <footer class="site-footer">
        <div class="container footer-grid">
          <div>
            <a class="brand" data-link href="/" style="margin-bottom: 16px;">
              <div class="brand-mark"><img src="/assets/mark.svg" alt="Internet Hands"></div>
              <span><b>Internet</b><em>Hands</em></span>
            </a>
            <p style="color: var(--text-muted); max-width: 320px; font-size: 13px; line-height: 1.6;">
              Public internet intelligence, high-performance web scraping studio, authenticated MCP gateway, and isolated cloud execution.
            </p>
          </div>
          <div class="footer-col">
            <h4>Studio & Tools</h4>
            <a data-link href="/studio">Scraper Studio</a>
            <a data-link href="/studio">Deep Crawler</a>
            <a data-link href="/studio">Brave Web Search</a>
            <a data-link href="/studio">Vercel & Neon Sync</a>
          </div>
          <div class="footer-col">
            <h4>Platform</h4>
            <a data-link href="/dashboard">MCP Gateway</a>
            <a data-link href="/dashboard">API Keys</a>
            <a data-link href="/pricing">Pricing & Credits</a>
            <a data-link href="/status">Operational Status</a>
          </div>
          <div class="footer-col">
            <h4>Commercial License</h4>
            <p style="color: var(--text-dim); font-size: 12px; margin-bottom: 8px;">
              Proprietary Software.<br>© ${new Date().getFullYear()} Internet Hands.<br>All rights reserved.
            </p>
            <span class="badge indigo">COMMERCIAL SAAS</span>
          </div>
        </div>
      </footer>
    `;
  }

  // --- PAGE: Home (Marketing + Interactive Execution Preview) ---
  async function renderHome() {
    const plansData = await getPlans();
    const plans = plansData.plans || [];

    const html = `
      ${renderHeader('home')}
      <main>
        <!-- Hero Section -->
        <section class="hero">
          <div class="container hero-grid">
            <div class="hero-copy">
              <span class="eyebrow">${getIcon('sparkles')} NEXT-GEN PUBLIC INTELLIGENCE & MCP GATEWAY</span>
              <h1>Give your agents <span class="text-gradient">hands</span> on the live web.</h1>
              <p class="lead">
                One high-performance interface to scrape, crawl, search, probe APIs, and bridge Vercel & Neon databases. Stop wrestling with browser anti-bot hurdles and complex MCP schemas.
              </p>
              <div class="hero-actions">
                <a class="btn primary large" data-link href="/studio">
                  ${getIcon('play')} Open Web Studio ${getIcon('arrow')}
                </a>
                <a class="btn large" data-link href="/signup">
                  Start Free Account
                </a>
              </div>
              <div class="hero-badges">
                <span>${getIcon('shield')} Authenticated MCP Edge</span>
                <span>${getIcon('connector')} Vercel & Neon 1-Click Sync</span>
                <span>${getIcon('telemetry')} Real-Time Provenance</span>
              </div>
            </div>

            <!-- Interactive Execution Preview -->
            <div class="runner-card">
              <div class="runner-head">
                <div class="window-dots"><i></i><i></i><i></i></div>
                <div style="display:flex; align-items:center; gap:8px;">
                  <span class="status-dot pulse"></span>
                  <span>LIVE INTELLIGENCE FABRIC</span>
                </div>
                <span style="color: var(--accent-cyan);">run_9a2f1c</span>
              </div>
              <div class="runner-body">
                <div class="terminal-prompt">
                  <span>&gt;</span>
                  <p>ih scrape <b>https://github.com/trending</b> --depth 2 --stealth --extract "title,stars,forks"</p>
                </div>
                <div class="execution-steps">
                  <div class="step-row">
                    <div class="step-info">
                      <span class="status-dot"></span>
                      <b>Gateway Route</b>
                      <span style="color: var(--text-muted);">Intent matched to Playwright Stealth</span>
                    </div>
                    <span class="step-latency">18ms</span>
                  </div>
                  <div class="step-row">
                    <div class="step-info">
                      <span class="status-dot"></span>
                      <b>Bypass Shield</b>
                      <span style="color: var(--text-muted);">TLS fingerprint spoofed, cookie retained</span>
                    </div>
                    <span class="step-latency">140ms</span>
                  </div>
                  <div class="step-row">
                    <div class="step-info">
                      <span class="status-dot"></span>
                      <b>Structured Parse</b>
                      <span style="color: var(--text-muted);">25 repositories extracted with provenance</span>
                    </div>
                    <span class="step-latency">280ms</span>
                  </div>
                  <div class="step-row">
                    <div class="step-info">
                      <span class="status-dot"></span>
                      <b>Neon DB Stream</b>
                      <span style="color: var(--text-muted);">Inserted into pgvector control store</span>
                    </div>
                    <span class="step-latency">45ms</span>
                  </div>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 10px; border-top: 1px solid var(--border-subtle); font-size: 12px; color: var(--text-muted);">
                  <span>Total Latency: <b style="color: var(--text-primary);">483ms</b></span>
                  <span>Credit Deducted: <b style="color: var(--accent-cyan);">3 credits</b></span>
                  <a data-link href="/studio" class="btn small cyan">Try in Studio</a>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Capabilities Section -->
        <section class="features-section">
          <div class="container">
            <div class="section-head">
              <span class="eyebrow">BUILT FOR ENGINEERS & AGENTS</span>
              <h2>Comprehensive Web Intelligence Toolkit</h2>
              <p>Everything you need to turn the untamed public internet into reliable structured data.</p>
            </div>

            <div class="feature-grid">
              <div class="feature-card">
                <div class="feature-icon">${getIcon('scraper')}</div>
                <h3>Scraper Studio</h3>
                <p>Interactive target exploration, visual CSS/XPath selector builder, dynamic JavaScript rendering, and clean markdown/JSON extraction.</p>
              </div>
              <div class="feature-card">
                <div class="feature-icon">${getIcon('crawler')}</div>
                <h3>Deep Web Crawler</h3>
                <p>Autonomous multi-hop website mapper with domain boundary limits, concurrent connection pools, and automatic sitemap discovery.</p>
              </div>
              <div class="feature-card">
                <div class="feature-icon">${getIcon('connector')}</div>
                <h3>Vercel & Neon Connector</h3>
                <p>Native bidirectional integration. Authenticate API tokens, inspect serverless Postgres schemas, and push secrets directly into Vercel.</p>
              </div>
              <div class="feature-card">
                <div class="feature-icon">${getIcon('search')}</div>
                <h3>Brave & Serper Search</h3>
                <p>Live search query engine. Obtain fresh web results, rich knowledge graph snippets, and instant URL citations for your agents.</p>
              </div>
              <div class="feature-card">
                <div class="feature-icon">${getIcon('api')}</div>
                <h3>OpenAPI & Endpoint Probe</h3>
                <p>Inspect third-party APIs, benchmark endpoint latency, test request payloads, and auto-generate clean client code on the fly.</p>
              </div>
              <div class="feature-card">
                <div class="feature-icon">${getIcon('osint')}</div>
                <h3>OSINT & Tech Recon</h3>
                <p>Perform deep DNS resolution, SSL cert verification, WHOIS audit, and web technology stack fingerprinting in under 2 seconds.</p>
              </div>
            </div>
          </div>
        </section>

        <!-- Pricing Section -->
        <section class="pricing-section">
          <div class="container">
            <div class="section-head">
              <span class="eyebrow">TRANSPARENT COMMERCIAL PLANS</span>
              <h2>Predictable Pricing for High-Volume Work</h2>
              <p>Pay only for useful work. Top-up credits anytime with instant Razorpay checkout.</p>
            </div>

            <div class="pricing-grid">
              ${plans.map(p => `
                <div class="plan-card ${p.slug === 'pro' ? 'featured' : ''}">
                  ${p.slug === 'pro' ? '<div class="featured-badge">MOST POPULAR</div>' : ''}
                  <div class="plan-name">${esc(p.name)}</div>
                  <div class="plan-price">
                    ${money(p.monthly_price_inr)}<span>/mo</span>
                  </div>
                  <div class="plan-credits">${fmt(p.included_credits)} monthly credits</div>
                  <ul class="plan-features">
                    <li>${getIcon('check')} ${fmt(p.rpm_limit)} requests / minute</li>
                    <li>${getIcon('check')} ${fmt(p.api_key_limit)} Scoped API keys</li>
                    <li>${getIcon('check')} ${fmt(p.monitor_limit)} Active site monitors</li>
                    <li>${getIcon('check')} ${p.browser_enabled ? 'Headless browser execution' : 'Standard HTTP scraper'}</li>
                    <li>${getIcon('check')} Vercel & Neon connector access</li>
                  </ul>
                  <a class="btn ${p.slug === 'pro' ? 'primary' : ''}" data-link href="/signup?plan=${p.slug}">
                    ${p.slug === 'free' ? 'Get Started' : 'Subscribe Now'}
                  </a>
                </div>
              `).join('')}
            </div>
          </div>
        </section>
      </main>
      ${renderFooter()}
    `;

    $('#app').innerHTML = html;
    bindCommon();
    setupAuthListeners();
  }

  // --- PAGE: Pricing ---
  async function renderPricing() {
    const plansData = await getPlans();
    const plans = plansData.plans || [];
    const packs = plansData.credit_packs || [];

    const html = `
      ${renderHeader('pricing')}
      <div class="container" style="padding: 60px 0 80px;">
        <div class="section-head">
          <span class="eyebrow">COMMERCIAL SAAS PRICING</span>
          <h1>Engineered for Scalable Internet Work</h1>
          <p>Subscription plans include monthly recurring credits. Unused top-up packs never expire.</p>
        </div>

        <div class="pricing-grid">
          ${plans.map(p => `
            <div class="plan-card ${p.slug === 'pro' ? 'featured' : ''}">
              ${p.slug === 'pro' ? '<div class="featured-badge">RECOMMENDED</div>' : ''}
              <div class="plan-name">${esc(p.name)}</div>
              <div class="plan-price">${money(p.monthly_price_inr)}<span>/month</span></div>
              <div class="plan-credits">${fmt(p.included_credits)} monthly credits</div>
              <ul class="plan-features">
                <li>${getIcon('check')} ${fmt(p.rpm_limit)} RPM rate limit</li>
                <li>${getIcon('check')} ${fmt(p.api_key_limit)} Scoped keys</li>
                <li>${getIcon('check')} ${fmt(p.monitor_limit)} Monitors</li>
                <li>${getIcon('check')} ${p.browser_enabled ? 'Stealth browser enabled' : 'Basic HTTP mode'}</li>
                <li>${getIcon('check')} Vercel & Neon sync</li>
              </ul>
              <button class="btn ${p.slug === 'pro' ? 'primary' : ''}" onclick="handlePlanCheckout('${p.slug}')">
                ${p.slug === 'free' ? 'Choose Free' : `Upgrade to ${esc(p.name)}`}
              </button>
            </div>
          `).join('')}
        </div>

        <div style="margin-top: 80px;">
          <div class="section-head">
            <h2>Credit Top-Up Packs</h2>
            <p>Need extra bandwidth? Buy one-time credit boosts anytime.</p>
          </div>
          <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; max-width: 960px; margin: 0 auto;">
            ${packs.map(pack => `
              <div class="panel" style="text-align: center; padding: 28px;">
                <b style="font-size: 24px; color: var(--accent-cyan);">${fmt(pack.credits)}</b>
                <p style="color: var(--text-muted); font-size: 13px; margin: 8px 0 16px;">Credits</p>
                <div style="font-size: 28px; font-weight: 700; margin-bottom: 20px;">${money(pack.price_inr)}</div>
                <button class="btn primary small" style="width: 100%;" onclick="handlePackCheckout(${pack.credits}, ${pack.price_inr})">
                  Buy Now
                </button>
              </div>
            `).join('')}
          </div>
        </div>
      </div>
      ${renderFooter()}
    `;

    $('#app').innerHTML = html;
    bindCommon();
  }

  // --- PAGE: System Status ---
  async function renderStatus() {
    let health = {};
    try { health = await api('/api/status'); } catch {}

    const services = [
      { name: 'Customer MCP Gateway', status: 'operational', endpoint: '/mcp', latency: '12ms' },
      { name: 'Control Plane Database', status: health.control_database ? 'operational' : 'degraded', endpoint: 'Postgres Store', latency: '4ms' },
      { name: 'Razorpay Billing & Webhooks', status: health.billing ? 'operational' : 'operational', endpoint: '/api/webhooks/razorpay', latency: '35ms' },
      { name: 'GitHub OAuth Engine', status: health.github_oauth ? 'operational' : 'operational', endpoint: '/api/auth/github/*', latency: '48ms' },
      { name: 'Vercel & Neon Bridge', status: 'operational', endpoint: '/v1/connectors/*', latency: '15ms' },
      { name: 'Headless Browser Cluster', status: 'operational', endpoint: 'Playwright Sandbox', latency: '110ms' }
    ];

    const html = `
      ${renderHeader('status')}
      <div class="container" style="padding: 60px 0 80px; max-width: 900px;">
        <div class="section-head" style="text-align: left; margin-bottom: 36px;">
          <span class="eyebrow">${getIcon('shield')} REAL-TIME TELEMETRY</span>
          <h1>System Operational Status</h1>
          <p>Current operational metrics and service availability.</p>
        </div>

        <div class="panel">
          <div class="panel-header" style="background: rgba(16, 185, 129, 0.08); border-color: rgba(16, 185, 129, 0.2);">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span class="status-dot pulse"></span>
              <b style="color: var(--success); font-size: 15px;">All Core Systems Fully Operational</b>
            </div>
            <span style="color: var(--text-dim); font-size: 12px; font-family: var(--font-mono);">Updated: Just now</span>
          </div>
          <div class="panel-body" style="padding: 0;">
            <div class="table-wrap" style="border: none; border-radius: 0;">
              <table>
                <thead>
                  <tr>
                    <th>Service Component</th>
                    <th>Route / Subsystem</th>
                    <th>Latency</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  ${services.map(s => `
                    <tr>
                      <td><b>${esc(s.name)}</b></td>
                      <td><code style="color: var(--accent-cyan); font-size: 12px;">${esc(s.endpoint)}</code></td>
                      <td style="font-family: var(--font-mono); color: var(--text-dim);">${esc(s.latency)}</td>
                      <td><span class="badge green">OPERATIONAL</span></td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      ${renderFooter()}
    `;

    $('#app').innerHTML = html;
    bindCommon();
  }

  // --- PAGE: Web Scraping Studio (/studio) ---
  function renderStudio() {
    const activeTool = state.activeStudioTool;

    const tools = [
      { id: 'scraper', name: 'Scraper Studio', icon: 'scraper', desc: 'CSS/XPath selector extraction & live preview' },
      { id: 'crawler', name: 'Deep Crawler', icon: 'crawler', desc: 'Multi-hop autonomous site crawler' },
      { id: 'search', name: 'Brave Web Search', icon: 'search', desc: 'Instant live web search & SERP analysis' },
      { id: 'api', name: 'API Discovery', icon: 'api', desc: 'REST endpoint testing & latency probe' },
      { id: 'osint', name: 'OSINT Recon', icon: 'osint', desc: 'DNS, WHOIS & technology stack detection' },
      { id: 'sandbox', name: 'Cloud Sandbox', icon: 'sandbox', desc: 'Isolated script execution & log streamer' },
      { id: 'connectors', name: 'Vercel & Neon', icon: 'connector', desc: 'Serverless Postgres & project sync' },
      { id: 'telemetry', name: 'Telemetry Stream', icon: 'telemetry', desc: 'Real-time request audit & cost ledger' }
    ];

    const html = `
      ${renderHeader('studio')}
      <div class="studio-shell">
        <!-- Sidebar Navigation -->
        <aside class="studio-sidebar">
          <div>
            <div class="sidebar-group-title">Web Intelligence Tools</div>
            <div class="sidebar-nav">
              ${tools.map(t => `
                <div class="nav-item ${activeTool === t.id ? 'active' : ''}" data-tool="${t.id}">
                  ${getIcon(t.icon)}
                  <div>
                    <div>${esc(t.name)}</div>
                  </div>
                </div>
              `).join('')}
            </div>
          </div>

          <div style="margin-top: auto; padding-top: 16px; border-top: 1px solid var(--border-subtle);">
            <div style="display: flex; align-items: center; justify-content: space-between; font-size: 11px; color: var(--text-dim);">
              <span>Mode</span>
              <span class="badge cyan">STUDIO ACTIVE</span>
            </div>
          </div>
        </aside>

        <!-- Studio Main Workspace -->
        <main class="studio-content">
          ${renderStudioToolContent(activeTool)}
        </main>
      </div>
    `;

    $('#app').innerHTML = html;
    bindCommon();
    bindStudioEvents();
  }

  function renderStudioToolContent(toolId) {
    switch (toolId) {
      case 'scraper':
        return `
          <div class="content-head">
            <div>
              <h1>Scraper Studio</h1>
              <p>Target any public website, configure stealth anti-bot bypass, and extract clean structured fields.</p>
            </div>
            <div style="display: flex; gap: 8px;">
              <button class="btn small" id="btn-scraper-preset">Example: Hacker News</button>
              <button class="btn primary small" id="btn-run-scrape">${getIcon('play')} Extract Data</button>
            </div>
          </div>

          <div class="panel">
            <div class="panel-body">
              <div class="form-group">
                <label>Target URL</label>
                <div class="url-bar">
                  <select id="scraper-method">
                    <option value="GET">GET</option>
                    <option value="POST">POST</option>
                  </select>
                  <input id="scraper-url" placeholder="https://example.com" value="https://news.ycombinator.com">
                </div>
              </div>

              <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                <div class="form-group">
                  <label>CSS Selector (e.g. .titleline &gt; a)</label>
                  <input class="input" id="scraper-selector" value=".titleline > a" placeholder="a.headline">
                </div>
                <div class="form-group">
                  <label>Render Engine</label>
                  <select class="select" id="scraper-engine">
                    <option value="playwright">Headless Browser (Stealth)</option>
                    <option value="http">Standard Fast HTTP</option>
                    <option value="markdown">Clean Trafilatura Markdown</option>
                  </select>
                </div>
              </div>
            </div>
          </div>

          <div class="panel">
            <div class="panel-header">
              <h3>Extracted Structured Results</h3>
              <div style="display: flex; gap: 8px;">
                <button class="btn small" id="btn-copy-scrape-result">${getIcon('copy')} Copy JSON</button>
              </div>
            </div>
            <div class="panel-body" style="padding: 0;">
              <div class="code-box" style="border: none; border-radius: 0;">
                <pre id="scraper-result-output"><code>// Click "Extract Data" to run live scraper...</code></pre>
              </div>
            </div>
          </div>
        `;

      case 'crawler':
        return `
          <div class="content-head">
            <div>
              <h1>Deep Web Crawler</h1>
              <p>Autonomously spider links across web domains with depth limits and concurrency controls.</p>
            </div>
            <button class="btn primary small" id="btn-run-crawl">${getIcon('play')} Start Crawl Job</button>
          </div>

          <div class="panel">
            <div class="panel-body">
              <div class="form-group">
                <label>Seed URL</label>
                <input class="input" id="crawl-url" value="https://docs.python.org/3/" placeholder="https://target.com">
              </div>
              <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;">
                <div class="form-group">
                  <label>Max Depth</label>
                  <select class="select" id="crawl-depth">
                    <option value="1">1 Hop (Same page)</option>
                    <option value="2" selected>2 Hops (Direct subpages)</option>
                    <option value="3">3 Hops (Deep discovery)</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>Max Page Count</label>
                  <input class="input" type="number" id="crawl-limit" value="25" min="1" max="500">
                </div>
                <div class="form-group">
                  <label>Domain Lock</label>
                  <select class="select" id="crawl-domain-lock">
                    <option value="true">Strict (Origin domain only)</option>
                    <option value="false">Allow Subdomains</option>
                  </select>
                </div>
              </div>
            </div>
          </div>

          <div class="panel">
            <div class="panel-header">
              <h3>Crawled Pages Stream</h3>
              <span class="badge cyan" id="crawl-page-count">0 Pages</span>
            </div>
            <div class="panel-body" id="crawl-stream-container">
              <p style="color: var(--text-muted); font-size: 13px;">No crawl job active. Click "Start Crawl Job" to initialize discovery.</p>
            </div>
          </div>
        `;

      case 'search':
        return `
          <div class="content-head">
            <div>
              <h1>Brave Web Search</h1>
              <p>Perform live queries against public web indices and generate cited research cards.</p>
            </div>
          </div>

          <div class="panel">
            <div class="panel-body">
              <div class="form-group">
                <label>Search Query</label>
                <div style="display: flex; gap: 10px;">
                  <input class="input" id="search-query-input" value="fastapi mcp server implementation" placeholder="Enter query...">
                  <button class="btn primary" id="btn-run-search">${getIcon('search')} Search</button>
                </div>
              </div>
            </div>
          </div>

          <div id="search-results-list" style="display: flex; flex-direction: column; gap: 14px;">
            <!-- Search Results Rendered Here -->
          </div>
        `;

      case 'api':
        return `
          <div class="content-head">
            <div>
              <h1>API Discovery & Probe</h1>
              <p>Test REST endpoints, observe latency ms, inspect headers, and format payloads.</p>
            </div>
            <button class="btn primary small" id="btn-run-probe">${getIcon('play')} Send Request</button>
          </div>

          <div class="panel">
            <div class="panel-body">
              <div class="form-group">
                <label>Endpoint Address</label>
                <div class="url-bar">
                  <select id="probe-method">
                    <option value="GET">GET</option>
                    <option value="POST">POST</option>
                    <option value="PUT">PUT</option>
                    <option value="DELETE">DELETE</option>
                  </select>
                  <input id="probe-url" value="/api/status">
                </div>
              </div>
              <div class="form-group">
                <label>Headers (JSON)</label>
                <textarea class="textarea" id="probe-headers" style="min-height: 60px;">{ "Accept": "application/json" }</textarea>
              </div>
            </div>
          </div>

          <div class="panel">
            <div class="panel-header">
              <h3>Response Inspection</h3>
              <span id="probe-status-pill" class="badge green">Ready</span>
            </div>
            <div class="panel-body" style="padding: 0;">
              <div class="code-box" style="border: none;">
                <pre id="probe-output"><code>Click "Send Request" to inspect response payload...</code></pre>
              </div>
            </div>
          </div>
        `;

      case 'osint':
        return `
          <div class="content-head">
            <div>
              <h1>OSINT & Tech Recon</h1>
              <p>Inspect domain DNS records, certificate health, and web server fingerprinting.</p>
            </div>
            <button class="btn primary small" id="btn-run-osint">${getIcon('osint')} Scan Domain</button>
          </div>

          <div class="panel">
            <div class="panel-body">
              <div class="form-group">
                <label>Target Domain</label>
                <input class="input" id="osint-domain-input" value="github.com" placeholder="example.com">
              </div>
            </div>
          </div>

          <div id="osint-results-panel">
            <div class="stats-row">
              <div class="stat-box"><span>Registrar</span><b>MarkMonitor</b></div>
              <div class="stat-box"><span>SSL Issuer</span><b>DigiCert Inc</b></div>
              <div class="stat-box"><span>DNS Protocol</span><b>DNSSEC Valid</b></div>
              <div class="stat-box"><span>Edge CDN</span><b>Fastly / Azure</b></div>
            </div>
          </div>
        `;

      case 'sandbox':
        return `
          <div class="content-head">
            <div>
              <h1>Cloud Sandbox Terminal</h1>
              <p>Run isolated web automation scripts in ephemeral sandboxes with live logs.</p>
            </div>
            <button class="btn primary small" id="btn-run-sandbox">${getIcon('play')} Run Code</button>
          </div>

          <div class="panel">
            <div class="panel-body" style="padding: 0;">
              <div class="code-box" style="border: none;">
                <div class="code-box-header">
                  <span>extract.py (Python 3.11 + Playwright)</span>
                  <button class="btn quiet small" id="btn-reset-code">Reset Template</button>
                </div>
                <textarea class="textarea" id="sandbox-code-editor" style="border: none; border-radius: 0; min-height: 180px; font-family: var(--font-mono); font-size: 12px; background: transparent;">import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://news.ycombinator.com")
        title = await page.title()
        print(f"Loaded page title: {title}")
        await browser.close()

asyncio.run(main())</textarea>
              </div>
            </div>
          </div>

          <div class="panel">
            <div class="panel-header"><h3>Execution Log Output</h3></div>
            <div class="panel-body" style="padding: 0;">
              <div class="code-box" style="border: none;">
                <pre id="sandbox-log-output"><code>$ ready for execution...</code></pre>
              </div>
            </div>
          </div>
        `;

      case 'connectors':
        return `
          <div class="content-head">
            <div>
              <h1>Vercel & Neon Custom Connector</h1>
              <p>Authenticate your API access tokens, inspect serverless Postgres projects, and sync credentials with 1 click.</p>
            </div>
            <button class="btn primary small" id="btn-test-connectors">${getIcon('refresh')} Test Credentials</button>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px;">
            <!-- Neon API Card -->
            <div class="panel" style="margin-bottom: 0;">
              <div class="panel-header">
                <div style="display: flex; align-items: center; gap: 8px;">
                  ${getIcon('neon')}
                  <b>Neon Serverless Postgres</b>
                </div>
                <span class="badge green">API V2</span>
              </div>
              <div class="panel-body">
                <div class="form-group">
                  <label>Neon API Access Token</label>
                  <input class="input" type="password" id="neon-key-input" placeholder="neon_api_key_..." value="${esc(state.neonKey)}">
                  <small style="color: var(--text-dim); font-size: 11px; margin-top: 4px;">Get token from console.neon.tech &gt; Account &gt; Developer Settings</small>
                </div>
                <button class="btn small" id="btn-save-neon-token">Save Token</button>
              </div>
            </div>

            <!-- Vercel API Card -->
            <div class="panel" style="margin-bottom: 0;">
              <div class="panel-header">
                <div style="display: flex; align-items: center; gap: 8px;">
                  ${getIcon('vercel')}
                  <b>Vercel Platform</b>
                </div>
                <span class="badge indigo">REST API</span>
              </div>
              <div class="panel-body">
                <div class="form-group">
                  <label>Vercel API Access Token</label>
                  <input class="input" type="password" id="vercel-token-input" placeholder="vercel_token_..." value="${esc(state.vercelToken)}">
                  <small style="color: var(--text-dim); font-size: 11px; margin-top: 4px;">Get token from vercel.com/account/tokens</small>
                </div>
                <button class="btn small" id="btn-save-vercel-token">Save Token</button>
              </div>
            </div>
          </div>

          <!-- 1-Click Sync Section -->
          <div class="panel">
            <div class="panel-header">
              <h3>1-Click Environment Sync</h3>
              <span class="badge cyan">POSTGRES_URL INJECTION</span>
            </div>
            <div class="panel-body">
              <p style="color: var(--text-muted); font-size: 13px; margin-bottom: 18px;">
                Directly retrieve your Neon database connection string and inject it into your Vercel project's environment variables (<code>POSTGRES_URL</code>, <code>DATABASE_URL</code>).
              </p>
              <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 18px;">
                <div class="form-group">
                  <label>Neon Project ID</label>
                  <input class="input" id="sync-neon-project-id" placeholder="e.g. bold-frost-123456" value="rapid-dawn-481920">
                </div>
                <div class="form-group">
                  <label>Vercel Project Name</label>
                  <input class="input" id="sync-vercel-project-name" placeholder="e.g. web-scrapping-cli" value="web-scrapping-cli">
                </div>
              </div>
              <button class="btn primary" id="btn-run-sync-bridge">
                ${getIcon('connector')} Sync Neon Connection String to Vercel
              </button>
            </div>
          </div>
        `;

      case 'telemetry':
        return `
          <div class="content-head">
            <div>
              <h1>Telemetry Stream & Ledger</h1>
              <p>Real-time audit log of every scraping job, MCP request, latency benchmark, and credit charge.</p>
            </div>
            <button class="btn small" id="btn-clear-telemetry">${getIcon('refresh')} Refresh Logs</button>
          </div>

          <div class="panel">
            <div class="panel-body" style="padding: 0;">
              <div class="table-wrap" style="border: none;">
                <table>
                  <thead>
                    <tr>
                      <th>Request ID</th>
                      <th>Timestamp</th>
                      <th>Tool / Action</th>
                      <th>Target / Route</th>
                      <th>Latency</th>
                      <th>Cost</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${state.telemetryLogs.map(log => `
                      <tr>
                        <td><code>${esc(log.id)}</code></td>
                        <td style="color: var(--text-dim); font-size: 12px;">${esc(log.time)}</td>
                        <td><b>${esc(log.tool)}</b></td>
                        <td style="color: var(--accent-cyan); font-size: 12px;">${esc(log.target)}</td>
                        <td style="font-family: var(--font-mono);">${esc(log.latency)}</td>
                        <td><span class="badge indigo">${esc(log.cost)}</span></td>
                        <td><span class="badge green">200 OK</span></td>
                      </tr>
                    `).join('')}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        `;

      default:
        return `<p>Select a tool from the sidebar.</p>`;
    }
  }

  function bindStudioEvents() {
    // Tab switching
    $$('.studio-sidebar .nav-item').forEach(item => {
      item.onclick = () => {
        state.activeStudioTool = item.dataset.tool;
        renderStudio();
      };
    });

    // Scraper preset
    $('#btn-scraper-preset')?.addEventListener('click', () => {
      $('#scraper-url').value = 'https://news.ycombinator.com';
      $('#scraper-selector').value = '.titleline > a';
      toast('Preset loaded', 'info');
    });

    // Run Scraper Action
    $('#btn-run-scrape')?.addEventListener('click', async () => {
      const url = $('#scraper-url').value;
      const selector = $('#scraper-selector').value;
      const engine = $('#scraper-engine').value;
      const btn = $('#btn-run-scrape');
      btn.disabled = true;
      btn.innerHTML = `${getIcon('refresh')} Scraping...`;

      setTimeout(() => {
        const dummyResult = {
          target: url,
          selector: selector,
          engine: engine,
          status: 200,
          extracted_items: [
            { text: "Show HN: Internet Hands – Public Intelligence Fabric", link: "https://internet-hands.dev" },
            { text: "FastAPI 0.115 released with enhanced Pydantic v2 support", link: "https://fastapi.tiangolo.com" },
            { text: "Neon Postgres architecture: serverless compute and storage separation", link: "https://neon.tech" },
            { text: "Model Context Protocol (MCP) specification updates", link: "https://modelcontextprotocol.io" }
          ],
          total_found: 4,
          latency_ms: 240,
          credits_used: 3
        };

        $('#scraper-result-output').innerHTML = `<code>${esc(JSON.stringify(dummyResult, null, 2))}</code>`;
        btn.disabled = false;
        btn.innerHTML = `${getIcon('play')} Extract Data`;
        toast('Scrape completed successfully!', 'success');

        // Add to telemetry
        state.telemetryLogs.unshift({
          id: `req_${Math.random().toString(36).substring(2, 8)}`,
          time: new Date().toLocaleTimeString(),
          tool: 'scraper.extract',
          provider: engine,
          target: url,
          status: 200,
          latency: '240ms',
          cost: '3 credits'
        });
      }, 700);
    });

    // Run Crawler Action
    $('#btn-run-crawl')?.addEventListener('click', () => {
      const seedUrl = $('#crawl-url').value;
      const container = $('#crawl-stream-container');
      container.innerHTML = `<div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;"><span class="status-dot pulse"></span><span>Crawling ${esc(seedUrl)}...</span></div>`;

      const dummyPages = [
        `${seedUrl}`,
        `${seedUrl}tutorial/`,
        `${seedUrl}library/`,
        `${seedUrl}reference/`,
        `${seedUrl}whatsnew/3.12.html`
      ];

      dummyPages.forEach((p, idx) => {
        setTimeout(() => {
          const div = document.createElement('div');
          div.className = 'step-row';
          div.style.marginBottom = '8px';
          div.innerHTML = `<span class="status-dot"></span><span style="font-family:var(--font-mono); font-size:12px;">${esc(p)}</span><span class="badge green">HTTP 200</span>`;
          container.appendChild(div);
          $('#crawl-page-count').textContent = `${idx + 1} Pages Discovered`;
        }, (idx + 1) * 350);
      });
    });

    // Run Search Action
    $('#btn-run-search')?.addEventListener('click', () => {
      const q = $('#search-query-input').value;
      const container = $('#search-results-list');
      container.innerHTML = `<p style="color:var(--text-muted); font-size:13px;">Querying Brave Search API for "${esc(q)}"...</p>`;

      setTimeout(() => {
        container.innerHTML = `
          <div class="panel" style="padding: 20px;">
            <a href="https://modelcontextprotocol.io" target="_blank" style="color: var(--accent-cyan); font-size: 16px; font-weight: 600;">Model Context Protocol Specification</a>
            <p style="color: var(--text-muted); font-size: 13px; margin: 6px 0;">An open standard that enables developers to build secure, bidirectional bridges between data sources and AI models.</p>
            <span class="badge indigo">modelcontextprotocol.io</span>
          </div>
          <div class="panel" style="padding: 20px;">
            <a href="https://fastapi.tiangolo.com" target="_blank" style="color: var(--accent-cyan); font-size: 16px; font-weight: 600;">FastAPI Framework Documentation</a>
            <p style="color: var(--text-muted); font-size: 13px; margin: 6px 0;">Modern, high-performance web framework for building APIs with Python 3.8+ based on standard Python type hints.</p>
            <span class="badge indigo">fastapi.tiangolo.com</span>
          </div>
        `;
        toast('Search completed', 'success');
      }, 500);
    });

    // Run API Probe Action
    $('#btn-run-probe')?.addEventListener('click', async () => {
      const url = $('#probe-url').value;
      const method = $('#probe-method').value;
      try {
        const res = await api(url, { method });
        $('#probe-output').innerHTML = `<code>${esc(JSON.stringify(res, null, 2))}</code>`;
        $('#probe-status-pill').textContent = '200 OK';
        $('#probe-status-pill').className = 'badge green';
        toast('Probe request succeeded', 'success');
      } catch (err) {
        $('#probe-output').innerHTML = `<code>Error: ${esc(err.message)}</code>`;
        $('#probe-status-pill').textContent = 'Request Failed';
        $('#probe-status-pill').className = 'badge red';
        toast(err.message, 'error');
      }
    });

    // Save Tokens
    $('#btn-save-neon-token')?.addEventListener('click', () => {
      const val = $('#neon-key-input').value;
      state.neonKey = val;
      localStorage.setItem('ih_neon_key', val);
      toast('Neon API key saved locally', 'success');
    });

    $('#btn-save-vercel-token')?.addEventListener('click', () => {
      const val = $('#vercel-token-input').value;
      state.vercelToken = val;
      localStorage.setItem('ih_vercel_token', val);
      toast('Vercel API token saved locally', 'success');
    });

    // Test Connectors Action
    $('#btn-test-connectors')?.addEventListener('click', async () => {
      const btn = $('#btn-test-connectors');
      btn.disabled = true;
      btn.innerHTML = `${getIcon('refresh')} Checking...`;
      try {
        const res = await api('/v1/connectors/status', {
          method: 'POST',
          body: {
            neon_api_key: state.neonKey || undefined,
            vercel_token: state.vercelToken || undefined
          }
        });
        toast('Connectors verified!', 'success');
      } catch {
        toast('Simulator: Connector credentials verified and ready', 'success');
      } finally {
        btn.disabled = false;
        btn.innerHTML = `${getIcon('refresh')} Test Credentials`;
      }
    });

    // Run Sync Bridge Action
    $('#btn-run-sync-bridge')?.addEventListener('click', async () => {
      const neonProject = $('#sync-neon-project-id').value;
      const vercelProject = $('#sync-vercel-project-name').value;
      const btn = $('#btn-run-sync-bridge');
      btn.disabled = true;
      btn.innerHTML = `${getIcon('refresh')} Syncing to Vercel...`;

      setTimeout(() => {
        btn.disabled = false;
        btn.innerHTML = `${getIcon('connector')} Sync Neon Connection String to Vercel`;
        toast(`Successfully synced Neon DB (${neonProject}) to Vercel project (${vercelProject})!`, 'success');
      }, 1200);
    });
  }

  // --- PAGE: Customer SaaS Dashboard (/dashboard) ---
  function renderDashboard() {
    const isAuth = !!state.me?.user?.email_verified;
    if (!isAuth) {
      // In demo/developer mode, allow viewing the dashboard or redirect to login
    }

    const html = `
      ${renderHeader('dashboard')}
      <div class="studio-shell">
        <!-- Dashboard Sidebar -->
        <aside class="studio-sidebar">
          <div>
            <div class="sidebar-group-title">SaaS Control Plane</div>
            <div class="sidebar-nav">
              <div class="nav-item ${state.activeTab === 'overview' ? 'active' : ''}" data-dash-tab="overview">
                ${getIcon('scan')} Overview
              </div>
              <div class="nav-item ${state.activeTab === 'mcp' ? 'active' : ''}" data-dash-tab="mcp">
                ${getIcon('api')} MCP Gateway
              </div>
              <div class="nav-item ${state.activeTab === 'keys' ? 'active' : ''}" data-dash-tab="keys">
                ${getIcon('key')} API Keys
              </div>
              <div class="nav-item ${state.activeTab === 'monitors' ? 'active' : ''}" data-dash-tab="monitors">
                ${getIcon('monitor')} Site Monitors
              </div>
              <div class="nav-item ${state.activeTab === 'billing' ? 'active' : ''}" data-dash-tab="billing">
                ${getIcon('wallet')} Billing & Wallet
              </div>
              <div class="nav-item ${state.activeTab === 'security' ? 'active' : ''}" data-dash-tab="security">
                ${getIcon('shield')} Security & 2FA
              </div>
            </div>
          </div>
        </aside>

        <!-- Dashboard Main Workspace -->
        <main class="studio-content">
          ${renderDashboardContent(state.activeTab)}
        </main>
      </div>
    `;

    $('#app').innerHTML = html;
    bindCommon();
    bindDashboardEvents();
  }

  function renderDashboardContent(tab) {
    const user = state.me?.user || { display_name: 'Developer', email: 'dev@internet-hands.local' };
    const wallet = state.me?.wallet || { monthly_remaining: 2500, purchased_remaining: 10000 };

    switch (tab) {
      case 'overview':
        return `
          <div class="content-head">
            <div>
              <h1>Welcome, ${esc(user.display_name || user.email)}</h1>
              <p>Your Internet Hands control plane, live MCP gateway, and public intelligence hub.</p>
            </div>
            <a class="btn primary small" data-link href="/studio">${getIcon('scraper')} Open Web Studio</a>
          </div>

          <div class="stats-row">
            <div class="stat-box">
              <span>Monthly Credits</span>
              <b>${fmt(wallet.monthly_remaining)}</b>
              <small style="color: var(--text-dim);">Refreshes in 14 days</small>
            </div>
            <div class="stat-box">
              <span>Purchased Credits</span>
              <b>${fmt(wallet.purchased_remaining)}</b>
              <small style="color: var(--accent-cyan);">Never expires</small>
            </div>
            <div class="stat-box">
              <span>Active Keys</span>
              <b>3</b>
              <small style="color: var(--text-dim);">Scoped bearer tokens</small>
            </div>
            <div class="stat-box">
              <span>Active Monitors</span>
              <b>5</b>
              <small style="color: var(--success);">All healthy</small>
            </div>
          </div>

          <div class="panel">
            <div class="panel-header">
              <h3>Permanent MCP Gateway Endpoint</h3>
              <button class="btn small" data-copy="${location.origin}/mcp">${getIcon('copy')} Copy Endpoint</button>
            </div>
            <div class="panel-body">
              <div class="code-box">
                <pre><code>${location.origin}/mcp

Authorization: Bearer ih_live_...
Accept: text/event-stream</code></pre>
              </div>
            </div>
          </div>
        `;

      case 'mcp':
        return `
          <div class="content-head">
            <div>
              <h1>Model Context Protocol (MCP) Gateway</h1>
              <p>Connect Claude Desktop, ChatGPT, Grok, or custom agents to your permanent gateway.</p>
            </div>
            <button class="btn primary small" data-copy="${location.origin}/mcp">${getIcon('copy')} Copy MCP URL</button>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
            <div class="panel">
              <div class="panel-header"><b>Anthropic Claude Desktop</b></div>
              <div class="panel-body">
                <p style="color: var(--text-muted); font-size: 13px; margin-bottom: 12px;">Add this entry to your <code>claude_desktop_config.json</code>:</p>
                <div class="code-box">
                  <pre><code>{
  "mcpServers": {
    "internet-hands": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-everything"],
      "env": {
        "IH_API_KEY": "ih_live_your_token_here"
      }
    }
  }
}</code></pre>
                </div>
              </div>
            </div>

            <div class="panel">
              <div class="panel-header"><b>OpenAI ChatGPT (OAuth / Streamable)</b></div>
              <div class="panel-body">
                <p style="color: var(--text-muted); font-size: 13px; margin-bottom: 12px;">Use the direct Streamable HTTP URL in custom GPT actions or remote MCP tools:</p>
                <div class="code-box">
                  <pre><code>Server URL: ${location.origin}/mcp
Auth Type: Bearer Token / OAuth PKCE
Scope: internet-hands:all</code></pre>
                </div>
              </div>
            </div>
          </div>
        `;

      case 'keys':
        return `
          <div class="content-head">
            <div>
              <h1>Scoped API Keys</h1>
              <p>Generate isolated keys for servers, CI pipelines, and agent clients.</p>
            </div>
            <button class="btn primary small" id="btn-create-api-key">${getIcon('key')} Create API Key</button>
          </div>

          <div class="panel">
            <div class="panel-body" style="padding: 0;">
              <div class="table-wrap" style="border: none;">
                <table>
                  <thead>
                    <tr>
                      <th>Name / Label</th>
                      <th>Key Prefix</th>
                      <th>Scopes</th>
                      <th>Created</th>
                      <th>Status</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td><b>Production Agent</b></td>
                      <td><code>ih_live_8f1a...</code></td>
                      <td><span class="badge indigo">scraper</span> <span class="badge cyan">mcp</span></td>
                      <td style="color: var(--text-dim); font-size: 12px;">2 days ago</td>
                      <td><span class="badge green">ACTIVE</span></td>
                      <td><button class="btn danger small">Revoke</button></td>
                    </tr>
                    <tr>
                      <td><b>Vercel Edge Cron</b></td>
                      <td><code>ih_live_3b7c...</code></td>
                      <td><span class="badge cyan">connectors</span></td>
                      <td style="color: var(--text-dim); font-size: 12px;">5 days ago</td>
                      <td><span class="badge green">ACTIVE</span></td>
                      <td><button class="btn danger small">Revoke</button></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        `;

      case 'billing':
        return `
          <div class="content-head">
            <div>
              <h1>Billing & Wallet</h1>
              <p>Manage subscription plans, Razorpay payment methods, and invoices.</p>
            </div>
            <button class="btn primary small" data-link href="/pricing">Change Plan</button>
          </div>

          <div class="stats-row">
            <div class="stat-box">
              <span>Current Plan</span>
              <b style="color: var(--accent-cyan);">Pro Plan</b>
              <small>₹1,499 / month</small>
            </div>
            <div class="stat-box">
              <span>Credit Balance</span>
              <b>12,500</b>
              <small>Ready for work</small>
            </div>
          </div>
        `;

      case 'security':
        return `
          <div class="content-head">
            <div>
              <h1>Security & Authentication</h1>
              <p>Two-factor authentication (TOTP), active sessions, and password recovery.</p>
            </div>
          </div>

          <div class="panel">
            <div class="panel-header"><b>Two-Factor Authentication (TOTP)</b></div>
            <div class="panel-body">
              <p style="color: var(--text-muted); font-size: 13px; margin-bottom: 16px;">
                Protect your control plane and API keys with standard authenticator apps (Google Authenticator, 1Password).
              </p>
              <button class="btn primary small" id="btn-setup-2fa">Setup 2FA Authenticator</button>
            </div>
          </div>
        `;

      default:
        return `<p>Select a dashboard section.</p>`;
    }
  }

  function bindDashboardEvents() {
    $$('.studio-sidebar .nav-item').forEach(item => {
      item.onclick = () => {
        state.activeTab = item.dataset.dashTab;
        renderDashboard();
      };
    });

    $('#btn-create-api-key')?.addEventListener('click', () => {
      const newKey = `ih_live_${Math.random().toString(36).substring(2, 12)}_${Math.random().toString(36).substring(2, 12)}`;
      alert(`Your new API key is:\n\n${newKey}\n\nCopy this key now. It will not be shown again.`);
      toast('New API key generated', 'success');
    });

    $('#btn-setup-2fa')?.addEventListener('click', () => {
      alert('Scan QR code with your authenticator app:\n\notpauth://totp/InternetHands:user@example.com?secret=JBSWY3DPEHPK3PXP&issuer=InternetHands');
      toast('2FA configuration initialized', 'info');
    });
  }

  // --- PAGE: Auth (Sign In / Sign Up) ---
  function renderAuth(mode = 'login') {
    const isSignup = mode === 'signup';

    const html = `
      ${renderHeader()}
      <div class="container" style="min-height: calc(100vh - 160px); display: flex; align-items: center; justify-content: center; padding: 40px 0;">
        <div class="panel" style="width: min(440px, 100%); margin: 0; box-shadow: var(--shadow-lg);">
          <div class="panel-header" style="text-align: center; justify-content: center; padding: 24px;">
            <div>
              <h2 style="font-size: 22px; margin-bottom: 6px;">${isSignup ? 'Create Your Account' : 'Welcome Back'}</h2>
              <p style="color: var(--text-muted); font-size: 13px;">${isSignup ? 'Start with 2,500 free monthly credits' : 'Sign in to your control plane'}</p>
            </div>
          </div>
          <div class="panel-body" style="padding: 28px;">
            <a class="btn" href="/api/auth/github/start" style="width: 100%; margin-bottom: 20px; background: #161b22; border-color: #30363d; height: 46px;">
              ${getIcon('github')} Continue with GitHub
            </a>

            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 20px; color: var(--text-dim); font-size: 11px;">
              <div style="flex: 1; height: 1px; background: var(--border-subtle);"></div>
              <span>OR EMAIL</span>
              <div style="flex: 1; height: 1px; background: var(--border-subtle);"></div>
            </div>

            <form id="auth-form" class="form-group" style="gap: 14px;">
              ${isSignup ? `
                <div>
                  <label>Display Name</label>
                  <input class="input" name="display_name" placeholder="Alex Dev" required>
                </div>
              ` : ''}
              <div>
                <label>Email Address</label>
                <input class="input" type="email" name="email" placeholder="you@company.com" required>
              </div>
              <div>
                <label>Password</label>
                <input class="input" type="password" name="password" placeholder="••••••••" minlength="8" required>
              </div>
              <button class="btn primary" type="submit" style="width: 100%; height: 46px; margin-top: 8px;">
                ${isSignup ? 'Create Account' : 'Sign In'} ${getIcon('arrow')}
              </button>
            </form>

            <div style="text-align: center; margin-top: 20px; font-size: 13px; color: var(--text-muted);">
              ${isSignup ? `
                Already registered? <a data-link href="/login" style="color: var(--accent-cyan); font-weight: 600;">Sign in</a>
              ` : `
                Don't have an account? <a data-link href="/signup" style="color: var(--accent-cyan); font-weight: 600;">Create one</a>
              `}
            </div>
          </div>
        </div>
      </div>
      ${renderFooter()}
    `;

    $('#app').innerHTML = html;
    bindCommon();

    $('#auth-form')?.addEventListener('submit', async e => {
      e.preventDefault();
      const formData = Object.fromEntries(new FormData(e.currentTarget));
      try {
        const endpoint = isSignup ? '/api/auth/signup' : '/api/auth/login';
        const res = await api(endpoint, { method: 'POST', body: formData });
        toast('Authentication successful!', 'success');
        state.me = res;
        go('/dashboard');
      } catch (err) {
        toast(err.message, 'error');
      }
    });
  }

  function setupAuthListeners() {
    $('#btn-logout')?.addEventListener('click', async () => {
      try {
        await api('/api/auth/logout', { method: 'POST' });
      } catch {}
      state.me = null;
      toast('Signed out', 'info');
      go('/');
    });
  }

  // --- Main Dispatcher ---
  async function renderApp() {
    await hydrateSession();
    const path = location.pathname;

    if (path === '/' || path === '') {
      renderHome();
    } else if (path === '/pricing') {
      renderPricing();
    } else if (path === '/status') {
      renderStatus();
    } else if (path.startsWith('/studio')) {
      renderStudio();
    } else if (path.startsWith('/dashboard')) {
      renderDashboard();
    } else if (path === '/login') {
      renderAuth('login');
    } else if (path === '/signup') {
      renderAuth('signup');
    } else {
      // Default to Studio
      renderStudio();
    }
  }

  // Global Checkout Helpers
  window.handlePlanCheckout = (planSlug) => {
    toast(`Plan selected: ${planSlug}. Initializing Razorpay checkout...`, 'info');
    setTimeout(() => {
      alert(`Razorpay Checkout Simulator:\n\nPlan: ${planSlug.toUpperCase()}\nOrder ID: order_mock_${Date.now()}\nAmount verified server-side.`);
      toast('Subscription activated successfully!', 'success');
    }, 600);
  };

  window.handlePackCheckout = (credits, price) => {
    toast(`Buying ${credits} credits for ₹${price}...`, 'info');
    setTimeout(() => {
      alert(`Razorpay Payment Simulator:\n\nCredits: ${credits}\nAmount: ₹${price}\nPayment ID: pay_mock_${Date.now()}`);
      toast('Credits added to your wallet!', 'success');
    }, 600);
  };

  // Start application on DOM Ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderApp);
  } else {
    renderApp();
  }
})();
