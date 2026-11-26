// Injected into the main window and its popups (the server's web UI). WebKit
// in this app does not open `<a target="_blank">` links on its own, while
// `window.open` works, so a plain left click on such a link calls it. The
// shell then decides where the link opens (a popup for server pages, the
// browser for others). Clicks the page handles itself are left alone.
(() => {
  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!link || link.target !== "_blank" || link.hasAttribute("download")) return;
    event.preventDefault();
    window.open(link.href, "_blank");
  });
})();
