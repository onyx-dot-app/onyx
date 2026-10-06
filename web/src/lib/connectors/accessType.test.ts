import {
  isPermSynced,
  toManageAccess,
  toWireAccess,
} from "@/lib/connectors/accessType";
import { createConnectorValidationSchema } from "@/lib/connectors/utils";
import { ValidSources } from "@/lib/connectors/types/source";

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

describe("toManageAccess", () => {
  it("pairs each manage group with its role, defaulting to editor", () => {
    expect(toManageAccess([1, 2, 3], { "2": "operator" })).toEqual([
      { group_id: 1, role: "editor" },
      { group_id: 2, role: "operator" },
      { group_id: 3, role: "editor" },
    ]);
  });
});

describe("Specific Groups validation", () => {
  const REQUIRED = "Pick at least one group.";
  const schema = createConnectorValidationSchema(ValidSources.Web, false, {
    specificGroupsRequired: REQUIRED,
  });

  it("requires a reader group for private access", async () => {
    await expect(
      schema.validateAt("data_access_group_ids", {
        access_type: "private",
        data_access_group_ids: [],
      })
    ).rejects.toThrow(REQUIRED);
  });

  it("accepts private access with a group, and other access without one", async () => {
    await expect(
      schema.validateAt("data_access_group_ids", {
        access_type: "private",
        data_access_group_ids: [3],
      })
    ).resolves.toEqual([3]);
    await expect(
      schema.validateAt("data_access_group_ids", {
        access_type: "public",
        data_access_group_ids: [],
      })
    ).resolves.toEqual([]);
  });
});
