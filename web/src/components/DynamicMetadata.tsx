"use client";

import { useEffect } from "react";
import { useSettingsContext } from "@/providers/SettingsProvider";

export default function DynamicMetadata() {
  const { enterpriseSettings } = useSettingsContext();

  useEffect(() => {
    const title = enterpriseSettings?.application_name || "Onyx";
    if (document.title !== title) {
      document.title = title;
    }

    const favicon = enterpriseSettings?.use_custom_logo
      ? "/api/enterprise-settings/logo"
      : "/onyx.ico";

    const link =
      document.querySelector<HTMLLinkElement>('link[rel="icon"]') ??
      (() => {
        const el = document.createElement("link");
        el.rel = "icon";
        document.head.appendChild(el);
        return el;
      })();

    if (!link.href.endsWith(favicon)) {
      link.href = favicon;
    }
  }, [enterpriseSettings]);

  return null;
}
