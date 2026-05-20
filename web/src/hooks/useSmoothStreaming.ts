import Cookies from "js-cookie";
import { useCallback, useEffect, useState } from "react";

import { SMOOTH_STREAMING_COOKIE_NAME } from "@/lib/constants";

const CHANGE_EVENT = "smoothStreaming:change";
const DEFAULT_ENABLED = true;
const COOKIE_EXPIRES_DAYS = 365;

function readCookie(): boolean {
  const value = Cookies.get(SMOOTH_STREAMING_COOKIE_NAME);
  if (value === undefined) return DEFAULT_ENABLED;
  return value !== "false";
}

interface UseSmoothStreamingResult {
  enabled: boolean;
  setEnabled: (next: boolean) => void;
}

export function useSmoothStreaming(): UseSmoothStreamingResult {
  const [enabled, setEnabledState] = useState<boolean>(() =>
    typeof window === "undefined" ? DEFAULT_ENABLED : readCookie()
  );

  useEffect(() => {
    setEnabledState(readCookie());
    const handler = () => setEnabledState(readCookie());
    window.addEventListener(CHANGE_EVENT, handler);
    return () => window.removeEventListener(CHANGE_EVENT, handler);
  }, []);

  const setEnabled = useCallback((next: boolean) => {
    Cookies.set(SMOOTH_STREAMING_COOKIE_NAME, String(next), {
      expires: COOKIE_EXPIRES_DAYS,
    });
    setEnabledState(next);
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);

  return { enabled, setEnabled };
}
