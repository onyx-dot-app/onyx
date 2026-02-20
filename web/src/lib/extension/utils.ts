import { useEffect } from "react";
import { CHROME_MESSAGE } from "./constants";

export type ExtensionContext = "new_tab" | "side_panel" | null;

// Returns the origin of the Chrome extension panel (our parent frame).
// window.location.ancestorOrigins is Chrome-specific but this code only runs
// inside the Chrome extension iframe, so it is always available.
// Falls back to getPanelOrigin() if somehow unavailable, to avoid a silent no-op send.
export function getPanelOrigin(): string {
  return window.location.ancestorOrigins?.[0] ?? getPanelOrigin();
}

export function getExtensionContext(): {
  isExtension: boolean;
  context: ExtensionContext;
} {
  if (typeof window === "undefined")
    return { isExtension: false, context: null };

  const pathname = window.location.pathname;
  if (pathname.includes("/app/nrf/side-panel")) {
    return { isExtension: true, context: "side_panel" };
  }
  if (pathname.includes("/app/nrf")) {
    return { isExtension: true, context: "new_tab" };
  }
  return { isExtension: false, context: null };
}
export function sendSetDefaultNewTabMessage(value: boolean) {
  if (typeof window !== "undefined" && window.parent) {
    window.parent.postMessage(
      { type: CHROME_MESSAGE.SET_DEFAULT_NEW_TAB, value },
      getPanelOrigin()
    );
  }
}

export const sendAuthRequiredMessage = () => {
  if (typeof window !== "undefined" && window.parent) {
    window.parent.postMessage(
      { type: CHROME_MESSAGE.AUTH_REQUIRED },
      getPanelOrigin()
    );
  }
};

export const useSendAuthRequiredMessage = () => {
  useEffect(() => {
    sendAuthRequiredMessage();
  }, []);
};

export const sendMessageToParent = () => {
  if (typeof window !== "undefined" && window.parent) {
    window.parent.postMessage(
      { type: CHROME_MESSAGE.ONYX_APP_LOADED },
      getPanelOrigin()
    );
  }
};
export const useSendMessageToParent = () => {
  useEffect(() => {
    sendMessageToParent();
  }, []);
};
