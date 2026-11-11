/** How a closed activity card reads: resolved by Retry or by an admin, or superseded. */
import { closedBySupersede } from "@/views/admin/connectors/ConnectorDetailPage/closedRun";

const RESOLVED_AT = "2026-01-01T00:00:00Z";

describe("closedBySupersede", () => {
  it("reads a superseded run nobody resolved as superseded", () => {
    expect(closedBySupersede({ resolved_at: null, superseded: true })).toBe(
      true
    );
  });

  it("reads a resolved run as resolved, superseded or not", () => {
    expect(
      closedBySupersede({ resolved_at: RESOLVED_AT, superseded: true })
    ).toBe(false);
    expect(
      closedBySupersede({ resolved_at: RESOLVED_AT, superseded: false })
    ).toBe(false);
  });

  it("reads a run Retry closed as resolved", () => {
    expect(closedBySupersede({ resolved_at: null, superseded: false })).toBe(
      false
    );
  });
});
