"use client";

import { createContext, useContext } from "react";

/** What a form field may do to the form's capability checks. */
export interface ConnectorCheckActions {
  /**
   * Runs one check now, ignoring its cached result. It shows the checks
   * unless `showChecks` is false, e.g. for a listing a field refreshes.
   */
  runCheck: (checkId: string, options?: { showChecks?: boolean }) => void;
}

const ConnectorCheckActionsContext =
  createContext<ConnectorCheckActions | null>(null);

export const ConnectorCheckActionsProvider =
  ConnectorCheckActionsContext.Provider;

/** The form's check actions; null outside a form that runs checks. */
export function useConnectorCheckActions(): ConnectorCheckActions | null {
  return useContext(ConnectorCheckActionsContext);
}
