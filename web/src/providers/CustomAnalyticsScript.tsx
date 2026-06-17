"use client";

import { useEffect, useRef } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useSettings } from "@/lib/settings/hooks";
import { EE_ENABLED } from "@/lib/constants";

export default function CustomAnalyticsScript() {
  const { isLoading, error, ee_features_enabled } = useSettings();
  const shouldFetch =
    EE_ENABLED || (!isLoading && !error && ee_features_enabled !== false);
  const { data: customAnalyticsScript } = useSWR<string>(
    shouldFetch ? SWR_KEYS.customAnalyticsScript : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
      dedupingInterval: 60_000,
    }
  );
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
