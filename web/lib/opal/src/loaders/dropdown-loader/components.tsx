"use client";

import "@opal/loaders/styles.css";
import { SvgChevronDownSmall } from "@opal/icons";
import { Section } from "@opal/layouts/general/components";
import { useOpalStrings } from "@opal/strings";

/**
 * A select or combo box that has not loaded: the input's resting chrome
 * (border, background, radius, padding) holding a shimmering icon and label
 * and the chevron, in the trigger's layout. Fills its column.
 */
function DropdownLoader() {
  const strings = useOpalStrings();
  return (
    <Section
      role="status"
      aria-label={strings.loading}
      flexDirection="row"
      justifyContent="start"
      height="fit"
      gap={0}
      padding={1.5}
      className="rounded-08 border border-border-01 bg-background-neutral-00"
    >
      <Section width="fit" height="fit" gap={0} className="ms-0.5 me-1">
        <div className="opal-shimmer-block size-4 rounded-full" />
      </Section>
      <Section
        flexDirection="row"
        height="fit"
        gap={0}
        padding={0.5}
        className="min-h-6 flex-1"
      >
        <div className="opal-shimmer-block h-3 w-full rounded-04" />
      </Section>
      {/* The select's chevron as a plain icon, in its button's footprint:
          nothing here can be pressed yet. */}
      <Section width={1.5} height={1.5} gap={0}>
        <SvgChevronDownSmall className="size-4 text-text-03" />
      </Section>
    </Section>
  );
}

export { DropdownLoader };
