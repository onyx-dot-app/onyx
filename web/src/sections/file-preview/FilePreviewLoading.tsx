"use client";

import { useEffect, useState } from "react";
import { OnyxLoader, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import type { RichStr } from "@opal/types";

// A fast load shows nothing; a slower one shows the loader
const LOADER_DELAY_MS = 300;

interface FilePreviewLoadingProps {
  // A line under the loader, read out by screen readers
  status?: string | RichStr;
}

export function FilePreviewLoading({ status }: FilePreviewLoadingProps) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setVisible(true), LOADER_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, []);
  return (
    <Section gap={1}>
      {visible && <OnyxLoader size={32} />}
      <div aria-live="polite">
        {visible && status && (
          <Text as="p" font="secondary-body" color="text-03">
            {status}
          </Text>
        )}
      </div>
    </Section>
  );
}
