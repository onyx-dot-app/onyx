"use client";

import { createContext, useContext } from "react";

/**
 * Effective fold state of the enclosing sidebar, provided by `SidebarRoot`.
 *
 * This is the value `SidebarRoot` derives from the raw `useSidebarState`
 * fold state — it accounts for the mobile and small-screen overlays, and for
 * a non-foldable sidebar, which never folds on desktop.
 *
 * The default is `false`, so a component outside any `SidebarRoot` reads as
 * unfolded. `SidebarTab` is used for page-level tab navigation as well as in
 * sidebars, and those tabs must not collapse when the app sidebar folds.
 */
export const SidebarFoldedContext = createContext(false);

/** Fold state of the enclosing sidebar. `false` outside a `SidebarRoot`. */
export function useSidebarFolded(): boolean {
  return useContext(SidebarFoldedContext);
}
