"use client";

import { createContext, type RefObject } from "react";

/**
 * The app chrome's workspace: the row that holds the page column and the
 * right panel slot. An output panel in the slot measures the row for its
 * width, and makes the page column inert while it covers it. The elements
 * stay the same, so the chrome never re-renders for a width change.
 */
export const AppWorkspaceElementsContext = createContext<{
  workspace: RefObject<HTMLDivElement | null>;
  page: RefObject<HTMLDivElement | null>;
} | null>(null);
