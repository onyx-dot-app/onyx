import { showErrorModal, showAuthModal } from "../utils/error-modal.js";
import {
  ACTIONS,
  EXTENSION_MESSAGE,
  WEB_MESSAGE,
  STORAGE_KEYS,
  SIDEBAR_PATH,
} from "../utils/constants.js";

(function () {
  const iframe = document.getElementById("onyx-sidebar-iframe");
  const loadingScreen = document.getElementById("loading-screen");

  let currentUrl = "";
  let iframeLoaded = false;
  let iframeLoadTimeout;
  let authRequired = false;

  async function checkPendingInput() {
    try {
      const result = await browser.storage.session.get("pendingInput");
      if (result.pendingInput) {
        const { url, pageUrl, timestamp } = result.pendingInput;
        if (Date.now() - timestamp < 5000) {
          setIframeSrc(url, pageUrl);
          await browser.storage.session.remove("pendingInput");
          return true;
        }
        await browser.storage.session.remove("pendingInput");
      }
    } catch (error) {
      console.error("[Onyx Sidebar] Error checking pending input:", error);
    }
    return false;
  }

  async function initializeSidebar() {
    loadingScreen.style.display = "flex";
    loadingScreen.style.opacity = "1";
    iframe.style.opacity = "0";

    // Check for pending input first (from selection icon click)
    const hasPendingInput = await checkPendingInput();
    if (!hasPendingInput) {
      loadOnyxDomain();
    }
  }

  function setIframeSrc(url, pageUrl) {
    iframe.src = url;
    currentUrl = pageUrl;
  }

  function sendWebsiteToIframe(pageUrl) {
    if (iframe.contentWindow && pageUrl !== currentUrl) {
      iframe.contentWindow.postMessage(
        {
          type: WEB_MESSAGE.PAGE_CHANGE,
          url: pageUrl,
        },
        "*",
      );
      currentUrl = pageUrl;
    }
  }

  function startIframeLoadTimeout() {
    iframeLoadTimeout = setTimeout(() => {
      if (!iframeLoaded) {
        if (authRequired) {
          showAuthModal();
        } else {
          showErrorModal(iframe.src);
        }
      }
    }, 2500);
  }

  function handleMessage(event) {
    if (event.data.type === EXTENSION_MESSAGE.ONYX_APP_LOADED) {
      clearTimeout(iframeLoadTimeout);
      iframeLoaded = true;
      showIframe();
      if (iframe.contentWindow) {
        iframe.contentWindow.postMessage({ type: "PANEL_READY" }, "*");
      }
    } else if (event.data.type === EXTENSION_MESSAGE.AUTH_REQUIRED) {
      authRequired = true;
    }
  }

  function showIframe() {
    iframe.style.opacity = "1";
    loadingScreen.style.opacity = "0";
    setTimeout(() => {
      loadingScreen.style.display = "none";
    }, 500);
  }

  async function loadOnyxDomain() {
    const response = await browser.runtime.sendMessage({
      action: ACTIONS.GET_CURRENT_ONYX_DOMAIN,
    });
    if (response && response[STORAGE_KEYS.ONYX_DOMAIN]) {
      setIframeSrc(response[STORAGE_KEYS.ONYX_DOMAIN] + SIDEBAR_PATH, "");
    } else {
      console.warn("Onyx domain not found, using default");
      const result = await browser.storage.local.get({
        [STORAGE_KEYS.ONYX_DOMAIN]: "http://localhost:3000",
      });
      setIframeSrc(result[STORAGE_KEYS.ONYX_DOMAIN] + SIDEBAR_PATH, "");
    }
  }

  browser.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === ACTIONS.OPEN_ONYX_WITH_INPUT) {
      setIframeSrc(request.url, request.pageUrl);
    } else if (request.action === ACTIONS.UPDATE_PAGE_URL) {
      sendWebsiteToIframe(request.pageUrl);
    }
  });

  window.addEventListener("message", handleMessage);

  initializeSidebar();
  startIframeLoadTimeout();
})();
