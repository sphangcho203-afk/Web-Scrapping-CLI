(() => {
  const AUTH_ROUTES = new Set(['/login', '/signup', '/forgot-password']);
  let githubStateApplied = false;

  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link) return;
    const url = new URL(link.href, location.origin);
    if (url.origin !== location.origin || !AUTH_ROUTES.has(url.pathname)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    location.assign(url.pathname + url.search + url.hash);
  }, true);

  async function applyGithubState() {
    if (githubStateApplied) return;
    const button = document.querySelector('.github-btn');
    if (!button) return;
    try {
      const response = await fetch('/api/status', { credentials: 'include', cache: 'no-store' });
      if (!response.ok) return;
      const status = await response.json();
      if (status.github_oauth) {
        githubStateApplied = true;
        return;
      }
      githubStateApplied = true;
      button.textContent = 'GitHub unavailable in this Preview';
      button.setAttribute('aria-disabled', 'true');
      button.removeAttribute('href');
      button.style.opacity = '0.62';
      button.style.cursor = 'not-allowed';
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopImmediatePropagation();
      }, true);
    } catch {
      // Keep the normal GitHub link if status probing itself fails.
    }
  }

  const observer = new MutationObserver(() => {
    if (!githubStateApplied) void applyGithubState();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  void applyGithubState();
})();
