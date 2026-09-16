/**
 * Internet Hands — Web Studio & Control Plane
 * Elite UI/UX, multi-engine scraping, OSINT intelligence, and real-time telemetry.
 */

// Application State
const state = {
  activeTab: 'overview',
  theme: localStorage.getItem('ih_theme') || 'dark',
  apiConfig: {
    baseUrl: localStorage.getItem('ih_api_url') || (window.location.protocol.startsWith('http') ? window.location.origin : 'http://localhost:8788'),
    apiKey: localStorage.getItem('ih_api_key') || '',
    isOnline: false,
    useDemoFallback: true,
  },
  telemetryEvents: [],
  sseSource: null,
  activeCapture: null,
  activeCrawlResults: [],
  activeSearchResults: [],
  activeDiscovery: null,
  activeOsint: null,
  activeWatches: [
    { id: 1, url: 'https://news.ycombinator.com', interval: 3600, lastCheck: '10 mins ago', status: 'changed', hash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855' },
    { id: 2, url: 'https://github.com/trending', interval: 7200, lastCheck: '42 mins ago', status: 'unchanged', hash: '5f4dcc3b5aa765d61d8327deb882cf99' },
    { id: 3, url: 'https://pypi.org/project/fastapi/', interval: 86400, lastCheck: '3 hours ago', status: 'unchanged', hash: '7c4a8d09ca3762af61e59520943dc26494f8941b' }
  ],
};

// Initialize Theme
function initTheme() {
  document.documentElement.setAttribute('data-theme', state.theme);
  const themeToggle = document.getElementById('theme-toggle-btn');
  if (themeToggle) {
    themeToggle.innerHTML = state.theme === 'dark' 
      ? '<i data-lucide="sun" class="w-4 h-4"></i>' 
      : '<i data-lucide="moon" class="w-4 h-4"></i>';
  }
}

function toggleTheme() {
  state.theme = state.theme === 'dark' ? 'light' : 'dark';
  localStorage.setItem('ih_theme', state.theme);
  initTheme();
  lucide.createIcons();
}

// Toast Notification
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'toast';
  
  let iconName = 'info';
  let iconColor = 'text-indigo-400';
  if (type === 'success') { iconName = 'check-circle'; iconColor = 'text-emerald-400'; }
  if (type === 'error') { iconName = 'alert-triangle'; iconColor = 'text-rose-400'; }
  if (type === 'warning') { iconName = 'alert-circle'; iconColor = 'text-amber-400'; }

  toast.innerHTML = `
    <i data-lucide="${iconName}" class="w-5 h-5 ${iconColor} shrink-0"></i>
    <div class="flex-1 text-xs sm:text-sm">${message}</div>
  `;

  container.appendChild(toast);
  lucide.createIcons({ root: toast });

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px) scale(0.95)';
    toast.style.transition = 'all 0.2s ease';
    setTimeout(() => toast.remove(), 200);
  }, 3500);
}

// Resilient API Fetcher with Smart Demo Fallback
async function apiCall(endpoint, options = {}) {
  const headers = { ...options.headers };
  if (state.apiConfig.apiKey) {
    headers['X-API-Key'] = state.apiConfig.apiKey;
  }

  const url = `${state.apiConfig.baseUrl.replace(/\/+$/, '')}${endpoint}`;

  try {
    const res = await fetch(url, {
      ...options,
      headers,
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`HTTP ${res.status}: ${errText || res.statusText}`);
    }

    state.apiConfig.isOnline = true;
    updateStatusPill();
    return await res.json();
  } catch (err) {
    console.warn(`[API] Failed to call ${endpoint}:`, err.message);
    state.apiConfig.isOnline = false;
    updateStatusPill();

    if (state.apiConfig.useDemoFallback) {
      return getDemoData(endpoint, options);
    }
    throw err;
  }
}

// Health Check
async function checkBackendHealth() {
  try {
    const res = await fetch(`${state.apiConfig.baseUrl.replace(/\/+$/, '')}/healthz`, {
      headers: state.apiConfig.apiKey ? { 'X-API-Key': state.apiConfig.apiKey } : {},
    });
    if (res.ok) {
      state.apiConfig.isOnline = true;
    } else {
      state.apiConfig.isOnline = false;
    }
  } catch {
    state.apiConfig.isOnline = false;
  }
  updateStatusPill();
}

function updateStatusPill() {
  const pill = document.getElementById('connection-status-pill');
  if (!pill) return;

  if (state.apiConfig.isOnline) {
    pill.innerHTML = `
      <span class="status-indicator status-online"></span>
      <span class="text-xs font-medium text-emerald-400">Live API</span>
    `;
    document.getElementById('demo-mode-banner')?.classList.add('hidden');
  } else {
    pill.innerHTML = `
      <span class="status-indicator status-demo"></span>
      <span class="text-xs font-medium text-amber-400">Demo Simulator</span>
    `;
    document.getElementById('demo-mode-banner')?.classList.remove('hidden');
  }
}

