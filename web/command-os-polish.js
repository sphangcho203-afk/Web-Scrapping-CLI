/* Command OS public-shell polish.
 * Keeps the existing public navigation behavior while making its state explicit
 * to assistive technology and future route renders.
 */
(() => {
  const upgradePublicNav = () => {
    const toggle = document.querySelector('[data-nav-toggle]');
    const menu = document.querySelector('[data-mobile-menu]');
    if (!toggle || !menu) return;

    if (!menu.id) menu.id = 'ih-public-mobile-menu';
    toggle.setAttribute('aria-controls', menu.id);

    const sync = () => {
      const open = menu.classList.contains('open');
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
    };

    sync();
    if (toggle.dataset.cosA11yBound === 'true') return;
    toggle.dataset.cosA11yBound = 'true';
    toggle.addEventListener('click', () => requestAnimationFrame(sync));
  };

  if (typeof publicShell === 'function') {
    const previousPublicShell = publicShell;
    publicShell = function commandOsPublicShell(...args) {
      const result = previousPublicShell.apply(this, args);
      upgradePublicNav();
      return result;
    };
  }

  upgradePublicNav();
})();
