(() => {
  const AUTH_ROUTES = new Set(['/login', '/signup', '/forgot-password']);

  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link) return;
    const url = new URL(link.href, location.origin);
    if (url.origin !== location.origin || !AUTH_ROUTES.has(url.pathname)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    location.assign(url.pathname + url.search + url.hash);
  }, true);
})();
