"use client";

import "@opal/loaders/styles.css";
import { SvgChevronDownSmall } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";

/**
 * A select or combo box that has not loaded: the input's resting chrome
 * (border, background, radius, padding) holding a shimmering icon and label
 * and the chevron, in the trigger's layout. Fills its column.
 */
function DropdownLoader() {
  const strings = useOpalStrings();
  return (
    <div
      role="status"
      aria-label={strings.loading}
      className="flex w-full flex-row items-center rounded-08 border border-border-01 bg-background-neutral-00 p-1.5"
    >
      <div className="flex shrink-0 items-center justify-center ps-0.5 pe-1">
        <div className="opal-shimmer-block size-4 rounded-full" />
      </div>
      <div className="flex min-h-6 flex-1 items-center p-0.5">
        <div className="opal-shimmer-block h-3 w-full rounded-04" />
      </div>
      {/* The select's chevron as a plain icon, in its button's footprint:
          nothing here can be pressed yet. */}
      <div className="flex size-6 shrink-0 items-center justify-center">
        <SvgChevronDownSmall className="size-4 text-text-03" />
      </div>
    </div>
  );
}

export { DropdownLoader };
