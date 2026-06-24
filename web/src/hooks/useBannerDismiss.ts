"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Per-device dismissal for a banner, persisted in localStorage under `key`.
 * Pass `undefined` for a non-dismissible banner (always visible, no close
 * button). The key encodes whatever should re-show the banner — e.g. a license
 * stage or a banner id — so a new value resurfaces it.
 */
export function useBannerDismiss(key: string | undefined): {
  dismissed: boolean;
  dismiss: () => void;
} {
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || !key) {
      setDismissed(false);
      return;
    }
    setDismissed(window.localStorage.getItem(key) === "1");
  }, [key]);

  const dismiss = useCallback(() => {
    if (typeof window !== "undefined" && key) {
      window.localStorage.setItem(key, "1");
    }
    setDismissed(true);
  }, [key]);

  return { dismissed, dismiss };
}
