/* Internet Hands editorial product layer.
 * Loaded last. Replaces the generic neon/AI-startup presentation while preserving
 * all existing routes, API calls, auth handlers, billing behavior and dashboard logic.
 */
(() => {
  const rule = (label, value) => `<div class="ed-rule"><span>${label}</span><b>${value}</b></div>`;

  brand = function editorialBrand() {
    return `<a class="brand ih-brand ed-brand" data-link href="/" aria-label="Internet Hands home">
      <img src="/assets/mark.svg" width="30" height="30" alt="">
      <span>Internet Hands</span>
    </a>`;
  };

  publicShell = function editorialPublicShell(content) {
    const authenticated = !!state.me?.user?.email_verified;
    app.innerHTML = `<div class="ed-public-shell">
      <header class="ed-header">
        <nav class="container ed-nav">
          ${brand()}
          <div class="ed-nav-links">
            <a data-link href="/docs/capabilities">Platform</a>
            <a data-link href="/docs">Documentation</a>
            <a data-link href="/pricing">Pricing</a>
            <a data-link href="/status">Status</a>
          </div>
          <div class="ed-nav-actions">
            ${authenticated ? `<a class="ed-link-button" data-link href="/dashboard">Open console</a>` : `<a data-link href="/login">Sign in</a><a class="ed-link-button" data-link href="/signup">Create account</a>`}
          </div>
          <button class="icon-btn nav-toggle" data-nav-toggle aria-label="Open navigation">${icon('menu')}</button>
        </nav>
        <div class="mobile-menu ed-mobile-menu" data-mobile-menu>
          <a data-link href="/docs/capabilities">Platform</a><a data-link href="/docs">Documentation</a><a data-link href="/pricing">Pricing</a><a data-link href="/status">Status</a>
          ${authenticated ? `<a data-link href="/dashboard">Open console</a>` : `<a data-link href="/login">Sign in</a><a data-link href="/signup">Create account</a>`}
        </div>
      </header>
      ${content}
      <footer class="ed-footer">
        <div class="container ed-footer-grid">
          <div>${brand()}<p>Internet infrastructure for software that needs to search, inspect, extract and monitor public information.</p></div>
          <div><b>Product</b><a data-link href="/docs/capabilities">Capabilities</a><a data-link href="/docs/monitoring">Monitoring</a><a data-link href="/pricing">Pricing</a></div>
          <div><b>Developers</b><a data-link href="/docs/quickstart">Quickstart</a><a data-link href="/docs/mcp">MCP</a><a href="https://github.com/sphangcho203-afk/Web-Scrapping-CLI" target="_blank" rel="noreferrer">GitHub</a></div>
          <div><b>System</b><a data-link href="/status">Status</a><span>Scoped access</span><span>Metered execution</span></div>
        </div>
      </footer>
    </div>`;
    bindCommon();
  };

  renderHome = async function editorialHome() {
    publicShell(`<main class="ed-home">
      <section class="ed-hero">
        <div class="container ed-hero-grid">
          <div class="ed-hero-copy">
            <p class="ed-kicker">INTERNET HANDS / OPERATIONS PLATFORM</p>
            <h1>Give software a disciplined way to work with the internet.</h1>
            <p class="ed-deck">Search, browse, extract, monitor and route public internet work through one controlled interface. Keep the request, provider, cost, latency and evidence inspectable afterward.</p>
            <div class="ed-actions">
              <a class="ed-primary" data-link href="${state.me?.user?.email_verified ? '/dashboard' : '/signup'}">Open the console</a>
              <a class="ed-secondary" data-link href="/docs/quickstart">Read the quickstart</a>
            </div>
          </div>
          <aside class="ed-spec">
            <div class="ed-spec-head"><span>OPERATION / 1842</span><b>COMPLETE</b></div>
            <h2>Research a product, capture its public pricing, and retain the sources.</h2>
            <div class="ed-spec-grid">
              ${rule('01 / ROUTE','web + browser')}
              ${rule('02 / SOURCES','18 pages')}
              ${rule('03 / OUTPUT','structured data')}
              ${rule('04 / EVIDENCE','7 records')}
              ${rule('05 / LATENCY','2.4 s')}
              ${rule('06 / COST','11 credits')}
            </div>
            <div class="ed-spec-foot"><span>req_7f2c91</span><span>provider route retained</span></div>
          </aside>
        </div>
      </section>

      <section class="ed-proof">
        <div class="container ed-proof-grid">
          <span>OPENAI</span><span>ANTHROPIC</span><span>xAI</span><span>GITHUB</span><span>MCP</span><span>REST</span>
        </div>
      </section>

      <section class="ed-section">
        <div class="container ed-two-col">
          <div class="ed-section-title"><p>WHAT IT DOES</p><h2>A small control surface for a large capability layer.</h2></div>
          <div class="ed-capability-list">
            <article><span>01</span><div><h3>Collect</h3><p>Search, fetch, crawl and extract public information while keeping source context attached.</p></div></article>
            <article><span>02</span><div><h3>Operate</h3><p>Use browser and isolated execution when a target needs more than a plain HTTP request.</p></div></article>
            <article><span>03</span><div><h3>Route</h3><p>Resolve the right API, remote MCP or provider capability without dumping an entire catalog into the model.</p></div></article>
            <article><span>04</span><div><h3>Observe</h3><p>Track request IDs, status, provider, credits and latency in one operational ledger.</p></div></article>
          </div>
        </div>
      </section>

      <section class="ed-section ed-section-lined">
        <div class="container">
          <div class="ed-section-title wide"><p>RUN LEDGER</p><h2>The result is only useful when the operation can be inspected.</h2></div>
          <div class="ed-table">
            <div class="ed-table-row head"><span>REQUEST</span><span>CAPABILITY</span><span>PROVIDER</span><span>STATE</span><span>LATENCY</span></div>
            <div class="ed-table-row"><code>req_8ca5f2</code><span>web.search</span><span>public web</span><b>OK</b><span>184 ms</span></div>
            <div class="ed-table-row"><code>req_63d1a0</code><span>browser.open</span><span>chromium</span><b>OK</b><span>1.2 s</span></div>
            <div class="ed-table-row"><code>req_a82e19</code><span>mesh.execute</span><span>remote tool</span><b>OK</b><span>426 ms</span></div>
            <div class="ed-table-row"><code>req_1ed34b</code><span>extract.structured</span><span>parser</span><b>OK</b><span>307 ms</span></div>
          </div>
        </div>
      </section>

      <section class="ed-section">
        <div class="container ed-three">
          <article><span>01 / CONTROL</span><h3>Scoped credentials</h3><p>Keys and interactive authorization stay explicit and revocable.</p></article>
          <article><span>02 / ACCOUNTING</span><h3>Metered work</h3><p>Usage is attached to concrete requests instead of vague platform activity.</p></article>
          <article><span>03 / EVIDENCE</span><h3>Traceable output</h3><p>Design the workflow so a human can understand what happened after the run.</p></article>
        </div>
      </section>

      <section class="ed-closing">
        <div class="container ed-closing-inner"><div><p>START HERE</p><h2>One account. One connection. One successful request.</h2></div><a class="ed-primary" data-link href="${state.me?.user?.email_verified ? '/dashboard' : '/signup'}">Open Internet Hands</a></div>
      </section>
    </main>`);
  };

  authShell = function editorialAuthShell(title, sub, content, story = 'Controlled internet access for software.') {
    app.innerHTML = `<main class="ed-auth-layout">
      <section class="ed-auth-context">
        <div>${brand()}</div>
        <div class="ed-auth-copy"><p>INTERNET HANDS</p><h1>${story}</h1><p>Identity, access, usage and internet operations in one account boundary.</p></div>
        <div class="ed-auth-notes"><span>Verified identity</span><span>Scoped credentials</span><span>Request ledger</span></div>
      </section>
      <section class="ed-auth-main">
        <div class="ed-auth-card">
          <div class="auth-mobile-brand">${brand()}</div>
          <header><p class="ed-kicker">ACCOUNT</p><h2>${title}</h2><p>${sub}</p></header>
          ${content}
          <footer class="ed-auth-foot">Encrypted session · explicit account controls</footer>
        </div>
      </section>
    </main>`;
    bindCommon();
  };

  renderRoute();
})();
