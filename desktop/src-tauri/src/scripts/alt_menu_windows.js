(() => {
  if (window.__ONYX_ALT_MENU_HANDLER__) return;
  window.__ONYX_ALT_MENU_HANDLER__ = true;

  let altPressedAlone = false;

  document.addEventListener('keydown', (e) => {
    altPressedAlone = e.key === 'Alt' && !e.repeat;
  }, true);

  document.addEventListener('keyup', (e) => {
    if (e.key !== 'Alt' || !altPressedAlone) return;
    altPressedAlone = false;
    e.preventDefault();
    const invoke =
      window.__TAURI__?.core?.invoke || window.__TAURI_INTERNALS__?.invoke;
    if (typeof invoke === 'function') invoke('toggle_menu_bar').catch(() => {});
  }, true);
})();
