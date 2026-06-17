import React from "react";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { OnyxLoader } from "@/refresh-components/OnyxLoader";

interface PageLoaderProps {
  /** Label shown beneath the mark. Default: "Loading …". */
  text?: string;
  className?: string;
}

/**
 * Full-page loading state: the animated Onyx mark with a "Loading …" label,
 * centered within the available space. Use this for page/route-level loading
 * (e.g. while a page's data is being fetched). For an inline or section-level
 * loader without a label, use `OnyxLoader` directly.
 */
export function PageLoader({ text = "Loading …", className }: PageLoaderProps) {
  return (
    <div
      className={cn(
        "flex h-full min-h-[60vh] w-full flex-col items-center justify-center gap-3 p-5",
        className
      )}
    >
      <OnyxLoader />
      <Text font="main-ui-muted" color="text-03">
        {text}
      </Text>
    </div>
  );
}

export default PageLoader;
