"use client";

import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";

/**
 * Detects whether the app is running in embedded mode (e.g., inside a
 * Canvas LMS iframe via the LTI launch flow).
 *
 * Embedded mode is triggered by the `?embedded=true` query parameter,
 * which is set by the LTI launch redirect.
 */
export function useEmbeddedMode(): boolean {
  const searchParams = useSearchParams();
  return searchParams.get(SEARCH_PARAM_NAMES.EMBEDDED) === "true";
}
