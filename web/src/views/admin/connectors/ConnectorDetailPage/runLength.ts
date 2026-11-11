import type { useFormatter } from "next-intl";

/** A run's length in its two largest units in short form, such as "16 sec", "4 min 12 sec" or "1 hr 5 min". */
export function formatRunLength(
  format: ReturnType<typeof useFormatter>,
  ms: number,
): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const units = [
    { unit: "hour", value: Math.floor(total / 3600) },
    { unit: "minute", value: Math.floor(total / 60) % 60 },
    { unit: "second", value: total % 60 },
  ];
  // From the largest nonzero unit, or seconds for an instant run. A zero trailing unit is dropped, as in "2 min" or "1 hr".
  const first = units.findIndex((part) => part.value > 0);
  const from = first === -1 ? units.length - 1 : first;
  return format.list(
    units
      .slice(from, from + 2)
      .filter((part, index) => index === 0 || part.value > 0)
      .map(({ unit, value }) =>
        format.number(value, { style: "unit", unit, unitDisplay: "short" }),
      ),
    { type: "unit", style: "narrow" },
  );
}
