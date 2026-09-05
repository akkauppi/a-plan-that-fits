// GitHub Pages cannot set COOP/COEP headers. The same-origin service worker
// enables them before a solver worker is created. Never create a reload loop.
let isolationReloadPending = false;
window.coi = {
  quiet: true,
  coepCredentialless: () => false,
  shouldRegister: () => !window.crossOriginIsolated,
  doReload: async () => {
    const key = 'z3-map-isolation-reload';
    if (isolationReloadPending || sessionStorage.getItem(key)) return;
    isolationReloadPending = true;
    // updatefound fires before installation finishes. Reload only after the
    // worker can actually intercept navigation, including on a cold visit.
    await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) await new Promise(resolve => {
      navigator.serviceWorker.addEventListener('controllerchange', resolve, { once: true });
    });
    sessionStorage.setItem(key, '1');
    window.location.reload();
  },
};
if (window.crossOriginIsolated) sessionStorage.removeItem('z3-map-isolation-reload');
