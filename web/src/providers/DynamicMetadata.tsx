"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { useSettings } from "@/lib/settings/hooks";

export default function DynamicMetadata() {
  const { appName, logoUrl } = useSettings();
  const pathname = usePathname();

  useEffect(() => {
    if (document.title !== appName) {
      document.title = appName;
    }
  }, [appName, pathname]);

  return <link rel="icon" href={logoUrl ?? "/onyx.ico"} />;
}
