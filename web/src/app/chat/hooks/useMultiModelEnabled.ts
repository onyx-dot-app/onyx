import { useEffect, useState } from "react";

/**
 * Feature flag hook that checks if multi-model chat is enabled via cookie.
 * Set cookie `multi-model-enabled=true` to enable the feature.
 *
 * Example (in browser console):
 *   document.cookie = "multi-model-enabled=true";
 */
export function useMultiModelEnabled(): boolean {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    const cookies = document.cookie.split(";");
    const multiModelCookie = cookies.find((c) =>
      c.trim().startsWith("multi-model-enabled=")
    );
    if (multiModelCookie) {
      const value = multiModelCookie.split("=")[1]?.trim();
      setEnabled(value === "true");
    }
  }, []);

  return enabled;
}
