"use client";

import { createContext, useContext } from "react";

/** The admin top bar's element while the sidebar is an overlay, else null. */
export const AdminTopBarSlotContext = createContext<HTMLElement | null>(null);

/** Where a page portals a control to sit beside the sidebar button, or null to render it in place. */
export function useAdminTopBar(): HTMLElement | null {
  return useContext(AdminTopBarSlotContext);
}
