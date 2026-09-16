/* Internet Hands exact brand artwork integration.
 * Keeps the selected logo untouched and removes duplicate external wordmarks.
 */
(() => {
  const LOGO = '/assets/internet-hands-logo.webp';

  const renderBrand = () => `<a class="brand ih-brand cos-brand ih-logo-only" data-link href="/" aria-label="Internet Hands home">
    <img class="ih-brand-art" src="${LOGO}" alt="">
  </a>`;

  if (typeof brand !== 'undefined') brand = renderBrand;

  const normalizeBrand = el => {
    const img = el.querySelector(':scope > .ih-brand-art');
    const alreadyClean = el.classList.contains('ih-logo-only') && el.children.length === 1 && img?.getAttribute('src') === LOGO;
    if (alreadyClean) return;
    el.classList.add('ih-logo-only');
    el.innerHTML = `<img class="ih-brand-art" src="${LOGO}" alt="">`;
  };

  const normalizeBoot = el => {
    const img = el.querySelector(':scope > .ih-boot-art');
    if (el.children.length === 1 && img?.getAttribute('src') === LOGO) return;
    el.innerHTML = `<img class="ih-boot-art" src="${LOGO}" alt="Internet Hands">`;
  };

  const applyIdentity = () => {
    document.querySelectorAll('.ih-brand, .cos-brand').forEach(normalizeBrand);
    document.querySelectorAll('.cos-boot-mark').forEach(normalizeBoot);

    const favicon = document.querySelector('link[rel~="icon"]');
    if (favicon) {
      favicon.setAttribute('href', LOGO);
      favicon.setAttribute('type', 'image/webp');
    }
  };

  applyIdentity();
  const observer = new MutationObserver(applyIdentity);
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();
