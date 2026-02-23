import { showErrorModal, showAuthModal } from "../utils/error-modal.js";
import {
  ACTIONS,
  CHROME_MESSAGE,
  WEB_MESSAGE,
  CHROME_SPECIFIC_STORAGE_KEYS,
  SIDE_PANEL_PATH,
} from "../utils/constants.js";
(function () {
  const iframe = document.getElementById("onyx-panel-iframe");
  const loadingScreen = document.getElementById("loading-screen");

  let currentUrl = "";
  let iframeLoaded = false;
  let iframeLoadTimeout;
  let authRequired = false;

  // Returns the origin of the Onyx app loaded in the iframe.
  // Using "*" is unsafe; we derive the origin from iframe.src instead so
  // postMessage payloads (including tab URLs) are only delivered to the
  // expected page.
  function getIframeOrigin() {
    try {
      return new URL(iframe.src).origin;
    } catch {
      return "*";
    }
  }

  async function checkPendingInput() {
    try {
      const result = await chrome.storage.session.get("pendingInput");
      if (result.pendingInput) {
        const { url, pageUrl, timestamp } = result.pendingInput;
        if (Date.now() - timestamp < 5000) {
          setIframeSrc(url, pageUrl);
          await chrome.storage.session.remove("pendingInput");
          return true;
        }
        await chrome.storage.session.remove("pendingInput");
      }
    } catch (error) {
      console.error("[Onyx Panel] Error checking pending input:", error);
    }
    return false;
  }

  async function initializePanel() {
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
        getIframeOrigin(),
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
    // Only trust messages from the Onyx app iframe
    if (event.source !== iframe.contentWindow) return;
    if (event.data.type === CHROME_MESSAGE.ONYX_APP_LOADED) {
      clearTimeout(iframeLoadTimeout);
      iframeLoaded = true;
      showIframe();
      if (iframe.contentWindow) {
        iframe.contentWindow.postMessage(
          { type: "PANEL_READY" },
          getIframeOrigin(),
        );
      }
    } else if (event.data.type === CHROME_MESSAGE.AUTH_REQUIRED) {
      authRequired = true;
    } else if (event.data.type === CHROME_MESSAGE.TAB_READING_ENABLED) {
      chrome.runtime.sendMessage({ action: ACTIONS.TAB_READING_ENABLED });
    } else if (event.data.type === CHROME_MESSAGE.TAB_READING_DISABLED) {
      chrome.runtime.sendMessage({ action: ACTIONS.TAB_READING_DISABLED });
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
    const response = await chrome.runtime.sendMessage({
      action: ACTIONS.GET_CURRENT_ONYX_DOMAIN,
    });
    if (response && response[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN]) {
      setIframeSrc(
        response[CHROME_SPECIFIC_STORAGE_KEYS.ONYX_DOMAIN] + SIDE_PANEL_PATH,
        "",
      );
    } else {
      console.warn("Onyx domain not found, using default");
      const domain = await getOnyxDomain();
      setIframeSrc(domain + SIDE_PANEL_PATH, "");
    }
  }

  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === ACTIONS.OPEN_ONYX_WITH_INPUT) {
      setIframeSrc(request.url, request.pageUrl);
    } else if (request.action === ACTIONS.UPDATE_PAGE_URL) {
      sendWebsiteToIframe(request.pageUrl);
    } else if (request.action === ACTIONS.TAB_URL_UPDATED) {
      if (iframe.contentWindow) {
        iframe.contentWindow.postMessage(
          { type: CHROME_MESSAGE.TAB_URL_UPDATED, url: request.url },
          getIframeOrigin(),
        );
      }
    }
  });

  window.addEventListener("message", handleMessage);

  initializePanel();
  startIframeLoadTimeout();
})();
