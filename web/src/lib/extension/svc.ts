import { CHROME_MESSAGE } from "@/lib/extension/constants";
import { getPanelOrigin } from "@/lib/extension/utils";

export function sendSetDefaultNewTabMessage(value: boolean): void {
  if (typeof window !== "undefined" && window.parent !== window) {
    window.parent.postMessage(
      { type: CHROME_MESSAGE.SET_DEFAULT_NEW_TAB, value },
      getPanelOrigin()
    );
  }
}

export function sendAuthRequiredMessage(): void {
  if (typeof window !== "undefined" && window.parent !== window) {
    window.parent.postMessage(
      { type: CHROME_MESSAGE.AUTH_REQUIRED },
      getPanelOrigin()
    );
  }
}

export function sendMessageToParent(): void {
  if (typeof window !== "undefined" && window.parent !== window) {
    window.parent.postMessage(
      { type: CHROME_MESSAGE.ONYX_APP_LOADED },
      getPanelOrigin()
    );
  }
}
