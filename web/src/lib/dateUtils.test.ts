import { formatDateLog, formatDateTimeLog } from "@/lib/dateUtils";

describe("formatDateTimeLog", () => {
  it("prints a zero-padded 24-hour local stamp", () => {
    expect(formatDateTimeLog("2026-03-03T09:02:05")).toBe(
      "2026/03/03 09:02:05"
    );
    expect(formatDateTimeLog("2026-03-23T23:02:45")).toBe(
      "2026/03/23 23:02:45"
    );
  });
});

describe("formatDateLog", () => {
  it("prints only the date", () => {
    expect(formatDateLog("2026-06-13T08:00:00")).toBe("2026/06/13");
  });
});
