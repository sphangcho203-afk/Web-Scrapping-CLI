/* Internet Hands brand identity layer.
 * Owns the product mark without changing application behavior.
 */
(() => {
  const LOGO = '/assets/internet-hands-mark.webp';

  const renderBrand = () => `<a class="brand ih-brand cos-brand" data-link href="/" aria-label="Internet Hands home">
    <span class="ih-brand-mark cos-brand-mark"><img src="${LOGO}" width="42" height="42" alt=""></span>
    <span class="ih-wordmark cos-brand-copy"><b>Internet Hands</b><small>CONTROL PLANE</small></span>
  </a>`;

  if (typeof brand !== 'undefined') brand = renderBrand;

  const applyIdentity = () => {
    document.querySelectorAll('img[src="/assets/mark.svg"], .ih-brand img, .cos-brand img, .cos-boot-mark img')
      .forEach(img => {
        if (img.getAttribute('src') !== LOGO) img.setAttribute('src', LOGO);
        img.setAttribute('alt', '');
      });

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
