(() => {
  const overviewPath = () => location.pathname === '/dashboard' || location.pathname === '/dashboard/';

  function migrateOverview() {
    if (!overviewPath()) return;
    const content = document.querySelector('.content');
    if (!content || content.dataset.ihOverview === '1') return;

    const head = content.querySelector(':scope > .page-head');
    const stats = content.querySelector(':scope > .stats-grid');
    const dashboard = content.querySelector(':scope > .dashboard-grid');
    const quick = content.querySelector(':scope > .quick-card');
    if (!head || !stats || !dashboard || !quick) return;

    content.dataset.ihOverview = '1';
    content.classList.add('ih-page-shell', 'ih-overview');

    head.classList.add('ih-page-header');
    head.firstElementChild?.classList.add('ih-page-heading');
    head.querySelector('.overline')?.classList.add('ih-eyebrow');
    head.querySelector('h1')?.classList.add('ih-title');
    head.querySelector('p')?.classList.add('ih-subtitle');
    if (head.lastElementChild && head.lastElementChild !== head.firstElementChild) {
      head.lastElementChild.classList.add('ih-status');
      head.lastElementChild.dataset.tone = 'success';
    }

    stats.classList.add('ih-grid', 'ih-grid--4', 'ih-overview-metrics');
    stats.querySelectorAll(':scope > .stat-card').forEach(card => {
      card.classList.add('ih-panel', 'ih-overview-metric');
      card.querySelector(':scope > span')?.classList.add('ih-metric-label');
      card.querySelector(':scope > b')?.classList.add('ih-metric-value');
      card.querySelector(':scope > small')?.classList.add('ih-muted');
    });

    dashboard.classList.add('ih-grid', 'ih-grid--2', 'ih-overview-main');
    dashboard.querySelectorAll(':scope > .card').forEach(card => card.classList.add('ih-panel'));
    quick.classList.add('ih-panel', 'ih-overview-quick');
  }

  const observer = new MutationObserver(migrateOverview);
  observer.observe(document.getElementById('app'), { childList: true, subtree: true });
  addEventListener('popstate', () => queueMicrotask(migrateOverview));
  migrateOverview();
})();
