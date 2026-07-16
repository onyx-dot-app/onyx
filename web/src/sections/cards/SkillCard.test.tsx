import { render, screen, setupUser } from "@tests/setup/test-utils";
import SkillCard, {
  type BuiltinSkillCardItem,
  type CustomSkillCardItem,
} from "@/sections/cards/SkillCard";
import type { CustomSkill } from "@/lib/skills/types";

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ appName: "Onyx" }),
}));

function builtIn(
  overrides: Partial<BuiltinSkillCardItem> = {}
): BuiltinSkillCardItem {
  return {
    id: "skill-id",
    name: "Browser",
    description: "Browse the web",
    source: "builtin",
    enabled: true,
    can_toggle: false,
    is_available: true,
    ...overrides,
  };
}

function custom(overrides: Partial<CustomSkill> = {}): CustomSkillCardItem {
  const skill: CustomSkill = {
    source: "custom",
    id: "custom-skill-id",
    slug: "report-writer",
    name: "Report Writer",
    description: "Draft reports",
    is_available: null,
    unavailable_reason: null,
    is_valid: true,
    is_personal: true,
    enabled: true,
    can_toggle: true,
    author_user_id: "user-id",
    author_email: "owner@example.com",
    owner: { id: "user-id", email: "owner@example.com" },
    ownership_vacant: false,
    created_at: null,
    updated_at: null,
    user_shares: [],
    group_shares: [],
    public_permission: null,
    user_permission: "OWNER",
    ...overrides,
  };
  return {
    id: skill.id,
    name: skill.name,
    description: skill.description,
    source: "custom",
    skill,
    enabled: skill.enabled,
    can_toggle: skill.can_toggle,
    author_email: skill.author_email,
    is_personal: true,
  };
}

function invalidCustom(): CustomSkillCardItem {
  return custom({
    id: "invalid-skill-id",
    slug: "invalid-skill",
    name: "Invalid skill",
    description: "Invalid bundle",
    is_valid: false,
    enabled: false,
    can_toggle: false,
  });
}

describe("SkillCard", () => {
  it("does not render a preference switch for native built-ins", () => {
    render(<SkillCard item={builtIn()} />);

    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("reports user preference changes for toggleable skills", async () => {
    const user = setupUser();
    const item = custom();
    const onEnabledChange = jest.fn();
    render(<SkillCard item={item} onEnabledChange={onEnabledChange} />);

    await user.click(
      screen.getByRole("switch", { name: "Disable Report Writer" })
    );

    expect(onEnabledChange).toHaveBeenCalledWith(item, false);
  });

  it("directs users to recreate invalid skills without showing a switch", () => {
    render(<SkillCard item={invalidCustom()} />);

    expect(screen.getByText("Invalid")).toBeInTheDocument();
    expect(
      screen.getByText("Delete this invalid skill and create a new one.")
    ).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });
});
