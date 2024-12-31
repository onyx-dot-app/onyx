import { useEffect } from "react";
export const sendMessageToParent = () => {
  if (typeof window !== "undefined" && window.parent) {
    console.log("Sending message to parent");
    window.parent.postMessage({ type: "ONYX_APP_LOADED" }, "*");
  } else {
    console.log("No parent window found");
  }
};

export const useSendMessageToParent = () => {
  useEffect(() => {
    sendMessageToParent();
  }, []);
};
