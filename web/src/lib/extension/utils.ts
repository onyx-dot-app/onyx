export type ExtensionContext = "new_tab" | "side_panel" | null;

// Returns the origin of the Chrome extension panel (our parent frame).
// window.location.ancestorOrigins is Chrome-specific and only populated
// when the page is loaded inside an iframe (e.g. the Chrome extension panel).
// Falls back to "*" in regular browser contexts (no parent frame).
export function getPanelOrigin(): string {
  return window.location.ancestorOrigins?.[0] ?? "*";
}

export function getExtensionContext(): {
  isExtension: boolean;
  context: ExtensionContext;
} {
  if (typeof window === "undefined")
    return { isExtension: false, context: null };

  const pathname = window.location.pathname;
  if (pathname.includes("/nrf/side-panel")) {
    return { isExtension: true, context: "side_panel" };
  }
  if (pathname.includes("/nrf")) {
    return { isExtension: true, context: "new_tab" };
  }
  return { isExtension: false, context: null };
}
