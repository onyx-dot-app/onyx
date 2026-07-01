import { formatTokens } from "@/app/craft/utils/formatTokens";

describe("formatTokens", () => {
  it.each([
    [0, "0"],
    [999, "999"],
    [1000, "1K"],
    [1500, "1.5K"],
    [15526, "15.5K"],
    [99949, "99.9K"],
    [148400, "148K"],
    [200000, "200K"],
    // Boundary: must roll to "1M", never "1000K".
    [999499, "999K"],
    [999999, "1M"],
    [1000000, "1M"],
    [1500000, "1.5M"],
    [12000000, "12M"],
  ])("formats %i as %s", (input, expected) => {
    expect(formatTokens(input)).toBe(expected);
  });
});