// Tab Navigation
function switchTab(tabId) {
  state.activeTab = tabId;
  document.querySelectorAll('.nav-tab').forEach(tab => {
    if (tab.dataset.tab === tabId) {
      tab.classList.add('active');
    } else {
      tab.classList.remove('active');
    }
  });

  document.querySelectorAll('.tab-view').forEach(view => {
    if (view.id === `view-${tabId}`) {
      view.classList.remove('hidden');
    } else {
      view.classList.add('hidden');
    }
  });

  updateCodeDrawerForCurrentTab();
  lucide.createIcons();
}

// Code Generator Drawer
function updateCodeDrawerForCurrentTab() {
  const tab = state.activeTab;
  let cliSnippet = '';
  let pythonSnippet = '';
  let curlSnippet = '';

  const apiUrl = state.apiConfig.baseUrl;

  if (tab === 'scraper') {
    const targetUrl = document.getElementById('scraper-url-input')?.value || 'https://news.ycombinator.com';
    cliSnippet = `ih fetch "${targetUrl}" --include-body`;
    pythonSnippet = `import httpx\n\nres = httpx.get("${apiUrl}/v1/fetch", params={"url": "${targetUrl}", "include_body": True})\nprint(res.json())`;
    curlSnippet = `curl -X GET "${apiUrl}/v1/fetch?url=${encodeURIComponent(targetUrl)}&include_body=true"`;
  } else if (tab === 'crawler') {
    const targetUrl = document.getElementById('crawler-url-input')?.value || 'https://example.com';
    cliSnippet = `ih crawl "${targetUrl}" --max-pages 25`;
    pythonSnippet = `import httpx\n\nres = httpx.get("${apiUrl}/v1/crawl", params={"url": "${targetUrl}", "max_pages": 25})\ndata = res.json()\nprint(f"Crawled {len(data['pages'])} pages")`;
    curlSnippet = `curl -X GET "${apiUrl}/v1/crawl?url=${encodeURIComponent(targetUrl)}&max_pages=25"`;
  } else if (tab === 'search') {
    const query = document.getElementById('search-query-input')?.value || 'artificial intelligence web intelligence';
    cliSnippet = `ih-search web "${query}" --count 10`;
    pythonSnippet = `import httpx\n\nres = httpx.get("${apiUrl}/v1/web-search", params={"q": "${query}", "kind": "web", "count": 10})\nprint(res.json())`;
    curlSnippet = `curl -X GET "${apiUrl}/v1/web-search?q=${encodeURIComponent(query)}&kind=web&count=10"`;
  } else if (tab === 'discovery') {
    const targetUrl = document.getElementById('discovery-url-input')?.value || 'https://stripe.com';
    cliSnippet = `ih-discover "${targetUrl}" --probe-openapi`;
    pythonSnippet = `import httpx\n\nres = httpx.get("${apiUrl}/v1/discover", params={"url": "${targetUrl}", "probe_openapi": True})\nprint(res.json())`;
    curlSnippet = `curl -X GET "${apiUrl}/v1/discover?url=${encodeURIComponent(targetUrl)}&probe_openapi=true"`;
  } else if (tab === 'osint') {
    const username = document.getElementById('osint-username-input')?.value || 'sphangcho203-afk';
    cliSnippet = `ih intel username "${username}"`;
    pythonSnippet = `import httpx\n\nres = httpx.get("${apiUrl}/v1/intel/username", params={"username": "${username}"})\nprint(res.json())`;
    curlSnippet = `curl -X GET "${apiUrl}/v1/intel/username?username=${encodeURIComponent(username)}"`;
  } else {
    cliSnippet = `ih --help`;
    pythonSnippet = `import httpx\n\nres = httpx.get("${apiUrl}/healthz")\nprint(res.json())`;
    curlSnippet = `curl -X GET "${apiUrl}/healthz"`;
  }

  const cliEl = document.getElementById('code-cli');
  const pyEl = document.getElementById('code-python');
  const curlEl = document.getElementById('code-curl');

  if (cliEl) cliEl.textContent = cliSnippet;
  if (pyEl) pyEl.textContent = pythonSnippet;
  if (curlEl) curlEl.textContent = curlSnippet;
}

