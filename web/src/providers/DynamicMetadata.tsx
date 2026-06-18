"use client";

import { useEffect, useMemo } from "react";
import { useSettings } from "@/lib/settings/hooks";

export default function DynamicMetadata() {
  const settings = useSettings();
  const { appName } = settings;

  useEffect(() => {
    if (document.title !== appName) {
      document.title = appName;
    }
  }, [appName]);

  // Cache-buster so the favicon re-fetches after an admin uploads a new logo.
  const cacheBuster = useMemo(
    () => Date.now(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [settings.enterprise]
  );

  const favicon = settings.enterprise?.use_custom_logo
    ? `/api/enterprise-settings/logo?v=${cacheBuster}`
    : "/onyx.ico";

  return <link rel="icon" href={favicon} />;
}
