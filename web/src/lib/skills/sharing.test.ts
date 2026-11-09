import { serializeSkillSharing } from "@/lib/skills/sharing";
import { customFixture } from "@/lib/skills/__fixtures__/picker";

it.each([null, "VIEWER", "EDITOR"] as const)(
  "omits company settings without global authority, preserving visibility %s",
  (public_permission) => {
    const draft = customFixture({
      user_permission: "OWNER",
      public_permission,
      installation_policy: "DEFAULT",
      group_shares: [{ group_id: 7, group_name: "Team", permission: "EDITOR" }],
    });
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
