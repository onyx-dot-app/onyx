import { canReadSkillHistory, canShareSkill } from "@/lib/skills/permissions";
import {
  builtinFixture,
  customFixture,
} from "@/lib/skills/__fixtures__/picker";

describe("skill history authority", () => {
  it.each([false, true])(
    "allows editors of synced skills independently of sharing (personal: %s)",
    (personal) => {
      const skill = customFixture({
        user_permission: "EDITOR",
        marketplace: {
          id: "market",
          name: "Source",
          folder: null,
          personal,
          follows_access: true,
          can_share: false,
        },
      });
      expect(canReadSkillHistory(skill)).toBe(true);
      expect(canShareSkill({ skill })).toBe(false);
    }
  );

  it("excludes viewers, built-ins and retired skills", () => {
    expect(canReadSkillHistory(customFixture())).toBe(false);
    expect(
      canReadSkillHistory(builtinFixture({ user_permission: "OWNER" }))
    ).toBe(false);
    expect(
      canReadSkillHistory(
        customFixture({
          user_permission: "OWNER",
          retired_at: "2026-11-08T12:00:00Z",
        })
      )
    ).toBe(false);
    expect(
      canReadSkillHistory(customFixture({ user_permission: "OWNER" }))
    ).toBe(true);
  });
});
