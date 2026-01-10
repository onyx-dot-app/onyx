import { useEffect } from "react";
import { CHROME_MESSAGE } from "./constants";

export type ExtensionContext = "new_tab" | "side_panel" | null;

export function getExtensionContext(): {
  isExtension: boolean;
  context: ExtensionContext;
} {
  if (typeof window === "undefined")
    return { isExtension: false, context: null };

  const pathname = window.location.pathname;
  if (pathname.includes("/chat/nrf/side-panel")) {
    return { isExtension: true, context: "side_panel" };
  }
  if (pathname.includes("/chat/nrf")) {
    return { isExtension: true, context: "new_tab" };
  }
  return { isExtension: false, context: null };
}
export function sendSetDefaultNewTabMessage(value: boolean) {
  if (typeof window !== "undefined" && window.parent) {
    window.parent.postMessage(
      { type: CHROME_MESSAGE.SET_DEFAULT_NEW_TAB, value },
      "*"
    );
  }
}

export const sendAuthRequiredMessage = () => {
  if (typeof window !== "undefined" && window.parent) {
    window.parent.postMessage({ type: CHROME_MESSAGE.AUTH_REQUIRED }, "*");
  }
};

export const useSendAuthRequiredMessage = () => {
  useEffect(() => {
    sendAuthRequiredMessage();
  }, []);
};

export const sendMessageToParent = () => {
  if (typeof window !== "undefined" && window.parent) {
    window.parent.postMessage({ type: CHROME_MESSAGE.ONYX_APP_LOADED }, "*");
  }
};
export const useSendMessageToParent = () => {
  useEffect(() => {
    sendMessageToParent();
  }, []);
};

export function notifyExtensionOfThemeChange(
  newTheme: string,
  newBgUrl: string
) {
  if (typeof window !== "undefined" && window.parent) {
    window.parent.postMessage(
      {
        type: CHROME_MESSAGE.PREFERENCES_UPDATED,
        payload: {
          theme: newTheme,
          backgroundUrl: newBgUrl,
        },
      },
      "*"
    );
  }
}
