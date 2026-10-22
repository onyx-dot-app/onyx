import { windowCoversAllHistory } from "@/lib/connectors/edit/window";

describe("windowCoversAllHistory", () => {
  it("is true for a window that starts at the epoch", () => {
    expect(windowCoversAllHistory("1970-01-01T00:00:00Z")).toBe(true);
  });

  it("is false for a window with a later start", () => {
    expect(windowCoversAllHistory("2025-03-04T05:06:07Z")).toBe(false);
  });
});
