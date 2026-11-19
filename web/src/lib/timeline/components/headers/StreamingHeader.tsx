"use client";

import { TextLoader } from "@opal/loaders";

export interface StreamingHeaderProps {
  headerText: string;
}

/** The working run's title: shimmer text with its current activity. */
export function StreamingHeader({ headerText }: StreamingHeaderProps) {
  return (
    <div className="flex-1 min-w-0 px-(--timeline-header-text-padding-x) py-(--timeline-header-text-padding-y)">
      <TextLoader>{headerText}</TextLoader>
    </div>
  );
}
