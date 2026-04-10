"use client";

import { useSearchParams } from "next/navigation";

/**
 * Detects whether the app is running in embedded mode (e.g., inside a
 * Canvas LMS iframe via the LTI launch flow).
 *
 * Embedded mode is triggered by the `?embedded=true` query parameter,
 * which is set by the LTI launch redirect.
 */
export function useEmbeddedMode(): boolean {
  const searchParams = useSearchParams();
  return searchParams.get("embedded") === "true";
}