function copyCodeSnippet(type) {
  let text = '';
  if (type === 'cli') text = document.getElementById('code-cli')?.textContent || '';
  if (type === 'python') text = document.getElementById('code-python')?.textContent || '';
  if (type === 'curl') text = document.getElementById('code-curl')?.textContent || '';

  if (!text) return;
  navigator.clipboard.writeText(text);
  showToast(`Copied ${type.toUpperCase()} command to clipboard`, 'success');
}

// Scraper Handler
async function runScraper() {
  const urlInput = document.getElementById('scraper-url-input');
  const modeSelect = document.getElementById('scraper-mode-select');
  const runBtn = document.getElementById('scraper-run-btn');

  const url = urlInput?.value.trim();
  if (!url) {
    showToast('Please enter a valid URL to scrape', 'warning');
    return;
  }

  const mode = modeSelect?.value || 'fetch';
  runBtn.disabled = true;
  runBtn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Scraping...';
  lucide.createIcons();

  try {
    let endpoint = '/v1/fetch?url=' + encodeURIComponent(url) + '&include_body=true';
    if (mode === 'browser') {
      endpoint = '/v1/browser?url=' + encodeURIComponent(url) + '&include_html=true';
    }

    const data = await apiCall(endpoint);
    state.activeCapture = data;
    renderScraperResults(data);
    showToast(`Successfully extracted content from ${new URL(url).hostname}`, 'success');
  } catch (err) {
    showToast(`Scrape failed: ${err.message}`, 'error');
  } finally {
    runBtn.disabled = false;
    runBtn.innerHTML = '<i data-lucide="play" class="w-4 h-4"></i> Execute Scrape';
    updateCodeDrawerForCurrentTab();
    lucide.createIcons();
  }
}

function renderScraperResults(data) {
  const container = document.getElementById('scraper-results-container');
  if (!container) return;
  container.classList.remove('hidden');

  // Stats
  document.getElementById('stat-status-code').textContent = data.status || 200;
  document.getElementById('stat-timing-ms').textContent = (data.timing_ms || 248) + ' ms';
  document.getElementById('stat-size-kb').textContent = ((data.body?.length || 18420) / 1024).toFixed(1) + ' KB';
  document.getElementById('stat-sha256').textContent = data.sha256 || '9a4f78e12b...';

  // Text
  document.getElementById('scraper-extracted-title').textContent = data.title || 'Extracted Document';
  document.getElementById('scraper-extracted-text').textContent = data.text || data.readable_text || data.body || 'No readable text content extracted.';

  // Links
  const linksTable = document.getElementById('scraper-links-body');
  if (linksTable) {
    const links = data.links || [];
    if (links.length === 0) {
      linksTable.innerHTML = '<tr><td colspan="3" class="px-4 py-3 text-center text-xs text-slate-500">No links extracted</td></tr>';
    } else {
      linksTable.innerHTML = links.slice(0, 50).map((link, idx) => `
        <tr class="border-b border-slate-800/40 hover:bg-slate-800/30 text-xs">
          <td class="px-4 py-2 text-slate-400">${idx + 1}</td>
          <td class="px-4 py-2 font-mono text-indigo-400 break-all">
            <a href="${link.url || link}" target="_blank" class="hover:underline flex items-center gap-1">
              ${link.url || link}
              <i data-lucide="external-link" class="w-3 h-3"></i>
            </a>
          </td>
          <td class="px-4 py-2 text-slate-300">${link.text || 'Anchor'}</td>
        </tr>
      `).join('');
    }
  }

  // Headers
  const headersEl = document.getElementById('scraper-raw-headers');
  if (headersEl) {
    headersEl.textContent = JSON.stringify(data.headers || {
      'content-type': 'text/html; charset=utf-8',
      'server': 'cloudflare',
      'strict-transport-security': 'max-age=31536000',
      'x-frame-options': 'DENY'
    }, null, 2);
  }

  // Raw Body
  const rawBodyEl = document.getElementById('scraper-raw-body');
  if (rawBodyEl) {
    rawBodyEl.textContent = data.body || data.html || '<html>...</html>';
  }
}

// Deep Crawler Handler
async function runCrawler() {
  const urlInput = document.getElementById('crawler-url-input');
  const maxPagesInput = document.getElementById('crawler-max-pages');
  const runBtn = document.getElementById('crawler-run-btn');

  const url = urlInput?.value.trim();
  if (!url) {
    showToast('Please enter a valid seed URL', 'warning');
    return;
  }

  const maxPages = parseInt(maxPagesInput?.value || '15', 10);
  runBtn.disabled = true;
  runBtn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Crawling...';
  lucide.createIcons();

  try {
    const data = await apiCall(`/v1/crawl?url=${encodeURIComponent(url)}&max_pages=${maxPages}`);
    state.activeCrawlResults = data.pages || [];
    renderCrawlerResults(data);
    showToast(`Crawl completed: indexed ${state.activeCrawlResults.length} pages`, 'success');
  } catch (err) {
    showToast(`Crawl failed: ${err.message}`, 'error');
  } finally {
    runBtn.disabled = false;
    runBtn.innerHTML = '<i data-lucide="network" class="w-4 h-4"></i> Start Deep Crawl';
    updateCodeDrawerForCurrentTab();
    lucide.createIcons();
  }
}

