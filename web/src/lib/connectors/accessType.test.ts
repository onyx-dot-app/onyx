import { isPermSynced, toWireAccess } from "@/lib/connectors/accessType";

describe("toWireAccess", () => {
  it("restricts a synced connector when groups are chosen", () => {
    expect(
      toWireAccess("sync", {
        restrict_access_to_groups: true,
        restriction_group_ids: [3, 7],
      })
    ).toEqual({
      access_type: "sync_restricted",
      restriction_group_ids: [3, 7],
    });
  });

  it("keeps plain sync when the switch is on but no groups are chosen", () => {
    expect(
      toWireAccess("sync", {
        restrict_access_to_groups: true,
        restriction_group_ids: [],
      })
    ).toEqual({ access_type: "sync", restriction_group_ids: [] });
  });

  it("drops stale groups when the switch is off", () => {
    expect(
      toWireAccess("sync", {
        restrict_access_to_groups: false,
        restriction_group_ids: [3],
      })
    ).toEqual({ access_type: "sync", restriction_group_ids: [] });
  });

  it("never restricts non-synced access types", () => {
    for (const accessType of ["public", "private"] as const) {
      expect(
        toWireAccess(accessType, {
          restrict_access_to_groups: true,
          restriction_group_ids: [3],
        })
      ).toEqual({ access_type: accessType, restriction_group_ids: [] });
    }
  });
});

describe("isPermSynced", () => {
  it("treats both synced types as synced", () => {
    expect(isPermSynced("sync")).toBe(true);
    expect(isPermSynced("sync_restricted")).toBe(true);
    expect(isPermSynced("private")).toBe(false);
    expect(isPermSynced("public")).toBe(false);
  });
});
