// Custom title bar for Onyx Desktop
// This script injects a draggable title bar that matches Onyx design system

(function () {
  console.log("[Onyx Desktop] Title bar script loaded");

  const TITLEBAR_ID = "onyx-desktop-titlebar";
  const TITLEBAR_HEIGHT = 36;
  const STYLE_ID = "onyx-desktop-titlebar-style";

  // Wait for DOM to be ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  function getInvoke() {
    if (window.__TAURI__?.core?.invoke) return window.__TAURI__.core.invoke;
    if (window.__TAURI__?.invoke) return window.__TAURI__.invoke;
    if (window.__TAURI_INTERNALS__?.invoke)
      return window.__TAURI_INTERNALS__.invoke;
    return null;
  }

  async function startWindowDrag() {
    const invoke = getInvoke();

    if (invoke) {
      try {
        await invoke("start_drag_window");
        return;
      } catch (err) {
        console.error(
          "[Onyx Desktop] Failed to start dragging via invoke:",
          err,
        );
      }
    }

    const appWindow =
      window.__TAURI__?.window?.getCurrent?.() ??
      window.__TAURI__?.window?.appWindow;

    if (appWindow?.startDragging) {
      try {
        await appWindow.startDragging();
      } catch (err) {
        console.error(
          "[Onyx Desktop] Failed to start dragging via appWindow:",
          err,
        );
      }
    } else {
      console.error("[Onyx Desktop] No Tauri drag API available.");
    }
  }

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      body {
        padding-top: ${TITLEBAR_HEIGHT}px !important;
      }

      #${TITLEBAR_ID} {
        cursor: default !important;
        -webkit-user-select: none !important;
        user-select: none !important;
        -webkit-app-region: drag;
        background: rgba(255, 255, 255, 0.85);
      }

      /* Dark mode support */
      .dark #${TITLEBAR_ID} {
        background: linear-gradient(180deg, rgba(18, 18, 18, 0.82) 0%, rgba(18, 18, 18, 0.72) 100%);
        border-bottom-color: rgba(255, 255, 255, 0.08);
      }
    `;
    document.head.appendChild(style);
  }

  function buildTitleBar() {
    const titleBar = document.createElement("div");
    titleBar.id = TITLEBAR_ID;
    titleBar.setAttribute("data-tauri-drag-region", "");

    titleBar.addEventListener("mousedown", (e) => {
      // Only start drag on left click and not on buttons/inputs
      const nonDraggable = [
        "BUTTON",
        "INPUT",
        "TEXTAREA",
        "A",
        "SELECT",
        "OPTION",
      ];
      if (e.button === 0 && !nonDraggable.includes(e.target.tagName)) {
        e.preventDefault();
        startWindowDrag();
      }
    });

    // Apply styles matching Onyx design system with translucent glass effect
    titleBar.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      height: ${TITLEBAR_HEIGHT}px;
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.94) 0%, rgba(255, 255, 255, 0.78) 100%);
      border-bottom: 1px solid rgba(0, 0, 0, 0.06);
      box-shadow: 0 8px 28px rgba(0, 0, 0, 0.04);
      z-index: 999999;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: default;
      user-select: none;
      -webkit-user-select: none;
      font-family: 'Hanken Grotesk', -apple-system, BlinkMacSystemFont, sans-serif;
      backdrop-filter: blur(18px) saturate(180%);
      -webkit-backdrop-filter: blur(18px) saturate(180%);
      -webkit-app-region: drag;
      padding: 0 12px;
    `;

    return titleBar;
  }

  function mountTitleBar() {
    if (!document.body) {
      console.error("[Onyx Desktop] document.body not found");
      return;
    }

    const existing = document.getElementById(TITLEBAR_ID);
    if (existing?.parentElement === document.body) {
      return;
    }

    if (existing) {
      existing.remove();
    }

    const titleBar = buildTitleBar();
    document.body.insertBefore(titleBar, document.body.firstChild);
    injectStyles();
    console.log("[Onyx Desktop] Title bar injected");
  }

  function init() {
    mountTitleBar();

    // Keep it around even if the app DOM re-renders
    const observer = new MutationObserver(() => {
      if (!document.getElementById(TITLEBAR_ID)) {
        mountTitleBar();
      }
    });

    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
    });

    // Fallback keep-alive check
    setInterval(() => {
      if (!document.getElementById(TITLEBAR_ID)) {
        mountTitleBar();
      }
    }, 1500);
  }
})();
