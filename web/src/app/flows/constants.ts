/**
 * Routes and page-level constants for the flows UI.
 */

import type { Route } from "next";

export const FLOWS_API_BASE = "/api/flows";

export const FLOWS_PATH = "/flows" satisfies Route;

export function flowDetailPath(flowId: string): Route {
  // SAFETY: matches the `/flows/[id]` segment that typed routes generate;
  // the id is a UUID from the API, so it needs no escaping.
  return `${FLOWS_PATH}/${flowId}` as Route;
}

export function flowRunPath(flowId: string, runId: string): Route {
  // SAFETY: matches `/flows/[id]/runs/[runId]`; both ids are API UUIDs.
  return `${FLOWS_PATH}/${flowId}/runs/${runId}` as Route;
}

/** Page size for the run history table. */
export const RUNS_PAGE_SIZE = 25;

/** How often a page with an in-flight run re-checks it. */
export const RUN_POLL_INTERVAL_MS = 3000;

/** Zoom bounds for the canvas. */
export const MIN_ZOOM = 0.4;
export const MAX_ZOOM = 1.75;
export const ZOOM_STEP = 0.15;
