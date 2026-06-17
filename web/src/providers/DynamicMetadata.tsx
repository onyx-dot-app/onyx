"use client";

import { useEffect } from "react";
import { useSettings } from "@/lib/settings/hooks";

export default function DynamicMetadata() {
  const { appName, logoUrl } = useSettings();

  useEffect(() => {
    if (document.title !== appName) {
      document.title = appName;
    }
  }, [appName]);

  return <link rel="icon" href={logoUrl ?? "/onyx.ico"} />;
}