function renderCrawlerResults(data) {
  const container = document.getElementById('crawler-results-container');
  if (!container) return;
  container.classList.remove('hidden');

  const pages = data.pages || [];
  document.getElementById('crawler-count-badge').textContent = `${pages.length} Pages Crawled`;

  const listEl = document.getElementById('crawler-pages-list');
  if (listEl) {
    listEl.innerHTML = pages.map((p, i) => `
      <div class="glass-panel p-3 rounded-lg border border-slate-800 flex items-start justify-between gap-4">
        <div class="space-y-1">
          <div class="flex items-center gap-2">
            <span class="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono font-medium">${p.status || 200}</span>
            <span class="text-xs font-semibold text-slate-200">${p.title || 'Page ' + (i + 1)}</span>
          </div>
          <p class="text-xs font-mono text-slate-400 break-all">${p.url}</p>
        </div>
        <div class="text-right text-xs text-slate-500 shrink-0">
          <div>${p.depth ? 'Depth ' + p.depth : 'Origin'}</div>
          <div>${((p.size || 8400) / 1024).toFixed(1)} KB</div>
        </div>
      </div>
    `).join('');
  }
}

// Brave Web Search Handler
async function runSearch() {
  const queryInput = document.getElementById('search-query-input');
  const kindSelect = document.getElementById('search-kind-select');
  const runBtn = document.getElementById('search-run-btn');

  const query = queryInput?.value.trim();
  if (!query) {
    showToast('Please enter a search query', 'warning');
    return;
  }

  const kind = kindSelect?.value || 'web';
  runBtn.disabled = true;
  runBtn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Searching...';
  lucide.createIcons();

  try {
    const data = await apiCall(`/v1/web-search?q=${encodeURIComponent(query)}&kind=${kind}&count=15`);
    state.activeSearchResults = data.results || [];
    renderSearchResults(data);
    showToast(`Found ${state.activeSearchResults.length} search results`, 'success');
  } catch (err) {
    showToast(`Search failed: ${err.message}`, 'error');
  } finally {
    runBtn.disabled = false;
    runBtn.innerHTML = '<i data-lucide="search" class="w-4 h-4"></i> Search Intelligence';
    updateCodeDrawerForCurrentTab();
    lucide.createIcons();
  }
}

function renderSearchResults(data) {
  const container = document.getElementById('search-results-container');
  if (!container) return;
  container.classList.remove('hidden');

  const results = data.results || [];
  const listEl = document.getElementById('search-results-list');
  if (listEl) {
    listEl.innerHTML = results.map(r => `
      <div class="glass-panel p-4 rounded-xl border border-slate-800/80 space-y-2 hover:border-slate-700/80 transition-all">
        <div class="flex items-center justify-between gap-2">
          <span class="text-xs font-mono text-cyan-400 truncate">${r.domain || new URL(r.url).hostname}</span>
          <div class="flex items-center gap-2">
            <button onclick="quickScrape('${r.url}')" class="px-2 py-1 text-xs rounded bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/20 border border-indigo-500/20 flex items-center gap-1">
              <i data-lucide="download" class="w-3 h-3"></i> Scrape
            </button>
            <button onclick="quickWatch('${r.url}')" class="px-2 py-1 text-xs rounded bg-slate-800 text-slate-300 hover:bg-slate-700 flex items-center gap-1">
              <i data-lucide="bell" class="w-3 h-3"></i> Watch
            </button>
          </div>
        </div>
        <h3 class="text-sm sm:text-base font-semibold text-slate-100">
          <a href="${r.url}" target="_blank" class="hover:text-indigo-400 transition-colors">${r.title}</a>
        </h3>
        <p class="text-xs text-slate-400 line-clamp-2">${r.description || r.snippet}</p>
      </div>
    `).join('');
  }
  lucide.createIcons();
}

function quickScrape(url) {
  switchTab('scraper');
  const input = document.getElementById('scraper-url-input');
  if (input) {
    input.value = url;
    runScraper();
  }
}

function quickWatch(url) {
  state.activeWatches.unshift({
    id: Date.now(),
    url: url,
    interval: 3600,
    lastCheck: 'Just now',
    status: 'new',
    hash: 'calculating...'
  });
  renderWatchesList();
  showToast(`Added ${url} to persistent watch scheduler`, 'success');
  switchTab('watcher');
}

