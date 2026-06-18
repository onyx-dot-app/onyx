"use client";

import { useCustomAnalyticsScript } from "@/lib/analytics/hooks";
import { useEffect, useRef } from "react";

export default function CustomAnalyticsScript() {
  const customAnalyticsScript = useCustomAnalyticsScript();
  const injectedRef = useRef(false);

  useEffect(() => {
    if (!customAnalyticsScript || injectedRef.current) return;
    injectedRef.current = true;

    const script = document.createElement("script");
    script.type = "text/javascript";
    script.textContent = customAnalyticsScript;
    document.head.appendChild(script);
  }, [customAnalyticsScript]);

  return null;
}
