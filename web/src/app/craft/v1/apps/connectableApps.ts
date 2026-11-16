import { useSearchParams } from "@opal/navigation";
import { useEffect, useState } from "react";

/** Which system a connectable came from. Surfaced to the user: the two are
 * connected and governed differently, so a row must never be ambiguous. */
export type ConnectableKind = "app" | "mcp";

/** Query param selecting the Apps page tab. Exported so deep-link producers
 * (e.g. the input-bar picker) and the page can't disagree on the contract. */
export const CRAFT_APPS_TAB_PARAM = "tab";

/** Tab order shared by the member and admin Apps pages. */
export const KIND_ORDER: ConnectableKind[] = ["app", "mcp"];

export function parseConnectableTab(value: string | null): ConnectableKind {
  return value === "mcp" ? "mcp" : "app";
}

/** Tab state that follows the deep-linkable `?tab=` param — including on a
 * client-side navigation to the same page, which doesn't remount. */
export function useConnectableTab(): [
  ConnectableKind,
  (tab: ConnectableKind) => void,
] {
  const urlTab = parseConnectableTab(
    useSearchParams().get(CRAFT_APPS_TAB_PARAM)
  );
  const [tab, setTab] = useState<ConnectableKind>(urlTab);
  useEffect(() => setTab(urlTab), [urlTab]);
  return [tab, setTab];
}
