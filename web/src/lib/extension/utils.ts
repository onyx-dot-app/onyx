import { useEffect } from "react";
import { CHROME_MESSAGE } from "./constants";
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
