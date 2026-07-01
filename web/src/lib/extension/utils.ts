export type ExtensionContext = "new_tab" | "side_panel" | null;

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