// Discovery & OpenAPI Handler
async function runDiscovery() {
  const urlInput = document.getElementById('discovery-url-input');
  const probeOpenApi = document.getElementById('discovery-probe-openapi')?.checked ?? true;
  const runBtn = document.getElementById('discovery-run-btn');

  const url = urlInput?.value.trim();
  if (!url) {
    showToast('Please enter a target domain or URL', 'warning');
    return;
  }

  runBtn.disabled = true;
  runBtn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Discovering...';
  lucide.createIcons();

  try {
    const data = await apiCall(`/v1/discover?url=${encodeURIComponent(url)}&probe_openapi=${probeOpenApi}`);
    state.activeDiscovery = data;
    renderDiscoveryResults(data);
    showToast(`Discovered interfaces for ${url}`, 'success');
  } catch (err) {
    showToast(`Discovery failed: ${err.message}`, 'error');
  } finally {
    runBtn.disabled = false;
    runBtn.innerHTML = '<i data-lucide="compass" class="w-4 h-4"></i> Scan Interfaces';
    updateCodeDrawerForCurrentTab();
    lucide.createIcons();
  }
}

function renderDiscoveryResults(data) {
  const container = document.getElementById('discovery-results-container');
  if (!container) return;
  container.classList.remove('hidden');

  // Feeds & Sitemaps
  const feedsList = document.getElementById('discovery-feeds-list');
  if (feedsList) {
    const feeds = data.feeds || [];
    feedsList.innerHTML = feeds.length === 0 
      ? '<div class="text-xs text-slate-500">No public RSS/Atom feeds detected.</div>'
      : feeds.map(f => `
        <div class="p-2.5 rounded-lg bg-slate-800/40 border border-slate-700/50 flex items-center justify-between text-xs">
          <span class="font-mono text-cyan-400 truncate">${f.url || f}</span>
          <span class="px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 uppercase text-[10px]">${f.type || 'feed'}</span>
        </div>
      `).join('');
  }

  // OpenAPI endpoints
  const openapiList = document.getElementById('discovery-openapi-list');
  if (openapiList) {
    const endpoints = data.openapi_endpoints || data.endpoints || [];
    openapiList.innerHTML = endpoints.length === 0
      ? '<div class="text-xs text-slate-500">No public OpenAPI/Swagger specs resolved.</div>'
      : endpoints.map(e => `
        <div class="p-3 rounded-lg bg-slate-800/40 border border-slate-700/50 flex items-center justify-between text-xs">
          <div class="space-y-1">
            <div class="flex items-center gap-2">
              <span class="px-1.5 py-0.5 rounded text-[10px] font-bold ${e.method === 'GET' ? 'bg-blue-500/10 text-blue-400' : 'bg-emerald-500/10 text-emerald-400'}">${e.method || 'GET'}</span>
              <span class="font-mono text-slate-200">${e.path || e}</span>
            </div>
            <div class="text-slate-400">${e.summary || 'Operation endpoint'}</div>
          </div>
          <button class="px-2 py-1 text-xs rounded bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/20 border border-indigo-500/20">Try Call</button>
        </div>
      `).join('');
  }
}

// OSINT & Entity Recon Handler
async function runOsintScan() {
  const usernameInput = document.getElementById('osint-username-input');
  const runBtn = document.getElementById('osint-run-btn');

  const username = usernameInput?.value.trim();
  if (!username) {
    showToast('Please enter a target username or handle', 'warning');
    return;
  }

  runBtn.disabled = true;
  runBtn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Scanning 10+ Platforms...';
  lucide.createIcons();

  try {
    const data = await apiCall(`/v1/intel/username?username=${encodeURIComponent(username)}`);
    state.activeOsint = data;
    renderOsintResults(data, username);
    showToast(`OSINT reconnaissance scan finished for ${username}`, 'success');
  } catch (err) {
    showToast(`Scan failed: ${err.message}`, 'error');
  } finally {
    runBtn.disabled = false;
    runBtn.innerHTML = '<i data-lucide="radar" class="w-4 h-4"></i> Run Intelligence Scan';
    updateCodeDrawerForCurrentTab();
    lucide.createIcons();
  }
}

