import {
  humanReadableFormat,
  humanReadableFormatShort,
  timeAgo,
} from "@opal/time";

const minutesAgo = (n: number) =>
  new Date(Date.now() - n * 60_000).toISOString();
const daysAgo = (n: number) => minutesAgo(n * 24 * 60);

describe("timeAgo", () => {
  it("returns null without a date or with an unparseable one", () => {
    expect(timeAgo(null, "en")).toBeNull();
    expect(timeAgo(undefined, "en")).toBeNull();
    expect(timeAgo("not a date", "en")).toBeNull();
  });

  it("never reads as the future, even for a timestamp just ahead of now", () => {
    expect(timeAgo(minutesAgo(-2), "en")).toBe("0 seconds ago");
  });

  it("renders whole minutes, hours, days, months and years in English", () => {
    expect(timeAgo(minutesAgo(42), "en")).toBe("42 minutes ago");
    expect(timeAgo(minutesAgo(5 * 60), "en")).toBe("5 hours ago");
    expect(timeAgo(daysAgo(12), "en")).toBe("12 days ago");
    expect(timeAgo(daysAgo(14 + 30), "en")).toBe("1 month ago");
    expect(timeAgo(daysAgo(3 * 365), "en")).toBe("3 years ago");
  });

  it("follows the locale", () => {
    // Digit shaping for bare "ar" differs between ICU builds, so only the words are asserted.
    expect(timeAgo(daysAgo(3), "ar")).toMatch(/^قبل .* أيام$/);
    expect(timeAgo(daysAgo(3), "de")).toBe("vor 3 Tagen");
  });

  it("shapes digits from the numbering system on the locale tag", () => {
    expect(timeAgo(daysAgo(3), "ar-u-nu-arab")).toBe("قبل ٣ أيام");
  });
});

describe("date formatters", () => {
  // Local midnight, so the calendar day is the same in every test timezone.
  const june6 = new Date(2026, 5, 6).toISOString();

  it("formats in the requested locale", () => {
    expect(humanReadableFormatShort(june6, "en")).toBe("Jun 6, 2026");
    expect(humanReadableFormatShort(june6, "de")).toBe("6. Juni 2026");
    expect(humanReadableFormat(june6, "fr")).toBe("6 juin 2026");
    expect(humanReadableFormatShort(june6, "ar-u-nu-arab")).toContain("٢٠٢٦");
  });

  it("returns an empty string for a missing short date", () => {
    expect(humanReadableFormatShort(null, "en")).toBe("");
  });
});
