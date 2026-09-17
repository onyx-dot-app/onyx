import { describe, expect, it } from "@jest/globals";

import { formatDurationSeconds, timeAgo } from "@/lib/time";

function daysAgo(days: number): string {
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
}

describe("formatDurationSeconds", () => {
  it("renders sub-minute durations in whole seconds, rounding up", () => {
    expect(formatDurationSeconds(0)).toBe("0s");
    expect(formatDurationSeconds(4)).toBe("4s");
    expect(formatDurationSeconds(4.2)).toBe("5s");
    expect(formatDurationSeconds(59)).toBe("59s");
  });

  it("switches to minutes, dropping a zero seconds remainder", () => {
    expect(formatDurationSeconds(60)).toBe("1m");
    expect(formatDurationSeconds(75)).toBe("1m 15s");
    expect(formatDurationSeconds(120)).toBe("2m");
    expect(formatDurationSeconds(3661)).toBe("61m 1s");
  });
});

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