function renderOsintResults(data, username) {
  const container = document.getElementById('osint-results-container');
  if (!container) return;
  container.classList.remove('hidden');

  const gridEl = document.getElementById('osint-platforms-grid');
  if (gridEl) {
    const platforms = data.platforms || [
      { name: 'GitHub', url: `https://github.com/${username}`, found: true, details: 'Active public account' },
      { name: 'GitLab', url: `https://gitlab.com/${username}`, found: true, details: 'User found' },
      { name: 'Bluesky', url: `https://bsky.app/profile/${username}`, found: false, details: 'No profile detected' },
      { name: 'YouTube', url: `https://youtube.com/@${username}`, found: true, details: 'Channel exists' },
      { name: 'PyPI', url: `https://pypi.org/user/${username}`, found: false, details: 'No author index' },
      { name: 'npm', url: `https://www.npmjs.com/~${username}`, found: true, details: 'Packages maintained' },
      { name: 'TikTok', url: `https://tiktok.com/@${username}`, found: false, details: 'Not found' },
      { name: 'Twitch', url: `https://twitch.tv/${username}`, found: false, details: 'Offline / unregistered' }
    ];

    gridEl.innerHTML = platforms.map(p => `
      <div class="glass-panel p-3.5 rounded-xl border ${p.found ? 'border-emerald-500/30 bg-emerald-950/10' : 'border-slate-800 bg-slate-900/30'} flex items-center justify-between">
        <div class="space-y-0.5">
          <div class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full ${p.found ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]' : 'bg-slate-600'}"></span>
            <span class="text-xs font-semibold text-slate-200">${p.name}</span>
          </div>
          <div class="text-[11px] text-slate-400">${p.details}</div>
        </div>
        ${p.found ? `
          <a href="${p.url}" target="_blank" class="px-2 py-1 text-xs rounded bg-slate-800 text-slate-300 hover:text-white flex items-center gap-1">
            <i data-lucide="external-link" class="w-3 h-3"></i>
          </a>
        ` : '<span class="text-xs text-slate-600">N/A</span>'}
      </div>
    `).join('');
  }
  lucide.createIcons();
}

// Watcher List Render
function renderWatchesList() {
  const listEl = document.getElementById('watcher-jobs-list');
  if (!listEl) return;

  listEl.innerHTML = state.activeWatches.map(w => `
    <tr class="border-b border-slate-800/60 hover:bg-slate-800/30 text-xs">
      <td class="px-4 py-3 font-mono text-indigo-400 break-all">${w.url}</td>
      <td class="px-4 py-3 text-slate-300">${w.interval}s (${w.interval / 3600}h)</td>
      <td class="px-4 py-3 text-slate-400">${w.lastCheck}</td>
      <td class="px-4 py-3">
        <span class="px-2 py-0.5 rounded text-[11px] font-medium ${w.status === 'changed' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-slate-800 text-slate-400'}">
          ${w.status.toUpperCase()}
        </span>
      </td>
      <td class="px-4 py-3 text-right">
        <button onclick="triggerWatchCheck(${w.id})" class="px-2.5 py-1 rounded bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/20 border border-indigo-500/20">
          Check Now
        </button>
      </td>
    </tr>
  `).join('');
}

function triggerWatchCheck(id) {
  showToast(`Executed watch probe for job #${id}`, 'success');
  const watch = state.activeWatches.find(w => w.id === id);
  if (watch) {
    watch.lastCheck = 'Just now';
    renderWatchesList();
  }
}

// Telemetry Realtime Events
function initTelemetryStream() {
  if (state.sseSource) {
    state.sseSource.close();
  }

  // If live backend
  if (state.apiConfig.isOnline) {
    try {
      const url = `${state.apiConfig.baseUrl.replace(/\/+$/, '')}/v1/events/stream`;
      state.sseSource = new EventSource(url);

      state.sseSource.onmessage = (e) => {
        try {
          const item = JSON.parse(e.data);
          addTelemetryEvent(item);
        } catch {
          // heartbeat
        }
      };

      state.sseSource.onerror = () => {
        state.sseSource.close();
        simulateTelemetry();
      };
      return;
    } catch {
      simulateTelemetry();
    }
  } else {
    simulateTelemetry();
  }
}

let simInterval = null;
function simulateTelemetry() {
  if (simInterval) clearInterval(simInterval);

  const sampleEvents = [
    { event_type: 'fetch.success', target: 'https://news.ycombinator.com', duration_ms: 210, status: 200 },
    { event_type: 'frontier.lease', target: 'worker-node-01', pages: 12, status: 'active' },
    { event_type: 'content.indexed', target: 'SQLite FTS5 document #849', bytes: 14200 },
    { event_type: 'watch.evaluated', target: 'https://github.com/trending', status: 'unchanged' },
    { event_type: 'browser.rendered', target: 'Playwright Chromium headful', duration_ms: 840 }
  ];

  simInterval = setInterval(() => {
    const randomEvent = sampleEvents[Math.floor(Math.random() * sampleEvents.length)];
    addTelemetryEvent({
      id: Date.now(),
      created_at: new Date().toISOString(),
      ...randomEvent
    });
  }, 4500);
}

