import {
  serializeSkillSharing,
  type SkillSharingDraft,
} from "@/lib/skills/sharing";
import { customFixture } from "@/lib/skills/__fixtures__/picker";

it.each([null, "VIEWER", "EDITOR"] as const)(
  "omits company settings without global authority, preserving visibility %s",
  (public_permission) => {
    const draft: SkillSharingDraft = {
      ...customFixture({
        user_permission: "OWNER",
        public_permission,
        installation_policy: "DEFAULT",
      }),
      group_shares: [{ group_id: 7, group_name: "Team", permission: "EDITOR" }],
    };
    expect(
      JSON.parse(JSON.stringify(serializeSkillSharing(draft, false)))
    ).toEqual({
      user_shares: [],
      group_shares: [{ group_id: 7, permission: "EDITOR" }],
    });
  }
);
it("serializes company settings for a global holder", () => {
  expect(
    serializeSkillSharing(
      customFixture({
        user_permission: "EDITOR",
        public_permission: "VIEWER",
        installation_policy: "REQUIRED",
      }),
      true
    )
  ).toMatchObject({
    public_permission: "VIEWER",
    installation_policy: "REQUIRED",
  });
});

it("sends a group override only when the draft sets or clears it", () => {
  const draft: SkillSharingDraft = {
    ...customFixture({ user_permission: "OWNER" }),
    group_shares: [
      { group_id: 1, group_name: "Kept", permission: "VIEWER" },
      {
        group_id: 2,
        group_name: "Cleared",
        permission: "VIEWER",
        installation_policy: null,
      },
      {
        group_id: 3,
        group_name: "Hidden",
        permission: "EDITOR",
        installation_policy: "NOT_AVAILABLE",
      },
    ],
  };
  expect(serializeSkillSharing(draft, false).group_shares).toStrictEqual([
    { group_id: 1, permission: "VIEWER" },
    { group_id: 2, permission: "VIEWER", installation_policy: null },
    {
      group_id: 3,
      permission: "EDITOR",
      installation_policy: "NOT_AVAILABLE",
    },
  ]);
});
