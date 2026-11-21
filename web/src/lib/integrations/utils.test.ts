import { parsePositiveId } from "@/lib/integrations/utils";

describe("route ID boundary", () => {
  test.each(["7", "0007", String(Number.MAX_SAFE_INTEGER)])(
    "accepts positive safe integer %s",
    (value) => {
      expect(parsePositiveId(value)).toBe(Number(value));
    }
  );

  test.each([
    undefined,
    "",
    "0",
    "-7",
    "7.1",
    "7abc",
    "1e2",
    "0x7",
    "Infinity",
    "NaN",
    " 7",
    "9007199254740992",
  ])("rejects an invalid ID %s", (value) => {
    expect(parsePositiveId(value)).toBeNull();
  });
});