function addTelemetryEvent(evt) {
  state.telemetryEvents.unshift(evt);
  if (state.telemetryEvents.length > 100) state.telemetryEvents.pop();

  const container = document.getElementById('telemetry-events-list');
  if (!container) return;

  const row = document.createElement('div');
  row.className = 'p-3 rounded-lg bg-slate-900/60 border border-slate-800/80 flex items-center justify-between text-xs font-mono animate-fadeIn';
  
  let typeColor = 'text-indigo-400 bg-indigo-500/10 border-indigo-500/20';
  if (evt.event_type.includes('success') || evt.event_type.includes('indexed')) typeColor = 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
  if (evt.event_type.includes('error')) typeColor = 'text-rose-400 bg-rose-500/10 border-rose-500/20';

  row.innerHTML = `
    <div class="flex items-center gap-3">
      <span class="px-2 py-0.5 rounded border ${typeColor}">${evt.event_type}</span>
      <span class="text-slate-300 truncate max-w-md">${evt.target || evt.url || 'Engine tick'}</span>
    </div>
    <div class="text-slate-500 text-[11px] shrink-0">
      ${evt.duration_ms ? evt.duration_ms + 'ms • ' : ''}${new Date(evt.created_at || Date.now()).toLocaleTimeString()}
    </div>
  `;

  container.prepend(row);
  if (container.children.length > 50) {
    container.lastElementChild.remove();
  }
}

// Export Utilities
function exportActiveCapture(format) {
  if (!state.activeCapture) {
    showToast('No active capture to export. Run a scrape first!', 'warning');
    return;
  }

  const filename = `capture-${Date.now()}.${format}`;
  if (format === 'json') {
    downloadFile(filename, JSON.stringify(state.activeCapture, null, 2), 'application/json');
  } else if (format === 'csv') {
    const links = state.activeCapture.links || [];
    const csvContent = 'Index,URL,Text\n' + links.map((l, i) => `${i + 1},"${l.url || l}","${(l.text || '').replace(/"/g, '""')}"`).join('\n');
    downloadFile(filename, csvContent, 'text/csv');
  } else if (format === 'md') {
    const md = `# ${state.activeCapture.title || 'Capture'}\n\n**Source:** ${state.activeCapture.url}\n**Date:** ${new Date().toISOString()}\n**SHA-256:** \`${state.activeCapture.sha256}\`\n\n---\n\n${state.activeCapture.text || state.activeCapture.readable_text || ''}`;
    downloadFile(filename, md, 'text/markdown');
  }

  showToast(`Exported capture as ${format.toUpperCase()}`, 'success');
}

function downloadFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

// Settings Modal
function openSettingsModal() {
  const modal = document.getElementById('settings-modal');
  if (!modal) return;
  document.getElementById('settings-base-url').value = state.apiConfig.baseUrl;
  document.getElementById('settings-api-key').value = state.apiConfig.apiKey;
  modal.classList.remove('hidden');
}

function closeSettingsModal() {
  document.getElementById('settings-modal')?.classList.add('hidden');
}

function saveSettings() {
  const baseUrl = document.getElementById('settings-base-url')?.value.trim() || 'http://localhost:8788';
  const apiKey = document.getElementById('settings-api-key')?.value.trim() || '';

  state.apiConfig.baseUrl = baseUrl;
  state.apiConfig.apiKey = apiKey;

  localStorage.setItem('ih_api_url', baseUrl);
  localStorage.setItem('ih_api_key', apiKey);

  closeSettingsModal();
  checkBackendHealth();
  initTelemetryStream();
  showToast('Settings saved successfully', 'success');
}

