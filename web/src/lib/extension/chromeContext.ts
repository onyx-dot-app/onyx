import { CHROME_MESSAGE } from "@/lib/extension/constants";

/** The side panel's window and tab in Chrome, as the extension reports them. */
export interface ChromeContext {
  installation_id: string;
  window_id: number;
  tab_id: number;
}

/** The context in a `BROWSER_CONTEXT` message, or null for any other data. */
export function parseChromeContext(
  message: MessageEvent<unknown>
): ChromeContext | null {
  const data: unknown = message.data;
  if (
    typeof data !== "object" ||
    data === null ||
    !("type" in data) ||
    data.type !== CHROME_MESSAGE.BROWSER_CONTEXT ||
    !("installation_id" in data) ||
    !("window_id" in data) ||
    !("tab_id" in data)
  )
    return null;
  const { installation_id, window_id, tab_id } = data;
  if (
    typeof installation_id !== "string" ||
    typeof window_id !== "number" ||
    typeof tab_id !== "number"
  )
    return null;
  return { installation_id, window_id, tab_id };
}

let latest: ChromeContext | null = null;

export function getChromeContext(): ChromeContext | null {
  return latest;
}

export function setChromeContext(context: ChromeContext | null): void {
  latest = context;
}
