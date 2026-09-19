(() => {
  if (window.__ONYX_CONSOLE_CAPTURE__) return;
  window.__ONYX_CONSOLE_CAPTURE__ = true;

  const levels = ['log', 'warn', 'error', 'info', 'debug'];
  const originals = {};

  levels.forEach(level => {
    originals[level] = console[level];
    console[level] = function(...args) {
      originals[level].apply(console, args);
      try {
        const invoke =
          window.__TAURI__?.core?.invoke || window.__TAURI_INTERNALS__?.invoke;
        if (typeof invoke === 'function') {
          const message = args.map(a => {
            try { return typeof a === 'string' ? a : JSON.stringify(a); }
            catch { return String(a); }
          }).join(' ');
          invoke('log_from_frontend', { level, message }).catch(() => {});
        }
      } catch {}
    };
  });

  window.addEventListener('error', (event) => {
    try {
      const invoke =
        window.__TAURI__?.core?.invoke || window.__TAURI_INTERNALS__?.invoke;
      if (typeof invoke === 'function') {
        invoke('log_from_frontend', {
          level: 'error',
          message: `[uncaught] ${event.message} at ${event.filename}:${event.lineno}:${event.colno}`
        }).catch(() => {});
      }
    } catch {}
  });

  window.addEventListener('unhandledrejection', (event) => {
    try {
      const invoke =
        window.__TAURI__?.core?.invoke || window.__TAURI_INTERNALS__?.invoke;
      if (typeof invoke === 'function') {
        invoke('log_from_frontend', {
          level: 'error',
          message: `[unhandled rejection] ${event.reason}`
        }).catch(() => {});
      }
    } catch {}
  });
})();
