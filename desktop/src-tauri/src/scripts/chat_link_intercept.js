(() => {
  if (window.__ONYX_CHAT_LINK_INTERCEPT_INSTALLED__) {
    return;
  }

  window.__ONYX_CHAT_LINK_INTERCEPT_INSTALLED__ = true;

  function isChatSessionPage() {
    try {
      const trustedOrigin = window.__ONYX_TRUSTED_ORIGIN__;
      if (!trustedOrigin) {
        return false;
      }

      const currentUrl = new URL(window.location.href);
      return (
        currentUrl.origin === trustedOrigin &&
        currentUrl.pathname.startsWith("/app") &&
        currentUrl.searchParams.has("chatId")
      );
    } catch {
      return false;
    }
  }

  function getAllowedNavigationUrl(rawUrl) {
    try {
      const parsed = new URL(String(rawUrl), window.location.href);
      const scheme = parsed.protocol.toLowerCase();
      if (!["http:", "https:", "mailto:", "tel:"].includes(scheme)) {
        return null;
      }
      return parsed;
    } catch {
      return null;
    }
  }

  async function openWithTauri(url) {
    try {
      const invoke =
        window.__TAURI__?.core?.invoke || window.__TAURI_INTERNALS__?.invoke;
      if (typeof invoke !== "function") {
        return false;
      }

      await invoke("open_in_browser", { url });
      return true;
    } catch {
      return false;
    }
  }

  function handleChatNavigation(rawUrl) {
    const parsedUrl = getAllowedNavigationUrl(rawUrl);
    if (!parsedUrl) {
      return false;
    }

    const safeUrl = parsedUrl.toString();
    const scheme = parsedUrl.protocol.toLowerCase();
    if (scheme === "mailto:" || scheme === "tel:") {
      void openWithTauri(safeUrl).then((opened) => {
        if (!opened) {
          window.location.assign(safeUrl);
        }
      });
      return true;
    }

    window.location.assign(safeUrl);
    return true;
  }

  document.addEventListener(
    "click",
    (event) => {
      if (!isChatSessionPage() || event.defaultPrevented) {
        return;
      }

      const element = event.target;
      if (!(element instanceof Element)) {
        return;
      }

      const anchor = element.closest("a");
      if (!(anchor instanceof HTMLAnchorElement)) {
        return;
      }

      const target = (anchor.getAttribute("target") || "").toLowerCase();
      if (target !== "_blank") {
        return;
      }

      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("#")) {
        return;
      }

      if (!handleChatNavigation(href)) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
    },
    true
  );

  const nativeWindowOpen = window.open;
  window.open = function(url, target, features) {
    const resolvedTarget = typeof target === "string" ? target.toLowerCase() : "";
    const shouldNavigateInPlace = resolvedTarget === "" || resolvedTarget === "_blank";

    if (
      isChatSessionPage() &&
      shouldNavigateInPlace &&
      url != null &&
      String(url).length > 0
    ) {
      if (!handleChatNavigation(url)) {
        return null;
      }
      return null;
    }

    if (typeof nativeWindowOpen === "function") {
      return nativeWindowOpen.call(window, url, target, features);
    }
    return null;
  };
})();
