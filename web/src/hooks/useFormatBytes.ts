import { useCallback } from "react";
import { useFormatter } from "next-intl";

const BYTE_UNITS = ["byte", "kilobyte", "megabyte", "gigabyte"] as const;

/** A binary size in the viewer's locale, such as "500 MB" for 500 MiB. */
export function useFormatBytes(): (bytes: number) => string {
  const format = useFormatter();
  return useCallback(
    (bytes: number) => {
      let value = bytes;
      let unit = 0;
      while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
        value /= 1024;
        unit += 1;
      }
      return format.number(value, {
        style: "unit",
        unit: BYTE_UNITS[unit],
        unitDisplay: "short",
        maximumFractionDigits: 1,
      });
    },
    [format]
  );
}
