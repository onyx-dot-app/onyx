import { useEffect } from "react";
export function sendSetDefaultNewTabMessage(value: boolean) {
  if (typeof window !== "undefined" && window.parent) {
    window.parent.postMessage({ type: "SET_DEFAULT_NEW_TAB", value }, "*");
  }
}

export const sendMessageToParent = () => {
  if (typeof window !== "undefined" && window.parent) {
    window.parent.postMessage({ type: "ONYX_APP_LOADED" }, "*");
  }
};
export const useSendMessageToParent = () => {
  useEffect(() => {
    sendMessageToParent();
  }, []);
};
