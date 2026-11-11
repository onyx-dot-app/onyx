"use client";

import "@opal/loaders/styles.css";
import { useId } from "react";
import { Section } from "@opal/layouts/general/components";
import {
  LineLoader,
  type LineLoaderWidth,
} from "@opal/loaders/line-loader/components";
import { pick, seededRandom, type NonEmpty } from "@opal/loaders/random";
import { useOpalStrings } from "@opal/strings";

// The label widths a random tab picks from.
const LABEL_WIDTHS: NonEmpty<LineLoaderWidth> = ["1/2", "2/3", "3/4"];

interface SidebarLoaderProps {
  /** How many sidebar tabs to stand in for. @default 1 */
  count?: number;
  /** Width of every tab's label. Unset, each tab picks a random width. */
  width?: LineLoaderWidth;
  /** Stand in for the folded sidebar's icon-only tabs. @default false */
  folded?: boolean;
}

/**
 * Sidebar tabs that have not loaded: shimmering labels in a sidebar tab's
 * footprint, so the real tabs take their place without a shift. Folded, each
 * tab is a shimmering icon.
 */
function SidebarLoader({
  count = 1,
  width,
  folded = false,
}: SidebarLoaderProps) {
  const strings = useOpalStrings();
  const random = seededRandom(useId());
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
            {folded ? (
              <div className="opal-shimmer-block size-4 rounded-full" />
            ) : (
              <LineLoader width={width ?? pick(LABEL_WIDTHS, random)} />
            )}
          </Section>
        </Section>
      ))}
    </Section>
  );
}

export { SidebarLoader, type SidebarLoaderProps };
