import { useCallback } from "react";
import { type NumberFormatOptions, useFormatter } from "next-intl";

const BYTE_UNITS = [
  "byte",
  "kilobyte",
  "megabyte",
  "gigabyte",
  "terabyte",
] as const;

interface ByteSizeFormat {
  value: number;
  options: NumberFormatOptions;
}

/**
 * A binary size as a value in the largest unit that keeps it at 1 or more,
 * with the number format that shows it, for callers that need its parts.
 */
export function byteSizeFormat(bytes: number): ByteSizeFormat {
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return {
    value,
    options: {
      style: "unit",
      unit: BYTE_UNITS[unit],
      unitDisplay: "short",
      maximumFractionDigits: 1,
    },
  };
}

/** A binary size in the viewer's locale, such as "500 MB" for 500 MiB. */
export function useFormatBytes(): (bytes: number) => string {
  const format = useFormatter();
  return useCallback(
    (bytes: number) => {
      const { value, options } = byteSizeFormat(bytes);
      return format.number(value, options);
    },
    [format]
  );
}
