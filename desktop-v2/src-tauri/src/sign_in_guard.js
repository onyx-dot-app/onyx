// Injected into the main window only (the server's web UI). The web app moves
// to its login page with the history API (for example after sign-out), which
// the shell's navigation hook does not see. Reload that URL as a document
// navigation, so the shell can show its own sign-in window instead of the web
// sign-in, which would finish in the system browser and never reach the app.
(() => {
  const SIGN_IN = /^\/auth\/(login|signup)\/?$/;
  let reloading = false;
  const check = () => {
    if (reloading || !SIGN_IN.test(window.location.pathname)) return;
    reloading = true;
    window.location.replace(window.location.href);
  };
  for (const method of ["pushState", "replaceState"]) {
    const original = history[method];
    history[method] = function (...args) {
      const result = original.apply(this, args);
      check();
      return result;
    };
  }
  window.addEventListener("popstate", check);
})();
