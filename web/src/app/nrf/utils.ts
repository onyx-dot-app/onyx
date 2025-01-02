import { useEffect } from "react";
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