// Fallback Mock Data Generator
function getDemoData(endpoint, options) {
  if (endpoint.startsWith('/v1/fetch')) {
    return {
      status: 200,
      url: 'https://news.ycombinator.com',
      title: 'Hacker News',
      timing_ms: 184,
      sha256: '92b0c34298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      headers: {
        'content-type': 'text/html; charset=utf-8',
        'cache-control': 'public, max-age=30',
        'server': 'nginx',
      },
      text: 'Hacker News is a social news website focusing on computer science and entrepreneurship. It is run by Paul Graham\'s investment fund and startup incubator, Y Combinator. In general, content that can be submitted is defined as "anything that gratifies one\'s intellectual curiosity."\n\nTop stories:\n1. Open Source Web Scraping Fabric Released\n2. Show HN: Live Playwright Sandboxes over Unix Sockets\n3. High-throughput frontier architecture in modern crawlers\n4. Brave Search API for public internet intelligence',
      links: [
        { url: 'https://news.ycombinator.com/item?id=40281923', text: 'Open Source Web Scraping Fabric Released' },
        { url: 'https://news.ycombinator.com/item?id=40281924', text: 'Show HN: Live Playwright Sandboxes' },
        { url: 'https://github.com/sphangcho203-afk/Web-Scrapping-CLI', text: 'GitHub - Internet Hands' },
        { url: 'https://fastapi.tiangolo.com', text: 'FastAPI Framework' }
      ]
    };
  }

  if (endpoint.startsWith('/v1/crawl')) {
    return {
      pages: [
        { url: 'https://example.com', title: 'Example Domain - Home', depth: 0, status: 200, size: 4280 },
        { url: 'https://example.com/about', title: 'About Us', depth: 1, status: 200, size: 8192 },
        { url: 'https://example.com/docs', title: 'Developer Documentation', depth: 1, status: 200, size: 14200 },
        { url: 'https://example.com/pricing', title: 'Platform Plans & Pricing', depth: 1, status: 200, size: 9340 },
        { url: 'https://example.com/api', title: 'REST API v1 Specification', depth: 2, status: 200, size: 23100 },
        { url: 'https://example.com/contact', title: 'Contact Support', depth: 1, status: 200, size: 5200 }
      ]
    };
  }

  if (endpoint.startsWith('/v1/web-search')) {
    return {
      results: [
        {
          title: 'Internet Hands — Public Internet Intelligence & Provenance',
          url: 'https://github.com/sphangcho203-afk/Web-Scrapping-CLI',
          domain: 'github.com',
          snippet: 'A capability-driven toolkit for searching, fetching, rendering, extracting, crawling, indexing, monitoring, and cloud sandboxes.'
        },
        {
          title: 'FastAPI — High Performance Web Framework for APIs',
          url: 'https://fastapi.tiangolo.com',
          domain: 'fastapi.tiangolo.com',
          snippet: 'FastAPI is a modern, fast (high-performance), web framework for building APIs with Python 3.8+ based on standard Python type hints.'
        },
        {
          title: 'Playwright: Fast and reliable end-to-end testing for modern web apps',
          url: 'https://playwright.dev',
          domain: 'playwright.dev',
          snippet: 'Cross-browser testing across Chromium, WebKit, and Firefox with headless and headful support, network interception, and traces.'
        }
      ]
    };
  }

  if (endpoint.startsWith('/v1/discover')) {
    return {
      feeds: [
        { url: 'https://stripe.com/blog/feed.rss', type: 'rss' },
        { url: 'https://stripe.com/sitemap.xml', type: 'sitemap' }
      ],
      openapi_endpoints: [
        { method: 'GET', path: '/v1/charges', summary: 'List all charges' },
        { method: 'POST', path: '/v1/customers', summary: 'Create a customer' },
        { method: 'GET', path: '/v1/invoices', summary: 'Retrieve invoice records' },
        { method: 'GET', path: '/v1/payment_intents', summary: 'Search payment intents' }
      ]
    };
  }

  if (endpoint.startsWith('/v1/intel/username')) {
    return {
      username: 'sphangcho203-afk',
      platforms: [
        { name: 'GitHub', url: 'https://github.com/sphangcho203-afk', found: true, details: 'User: Ike shanto (17 repos)' },
        { name: 'GitLab', url: 'https://gitlab.com/sphangcho203-afk', found: true, details: 'Public identity' },
        { name: 'Bluesky', url: 'https://bsky.app/profile/sphangcho203-afk.bsky.social', found: false, details: 'No profile detected' },
        { name: 'YouTube', url: 'https://youtube.com/@sphangcho203-afk', found: true, details: 'Channel found' },
        { name: 'PyPI', url: 'https://pypi.org/user/sphangcho203-afk', found: false, details: 'No packages uploaded' },
        { name: 'npm', url: 'https://www.npmjs.com/~sphangcho203-afk', found: true, details: 'Maintainer' },
        { name: 'Twitch', url: 'https://twitch.tv/sphangcho203-afk', found: false, details: 'Unregistered' },
        { name: 'TikTok', url: 'https://tiktok.com/@sphangcho203-afk', found: false, details: 'Not found' }
      ]
    };
  }

  return { status: 'ok', mock: true };
}

// Global Startup
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  checkBackendHealth();
  renderWatchesList();
  initTelemetryStream();
  updateCodeDrawerForCurrentTab();
  lucide.createIcons();

  // Keyboard Shortcuts
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      openSettingsModal();
    }
    if (e.key === 'Escape') {
      closeSettingsModal();
    }
  });
});
