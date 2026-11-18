"use client";

import { useEffect, useState } from "react";
import { OnyxLoader } from "@opal/components";
import { Section } from "@opal/layouts";

/** Fast previews stay quiet; slower loads use the shared section loader. */
export function FilePreviewLoading() {
  const [visible, setVisible] = useState(false);
  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- timer that shows the loader only when a preview takes over 300ms
  useEffect(() => {
    const timer = window.setTimeout(() => setVisible(true), 300);
    return () => window.clearTimeout(timer);
  }, []);
  return <Section gap={0}>{visible && <OnyxLoader size={32} />}</Section>;
}
