"use client";

import "@opal/loaders/styles.css";
import { useOpalStrings } from "@opal/strings";

/**
 * A select or combo box that has not loaded: a shimmering block in the
 * input's shape, as tall and as rounded, filling its column.
 */
function DropdownLoader() {
  const strings = useOpalStrings();
  return (
    <div
      role="status"
      aria-label={strings.loading}
      className="opal-shimmer-block h-9 w-full rounded-08"
    />
  );
}

export { DropdownLoader };
