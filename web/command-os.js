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
    return `<a class="brand ih-brand cos-brand" data-link href="/" aria-label="Internet Hands home">
      <span class="cos-brand-mark"><img src="/assets/mark.svg" width="30" height="30" alt=""></span>
      <span class="cos-brand-copy"><b>Internet Hands</b><small>CONTROL PLANE</small></span>
    </a>`;
  };

  const nav = [
    ['Operate', [
      ['overview','terminal','Command'],
      ['usage','activity','Runs'],
      ['monitors','monitor','Monitors']
    ]],
    ['Connect', [
      ['integrations','plug','Integrations'],
      ['api-keys','key','API keys']
    ]],
    ['Manage', [
      ['wallet','wallet','Credits'],
      ['billing','billing','Billing'],
      ['settings','settings','Settings']
    ]]
  ];

  dashboardShell = function commandOsShell(active, content) {
    const u = state.me?.user || {};
    const current = nav.flatMap(x => x[1]).find(x => x[0] === active);
    const title = current?.[2] || 'Command';
    const initials = esc((u.display_name || u.email || 'I')[0].toUpperCase());

    app.innerHTML = `<div class="cos-app">
      <aside class="cos-sidebar ih-sidebar sidebar">
        <div class="cos-sidebar-brand">${brand()}</div>

        <a class="cos-launch ${active === 'overview' ? 'active' : ''}" data-link href="/dashboard">
          <span>${icon('terminal')}</span><b>Run command</b><kbd>⌘ K</kbd>
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
            <button class="cos-account" data-account-toggle aria-expanded="false"><i>${initials}</i><span><b>${esc(u.display_name || 'Account')}</b><small>${esc(u.email || '')}</small></span>${icon('chevron')}</button>
          </div>
          <div class="cos-account-menu" data-account-menu hidden>
            <div><span class="cos-account-avatar">${initials}</span><span><b>${esc(u.display_name || 'Internet Hands')}</b><small>${esc(u.email || '')}</small></span></div>
            <a data-link href="/dashboard/settings">${icon('settings')} Settings & security</a>
            <a data-link href="/dashboard/billing">${icon('billing')} Billing & plans</a>
            <a data-link href="/dashboard/wallet">${icon('wallet')} Credits</a>
            <a data-link href="/docs">${icon('docs')} Documentation</a>
            <button id="account-logout">Sign out</button>
          </div>
        </header>

        <main class="cos-content content ih-content">${content}</main>
      </section>

      <nav class="cos-mobile-bottom ih-mobile-bottom mobile-bottom">
        ${[
          ['overview','terminal','Command'],
          ['usage','activity','Runs'],
          ['monitors','monitor','Watch'],
          ['integrations','plug','Connect'],
          ['more','more','More']
        ].map(([slug, ico, label]) => `<a ${slug === 'more' ? 'data-more' : 'data-link'} href="${slug === 'more' ? '#' : hrefFor(slug)}" class="${slug === active ? 'active' : ''}">${icon(ico)}<span>${label}</span></a>`).join('')}
      </nav>

      <div class="cos-more-sheet more-sheet" data-more-sheet>
        <div class="cos-sheet-handle"></div><b>Workspace</b>
        <a data-link href="/dashboard/api-keys">${icon('key')} API keys</a>
        <a data-link href="/dashboard/wallet">${icon('wallet')} Credits</a>
        <a data-link href="/dashboard/billing">${icon('billing')} Billing & plans</a>
        <a data-link href="/dashboard/settings">${icon('settings')} Settings & security</a>
        <a data-link href="/docs">${icon('docs')} Documentation</a>
        <a data-link href="/status">${icon('activity')} System status</a>
        <button id="mobile-logout">Sign out</button>
      </div>
      <div class="cos-sheet-backdrop sheet-backdrop" data-sheet-backdrop></div>
    </div>`;

    bindCommon();

    const sidebar = $('.cos-sidebar');
    const sheet = $('[data-more-sheet]');
    const backdrop = $('[data-sheet-backdrop]');
    $('[data-sidebar-toggle]')?.addEventListener('click', () => sidebar?.classList.toggle('open'));
    $('[data-more]')?.addEventListener('click', e => {
      e.preventDefault();
      sheet?.classList.add('open');
      backdrop?.classList.add('open');
    });
    backdrop?.addEventListener('click', () => {
      sheet?.classList.remove('open');
      backdrop?.classList.remove('open');
      sidebar?.classList.remove('open');
    });

    const accountToggle = $('[data-account-toggle]');
    const accountMenu = $('[data-account-menu]');
    accountToggle?.addEventListener('click', e => {
      e.stopPropagation();
      if (!accountMenu) return;
      const opening = accountMenu.hasAttribute('hidden');
      if (opening) accountMenu.removeAttribute('hidden'); else accountMenu.setAttribute('hidden','');
      accountToggle.setAttribute('aria-expanded', String(opening));
    });

    if (window.__ihAccountCloser) document.removeEventListener('click', window.__ihAccountCloser);
    window.__ihAccountCloser = e => {
      if (!accountMenu || accountMenu.hasAttribute('hidden')) return;
      if (!accountMenu.contains(e.target) && !accountToggle?.contains(e.target)) {
        accountMenu.setAttribute('hidden','');
        accountToggle?.setAttribute('aria-expanded','false');
      }
    };
    document.addEventListener('click', window.__ihAccountCloser);

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

  if (location.pathname.startsWith('/dashboard')) renderRoute();
})();