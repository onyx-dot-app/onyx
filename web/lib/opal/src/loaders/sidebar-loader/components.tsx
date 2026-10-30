"use client";

import "@opal/loaders/styles.css";
import { Section } from "@opal/layouts/general/components";
import { useOpalStrings } from "@opal/strings";
import { cn } from "@opal/utils";

// Label widths the tabs cycle through, so a stack reads as a list.
const LABEL_WIDTHS = ["w-3/4", "w-1/2", "w-2/3"] as const;

interface SidebarLoaderProps {
  /** How many sidebar tabs to stand in for. @default 1 */
  count?: number;
  /** Stand in for the folded sidebar's icon-only tabs. @default false */
  folded?: boolean;
}

/**
 * Sidebar tabs that have not loaded: shimmering labels in a sidebar tab's
 * footprint, so the real tabs take their place without a shift. Folded, each
 * tab is a shimmering icon.
 */
function SidebarLoader({ count = 1, folded = false }: SidebarLoaderProps) {
  const strings = useOpalStrings();
  return (
    <Section
      role="status"
      aria-label={strings.loading}
      height="fit"
      gap={0}
      className="opal-sidebar-loader"
    >
      {Array.from({ length: count }, (_, index) => (
        <Section
          key={index}
          aria-hidden
          flexDirection="row"
          justifyContent="start"
          height="fit"
          gap={0}
          padding={1.5}
        >
          <Section
            flexDirection="row"
            justifyContent="start"
            height="fit"
            gap={0}
            padding={0.5}
            className="min-h-6 ms-0.5"
          >
            <div
              className={cn(
                "opal-shimmer-block",
                folded
                  ? "size-4 rounded-full"
                  : cn("h-3 rounded-04", LABEL_WIDTHS[index % 3])
              )}
            />
          </Section>
        </Section>
      ))}
    </Section>
  );
}

export { SidebarLoader, type SidebarLoaderProps };
