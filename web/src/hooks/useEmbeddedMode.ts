"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";

const EMBEDDED_MODE_SESSION_STORAGE_KEY = "onyx:embedded-mode";

let embeddedModeSeenInSession = false;

/**
 * Detects whether the app is running in embedded mode (e.g., inside a
 * Canvas LMS iframe via the LTI launch flow).
 *
 * Embedded mode is triggered by the `?embedded=true` query parameter,
 * which is set by the LTI launch redirect, and persists for the current
 * browser tab so client navigation cannot accidentally restore app chrome.
 */
export function useEmbeddedMode(): boolean {
  const searchParams = useSearchParams();
  const embeddedParam = searchParams.get(SEARCH_PARAM_NAMES.EMBEDDED);
  const hasEmbeddedParam = embeddedParam === "true";
  const clearsEmbeddedParam = embeddedParam === "false";
  const [isEmbedded, setIsEmbedded] = useState(
    hasEmbeddedParam || embeddedModeSeenInSession
  );

  useEffect(() => {
    if (hasEmbeddedParam) {
      embeddedModeSeenInSession = true;
      window.sessionStorage.setItem(EMBEDDED_MODE_SESSION_STORAGE_KEY, "true");
      setIsEmbedded(true);
      return;
    }

    if (clearsEmbeddedParam) {
      embeddedModeSeenInSession = false;
      window.sessionStorage.removeItem(EMBEDDED_MODE_SESSION_STORAGE_KEY);
      setIsEmbedded(false);
      return;
    }

    if (
      embeddedModeSeenInSession ||
      window.sessionStorage.getItem(EMBEDDED_MODE_SESSION_STORAGE_KEY) ===
        "true"
    ) {
      embeddedModeSeenInSession = true;
      setIsEmbedded(true);
      return;
    }

    setIsEmbedded(false);
  }, [clearsEmbeddedParam, hasEmbeddedParam]);

  return hasEmbeddedParam || isEmbedded;
}
