// Lets an Onyx page ask the extension to connect now (for example after an
// admin turns on the user's Chrome). The service worker checks the origin.
(function () {
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.type !== "onyx:browser-wake") return;
    chrome.runtime.sendMessage({ action: "onyxBrowserWake" }).catch(() => {});
  });
})();
