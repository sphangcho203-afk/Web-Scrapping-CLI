/* OpenCrawl dimensional surfaces. Event delegation survives route changes. */
(() => {
  'use strict';
  const surfaces = '.ih-command-stats>div,.oc-overview-composer,.ih-run-demo,.ihx-public-plan-grid>article';
  const enabled = matchMedia('(min-width:901px) and (hover:hover) and (pointer:fine) and (prefers-reduced-motion:no-preference)');
  const properties = ['--oc-depth-x','--oc-depth-y','--oc-light-x','--oc-light-y'];
  let active = null, frame = 0, point = null;

  const reset = () => {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    if (active) properties.forEach(name => active.style.removeProperty(name));
    active = null;
    point = null;
  };

  document.addEventListener('pointermove', event => {
    const surface = event.target.closest?.(surfaces);
    if (!enabled.matches || event.pointerType === 'touch' || !surface || surface.contains(document.activeElement)) {
      reset();
      return;
    }
    if (surface !== active) { reset(); active = surface; }
    point = {x:event.clientX,y:event.clientY};
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (!active?.isConnected || !enabled.matches || active.contains(document.activeElement)) { reset(); return; }
      const rect = active.getBoundingClientRect();
      if (!rect.width || !rect.height) { reset(); return; }
      const x = Math.max(0,Math.min(1,(point.x-rect.left)/rect.width));
      const y = Math.max(0,Math.min(1,(point.y-rect.top)/rect.height));
      const strength = active.classList.contains('ih-run-demo') ? 2 : active.classList.contains('oc-overview-composer') ? .65 : 1.2;
      active.style.setProperty('--oc-depth-x',((.5-y)*2*strength).toFixed(2)+'deg');
      active.style.setProperty('--oc-depth-y',((x-.5)*2*strength).toFixed(2)+'deg');
      active.style.setProperty('--oc-light-x',(x*100).toFixed(1)+'%');
      active.style.setProperty('--oc-light-y',(y*100).toFixed(1)+'%');
    });
  }, {passive:true});
  document.addEventListener('pointerout', event => {
    if (active && (!(event.relatedTarget instanceof Node) || !active.contains(event.relatedTarget))) reset();
  }, {passive:true});
  document.addEventListener('focusin', () => {
    if (active?.contains(document.activeElement)) reset();
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) reset(); });
  window.addEventListener('blur', reset);
  if (enabled.addEventListener) enabled.addEventListener('change', reset);
  else enabled.addListener(reset);
})();
