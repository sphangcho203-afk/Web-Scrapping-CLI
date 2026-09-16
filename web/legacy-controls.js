/* Restore the original control-plane information architecture and flows
 * inside the current editorial UI. This file intentionally loads last.
 */
(() => {
  const fullNav = [
    ['Workspace', [
      ['overview','overview','Overview'],
      ['usage','activity','Usage'],
      ['api-keys','key','API keys'],
      ['monitors','monitor','Monitors'],
      ['integrations','plug','Integrations']
    ]],
    ['Commercial', [
      ['wallet','wallet','Wallet'],
      ['billing','wallet','Billing & plans']
    ]],
    ['Account', [
      ['settings','settings','Settings & security']
    ]]
  ];

  const hrefFor = slug => `/dashboard${slug === 'overview' ? '' : `/${slug}`}`;

  dashboardShell = function dashboardShellLegacyCompat(active, content) {
    const u = state.me?.user || {};
    const current = fullNav.flatMap(x => x[1]).find(x => x[0] === active);
    const currentTitle = current?.[2] || 'Console';
    const initials = esc((u.display_name || u.email || 'I')[0].toUpperCase());

    app.innerHTML = `<div class="app-shell ih-app-shell">
      <aside class="sidebar ih-sidebar">
        <div class="ih-sidebar-top">${brand()}<span class="ih-console-tag">CONTROL PLANE</span></div>
        <nav>
          ${fullNav.map(([group, items]) => `<div class="nav-group"><span>${group}</span>${items.map(([slug, ico, title]) => `<a class="${slug === active ? 'active' : ''}" data-link href="${hrefFor(slug)}">${icon(ico)}<b>${title}</b></a>`).join('')}</div>`).join('')}
        </nav>
        <div class="ih-sidebar-system">
          <div><span><i class="ih-status-dot ok"></i></span><b>Internet Hands</b><small>Gateway operational</small></div>
          <a data-link href="/status">View status</a>
        </div>
        <div class="sidebar-foot">
          <a data-link href="/docs">${icon('docs')} Docs</a>
          <button id="logout">Sign out</button>
        </div>
      </aside>

      <section class="workspace ih-workspace">
        <header class="topbar ih-topbar">
          <div class="ih-topbar-title">
            <button class="icon-btn mobile-sidebar" data-sidebar-toggle>${icon('menu')}</button>
            <span><small>INTERNET HANDS</small><b>${esc(currentTitle)}</b></span>
          </div>
          <div class="top-actions ih-top-actions">
            <a class="btn small" data-link href="/dashboard/api-keys">${icon('key')} API key</a>
            <a class="btn small" data-link href="/dashboard/integrations">${icon('plug')} Connect</a>
            <button class="account-button" data-account-toggle aria-expanded="false"><i>${initials}</i><b>${esc(u.display_name || u.email || 'Account')}</b>${icon('arrow')}</button>
          </div>
          <div class="ih-account-menu" data-account-menu hidden>
            <a data-link href="/dashboard/settings">${icon('settings')} Settings & security</a>
            <a data-link href="/dashboard/billing">${icon('wallet')} Billing & plans</a>
            <a data-link href="/dashboard/wallet">${icon('wallet')} Wallet</a>
            <a data-link href="/docs">${icon('docs')} Documentation</a>
            <button id="account-logout">Sign out</button>
          </div>
        </header>
        <main class="content ih-content">${content}</main>
      </section>

      <nav class="mobile-bottom ih-mobile-bottom">
        ${[
          ['overview','overview','Home'],
          ['usage','activity','Usage'],
          ['api-keys','key','Keys'],
          ['integrations','plug','Connect'],
          ['more','more','More']
        ].map(([slug, ico, title]) => `<a ${slug === 'more' ? 'data-more' : 'data-link'} href="${slug === 'more' ? '#' : hrefFor(slug)}" class="${slug === active ? 'active' : ''}">${icon(ico)}<span>${title}</span></a>`).join('')}
      </nav>

      <div class="more-sheet" data-more-sheet><i></i><b>All controls</b>
        <a data-link href="/dashboard/monitors">${icon('monitor')} Monitors</a>
        <a data-link href="/dashboard/wallet">${icon('wallet')} Wallet</a>
        <a data-link href="/dashboard/billing">${icon('wallet')} Billing & plans</a>
        <a data-link href="/dashboard/settings">${icon('settings')} Settings & security</a>
        <a data-link href="/docs">${icon('docs')} Documentation</a>
        <a data-link href="/status">${icon('activity')} System status</a>
        <button id="mobile-logout">Sign out</button>
      </div>
      <div class="sheet-backdrop" data-sheet-backdrop></div>
    </div>`;

    bindCommon();

    $('[data-sidebar-toggle]')?.addEventListener('click', () => $('.sidebar')?.classList.toggle('open'));
    $('[data-more]')?.addEventListener('click', e => {
      e.preventDefault();
      $('[data-more-sheet]')?.classList.add('open');
      $('[data-sheet-backdrop]')?.classList.add('open');
    });
    $('[data-sheet-backdrop]')?.addEventListener('click', () => {
      $('[data-more-sheet]')?.classList.remove('open');
      $('[data-sheet-backdrop]')?.classList.remove('open');
    });

    const accountToggle = $('[data-account-toggle]');
    const accountMenu = $('[data-account-menu]');
    accountToggle?.addEventListener('click', e => {
      e.stopPropagation();
      const open = accountMenu?.hasAttribute('hidden');
      if (!accountMenu) return;
      if (open) accountMenu.removeAttribute('hidden'); else accountMenu.setAttribute('hidden','');
      accountToggle.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', e => {
      if (!accountMenu || accountMenu.hasAttribute('hidden')) return;
      if (!accountMenu.contains(e.target) && !accountToggle?.contains(e.target)) {
        accountMenu.setAttribute('hidden','');
        accountToggle?.setAttribute('aria-expanded','false');
      }
    });

    $('#account-logout')?.addEventListener('click', async () => {
      await api('/api/auth/logout', { method: 'POST' });
      state.me = null;
      go('/login');
    });
  };

  // Re-render the current route so the restored shell is active immediately.
  if (location.pathname.startsWith('/dashboard')) renderRoute();
})();
