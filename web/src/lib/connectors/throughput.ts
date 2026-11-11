// Bar counts a chart may draw, most first. The spec caps at 72. Each splits the 1h and 24h windows into whole bins per tick.
const BIN_COUNTS = [72, 60, 48, 36, 30, 24, 18, 12] as const;
// The API's floor.
const FEWEST_BINS = 12;
// Narrower slots leave no visible gap between bars.
const MIN_SLOT_PX = 9.5;

/** The most bars that keep each slot at least `MIN_SLOT_PX` wide, or the fewest when none fits. */
export function binsForWidth(width: number): number {
  return BIN_COUNTS.find((bins) => width / bins >= MIN_SLOT_PX) ?? FEWEST_BINS;
}

/** The browser's UTC offset in minutes east, the sign the API takes; getTimezoneOffset counts west. */
export function browserUtcOffsetMinutes(): number {
  return -new Date().getTimezoneOffset();
}
