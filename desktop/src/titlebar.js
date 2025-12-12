// Custom title bar for Onyx Desktop
// This script injects a draggable title bar that matches Onyx design system

(function () {
  console.log("[Onyx Desktop] Title bar script loaded");

  const TITLEBAR_ID = "onyx-desktop-titlebar";
  const TITLEBAR_HEIGHT = 36;

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

  async function init() {
    console.log("[Onyx Desktop] Initializing title bar");

    // Remove any existing title bar
    const existing = document.getElementById(TITLEBAR_ID);
    if (existing) {
      existing.remove();
    }

    // Create title bar element
    const titleBar = document.createElement("div");
    titleBar.id = TITLEBAR_ID;
    titleBar.setAttribute("data-tauri-drag-region", "");

    // Make it draggable using Tauri's API
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
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.9) 0%, rgba(255, 255, 255, 0.72) 100%);
      border-bottom: 1px solid rgba(0, 0, 0, 0.05);
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

    // Insert at the beginning of body
    if (document.body) {
      document.body.insertBefore(titleBar, document.body.firstChild);

      // Add padding to body to account for title bar
      const style = document.createElement("style");
      style.textContent = `
        body {
          padding-top: ${TITLEBAR_HEIGHT}px !important;
        }

        #onyx-desktop-titlebar {
          cursor: default !important;
          -webkit-user-select: none !important;
          user-select: none !important;
          -webkit-app-region: drag;
          background: rgba(255, 255, 255, 0.72);
        }

        /* Dark mode support */
        .dark #onyx-desktop-titlebar {
          background: linear-gradient(180deg, rgba(18, 18, 18, 0.82) 0%, rgba(18, 18, 18, 0.72) 100%);
          border-bottom-color: rgba(255, 255, 255, 0.08);
        }
      `;
      document.head.appendChild(style);

      console.log("[Onyx Desktop] Title bar injected successfully");
    } else {
      console.error("[Onyx Desktop] document.body not found");
    }
  }
})();
