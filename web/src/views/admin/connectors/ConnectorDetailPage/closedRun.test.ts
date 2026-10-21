/** How a closed activity card reads: resolved by Retry or by an admin, or superseded. */
import { closedByResolution } from "@/views/admin/connectors/ConnectorDetailPage/closedRun";

describe("closedByResolution", () => {
  it("reads a closed errors run as resolved whichever path resolved it", () => {
    expect(closedByResolution({ resolved_at: null }, "errors")).toBe(true);
    expect(
      closedByResolution({ resolved_at: "2026-01-01T00:00:00Z" }, "errors")
    ).toBe(true);
  });

  it("reads a closed failure as resolved only when an admin resolved it", () => {
    expect(
      closedByResolution({ resolved_at: "2026-01-01T00:00:00Z" }, "failures")
    ).toBe(true);
    expect(closedByResolution({ resolved_at: null }, "failures")).toBe(false);
  });
});
