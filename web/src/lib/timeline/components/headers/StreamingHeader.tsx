"use client";

import { TextLoader } from "@opal/loaders";
import { Section } from "@opal/layouts";
import type { IconFunctionComponent } from "@opal/types";

export interface StreamingHeaderProps {
  headerText: string;
  /** The icon before the text, as every run header has one. */
  icon?: IconFunctionComponent;
}

/** The working run's title: an icon and shimmer text with its activity. */
export function StreamingHeader({
  headerText,
  icon: Icon,
}: StreamingHeaderProps) {
  return (
    // The same layout as `CompletedHeader`; only the shimmer differs.
    <Section
      flexDirection="row"
      justifyContent="start"
      gap={1}
      height="fit"
      className="opal-line-title font-main-ui-action flex-1 min-w-0 mx-(--timeline-header-text-padding-x) my-(--timeline-header-text-padding-y)"
    >
      {Icon && <Icon className="shrink-0 w-4 h-4" />}
      <TextLoader>{headerText}</TextLoader>
    </Section>
  );
}
