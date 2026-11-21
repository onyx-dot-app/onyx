// Injected into the main window (the server's web UI). It only restyles the
// page; it calls no app command.
//
// - The web app reserves a 36px strip for desktop v1 (`html.onyx-desktop`);
//   v2 removes it on pages with the chat layout, whose own rows drag the
//   window. Other pages (the web sign-in page after a session expires) keep
//   the strip, and a fixed drag strip covers it.
// - The sidebar runs to the window's top edge. Its logo row becomes the
//   traffic-light row: the logo is hidden, the collapse button sits at the
//   row's right end in line with the lights, and the rest moves up.
// - Collapsed, the sidebar disappears and the collapse
//   button stays beside the traffic lights. In full screen, where macOS hides
//   the lights, the button sits at the left edge whether open or collapsed.
// - The sidebar's top row and the chat area's top bar drag the window
//   (Tauri's `data-tauri-drag-region`).
//
// The traffic lights are native and do not scale with page zoom (Cmd+=/-), so
// every size tied to them is given in screen points and divided by the zoom.
// The shell calls `window.__onyxDesktop.sync(zoom, fullscreen)`
// after each page load, zoom change and full-screen change.
//
// Not gated on `html.onyx-desktop`: the theme script replaces <html>'s classes,
// and this script only runs inside the desktop window.
(() => {
  if (window.top !== window) return;

  // Wide windows lay the sidebar out as a column; below the web app's
  // `md` breakpoint (912 CSS px, so also when zoomed in) it is an overlay.
  const SIDEBAR = ":is(.opal-sidebar-root__column, .opal-sidebar-root__overlay)";
  const FOLDED = `${SIDEBAR}[data-folded="true"]`;
  const FULLSCREEN = 'html[data-onyx-fullscreen="true"]';
  const TOGGLE = 28; // the collapse button's size in CSS px (scales with zoom)
  const state = { zoom: 1, fullscreen: false };

  // Concrete values are written into the stylesheet on every sync: WebKit does
  // not always restyle fixed elements when only a root custom property changes.
  // The expanded sidebar width in CSS px. WebKit cannot animate between a
  // calc() that holds var() and a plain length (the transition sticks at its
  // start), so every animated value is a plain px length.
  function sidebarWidth() {
    const root = document.documentElement;
    const raw = getComputedStyle(root).getPropertyValue("--sidebar-width-expanded").trim();
    const value = parseFloat(raw);
    if (!Number.isFinite(value)) return 240;
    if (raw.endsWith("rem")) return value * parseFloat(getComputedStyle(root).fontSize || "16");
    return value;
  }

  const css = () => {
  // Screen points (unaffected by zoom) -> CSS px at the current zoom.
  const pt = (n) => `${(n / state.zoom).toFixed(3)}px`;
  const expanded = sidebarWidth();
  return `
    :root:has(.opal-root-layout) { --onyx-desktop-titlebar-height: 0px; }
    /* Without the page-wide inset, toasts and modals still keep clear of the
       traffic-light row (30pt at any zoom), as in Safari. */
    :root:has(.opal-root-layout) .opal-toast-viewport {
      top: calc(${pt(30)} + 0.5rem) !important;
    }
    :root:has(.opal-root-layout) .opal-modal-positioner {
      --opal-modal-top: calc(${pt(30)} + var(--opal-modal-gap)) !important;
    }
    /* Small windows: the web app adds its own open-sidebar button to the chat
       header. The app's fold button is always there, so show only that one. */
    :root:has(.opal-sidebar-header__fold-button)
      .opal-root-layout__header
      button:has(path[d^="M6 2V14M3.33333 2H12.6667"]) {
      display: none !important;
    }
    /* A drag strip for pages that have no other drag area: pages without the
       chat layout, and chat-layout pages without the chat header (agents,
       settings) while the sidebar is folded. It sits under the fold button. */
    #onyx-desktop-drag-strip {
      position: fixed;
      inset: 0 0 auto 0;
      height: var(--onyx-titlebar-height, 36px);
      z-index: 55;
    }
    :root:has(.opal-root-layout) #onyx-desktop-drag-strip { height: ${pt(30)}; }
    :root:has(.opal-root-layout__header) #onyx-desktop-drag-strip,
    :root:has(${SIDEBAR}:not([data-folded="true"])) #onyx-desktop-drag-strip {
      display: none;
    }
    .opal-sidebar-header__mark,
    .opal-sidebar-header__wordmark { display: none !important; }

    /* The traffic-light row: 30pt tall at any zoom. */
    .opal-sidebar-header__topbar {
      padding-top: 0 !important;
      height: ${pt(30)} !important;
      margin-bottom: ${pt(-6)} !important;
    }
    .opal-sidebar-header__brand { height: ${pt(30)} !important; }

    /* One timing for every part of the fold, so it reads as one slide. */
    :root {
      --onyx-fold-duration: var(--duration-sidebar-fold, 200ms);
      --onyx-fold-ease: cubic-bezier(0.2, 0, 0, 1);
    }

    /* The column's width animates; its contents keep the expanded width and
       layout, so they slide out of view instead of reflowing. */
    ${SIDEBAR} {
      overflow: hidden !important;
      transition: width var(--onyx-fold-duration) var(--onyx-fold-ease) !important;
    }
    ${SIDEBAR}:not([data-folded="true"]) { width: ${expanded}px !important; }
    /* The overlay keeps a folded-width spacer in the page; the folded sidebar
       here has no width, so neither does the spacer. */
    .opal-sidebar-root__spacer { width: 0 !important; min-width: 0 !important; }
    .opal-sidebar-root__inner {
      width: ${expanded}px !important;
      min-width: ${expanded}px !important;
    }
    .opal-sidebar-root__inner[data-folded="true"] .opal-sidebar-body__content {
      display: flex !important;
    }
    /* The folded sidebar (header, body and footer) stays laid out for the
       slide, then leaves the tab order and the accessibility tree once the
       slide ends. Only the fold button stays reachable. */
    .opal-sidebar-root__inner { transition: visibility 0s; }
    .opal-sidebar-root__inner[data-folded="true"] {
      visibility: hidden;
      transition: visibility 0s linear var(--onyx-fold-duration);
    }
    .opal-sidebar-header__fold-button { visibility: visible !important; }
    ${FOLDED} { width: 0 !important; }
    /* The mobile overlay slides with a transform, which would also make it the
       containing block of the fixed fold button and clip it. The width
       animation above replaces that slide. */
    .opal-sidebar-root__overlay[data-variant="mobile"] {
      transform: none !important;
      translate: none !important; /* Tailwind v4's translate-x-* set this */
    }

    /* The toggle keeps one fixed position and moves between the sidebar's
       right end and the spot beside the traffic lights. Its centre sits 17pt
       from the top, level with the lights. */
    .opal-sidebar-header__fold-button {
      position: fixed !important;
      top: calc(${pt(17)} - ${TOGGLE / 2}px) !important;
      left: ${expanded - TOGGLE - 12}px !important;
      inset-inline-end: auto !important;
      opacity: 1 !important;
      z-index: 60 !important;
      transition: left var(--onyx-fold-duration) var(--onyx-fold-ease) !important;
    }
    /* Right-to-left pages put the sidebar on the right; the open toggle sits
       at its inner end there. The traffic lights stay on the left. */
    [dir="rtl"] .opal-sidebar-header__fold-button {
      left: auto !important;
      right: ${expanded - TOGGLE - 12}px !important;
    }
    ${FOLDED} .opal-sidebar-header__fold-button { left: ${pt(76)} !important; right: auto !important; }
    /* Full screen hides the lights: the toggle stays at the left edge, open or
       collapsed. */
    /* ${SIDEBAR} makes this outrank the folded position above. */
    ${FULLSCREEN} ${SIDEBAR} .opal-sidebar-header__fold-button {
      left: ${pt(12)} !important;
      right: auto !important;
    }

    /* The header keeps clear of the traffic lights and the toggle. They are
       always on the physical left, so this uses padding-left, also on
       right-to-left pages. */
    .opal-root-layout__header {
      transition: padding-left var(--onyx-fold-duration) var(--onyx-fold-ease);
    }
    .opal-root-layout:has(${FOLDED}) .opal-root-layout__header {
      padding-left: calc(${pt(84)} + ${TOGGLE}px) !important;
    }
    ${FULLSCREEN} .opal-root-layout:has(${FOLDED}) .opal-root-layout__header {
      padding-left: calc(${pt(20)} + ${TOGGLE}px) !important;
    }
    /* Right to left, the open sidebar is on the right, so the header starts
       under the traffic lights (and, in full screen, the toggle). */
    [dir="rtl"] .opal-root-layout:not(:has(${FOLDED})) .opal-root-layout__header {
      padding-left: ${pt(84)} !important;
    }
    ${FULLSCREEN}[dir="rtl"] .opal-root-layout:not(:has(${FOLDED})) .opal-root-layout__header,
    ${FULLSCREEN} [dir="rtl"] .opal-root-layout:not(:has(${FOLDED})) .opal-root-layout__header {
      padding-left: calc(${pt(20)} + ${TOGGLE}px) !important;
    }
  `;
  };

  const DRAG_SELECTORS = [
    ".opal-sidebar-header__topbar",
    ".opal-sidebar-header__topbar-inner",
    ".opal-sidebar-header__brand",
    ".opal-root-layout__header",
  ].join(",");

  let rendered = "";

  function applyState() {
    const root = document.documentElement;
    if (!root) return;
    root.setAttribute("data-onyx-fullscreen", String(state.fullscreen));
    const style = document.getElementById("onyx-desktop-chrome");
    const text = css();
    if (style && text !== rendered) {
      style.textContent = text;
      rendered = text;
    }
  }

  function install() {
    if (!document.head) return;
    if (!document.getElementById("onyx-desktop-chrome")) {
      const style = document.createElement("style");
      style.id = "onyx-desktop-chrome";
      document.head.appendChild(style);
      rendered = "";
      applyState();
    }
  }

  // Added after hydration so React sees the server's attributes first.
  // "deep": empty space anywhere inside the row drags; buttons, links and
  // inputs inside it keep working (Tauri's drag script skips them).
  function markDragRegions() {
    document.querySelectorAll(DRAG_SELECTORS).forEach((el) => {
      if (el.getAttribute("data-tauri-drag-region") !== "deep") {
        el.setAttribute("data-tauri-drag-region", "deep");
      }
    });
  }

  // Outside <body>, so React never sees it; added after hydration.
  function installDragStrip() {
    if (document.getElementById("onyx-desktop-drag-strip")) return;
    const strip = document.createElement("div");
    strip.id = "onyx-desktop-drag-strip";
    strip.setAttribute("data-tauri-drag-region", "");
    document.documentElement.appendChild(strip);
  }

  window.__onyxDesktop = {
    sync(zoom, fullscreen) {
      state.zoom = Number(zoom) > 0 ? Number(zoom) : 1;
      state.fullscreen = Boolean(fullscreen);
      applyState();
    },
  };

  // Only added nodes can hold a new drag region, so the page (and streaming
  // chat answers) is not rescanned on every change. The stylesheet changes
  // only on sync(), so it is not rebuilt here.
  function markAdded(node) {
    if (!(node instanceof Element)) return;
    if (node.matches(DRAG_SELECTORS)) node.setAttribute("data-tauri-drag-region", "deep");
    if (node.firstElementChild) {
      node.querySelectorAll(DRAG_SELECTORS).forEach((el) => {
        el.setAttribute("data-tauri-drag-region", "deep");
      });
    }
  }

  new MutationObserver((mutations) => {
    if (!document.getElementById("onyx-desktop-chrome")) install();
    if (document.readyState !== "complete") return;
    installDragStrip();
    for (const mutation of mutations) mutation.addedNodes.forEach(markAdded);
  }).observe(document, { childList: true, subtree: true });
  document.addEventListener("DOMContentLoaded", install);
  window.addEventListener("load", () => {
    install();
    installDragStrip();
    markDragRegions();
    applyState();
  });
})();
