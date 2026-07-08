import { describe, expect, it } from "@jest/globals";

import { timeAgo } from "@/lib/time";

function daysAgo(days: number): string {
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
}

describe("timeAgo", () => {
  it("labels sub-year deltas by the largest fitting unit", () => {
    expect(timeAgo(daysAgo(0))).toBe("just now");
    expect(timeAgo(daysAgo(3))).toBe("3d ago");
    expect(timeAgo(daysAgo(40))).toBe("1mo ago");
    expect(timeAgo(daysAgo(200))).toBe("6mo ago");
  });

  it("labels ~1-year-old dates as '1y ago' (no '0y ago' gap)", () => {
    // Regression: the ~360-day window used to fall between days/30 and days/365.
    expect(timeAgo(daysAgo(363))).toBe("1y ago");
    expect(timeAgo(daysAgo(400))).toBe("1y ago");
  });

  it("returns null for unparseable input", () => {
    expect(timeAgo("not-a-date")).toBeNull();
  });
});
